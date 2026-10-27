"""Export and import, through the server's own client programs (spec §7.3).

One engine per direction. :class:`DumpStream` is the dump engine: an iterator of
chunks that raises :class:`TransferError` at the end, instead of stopping, when
the program failed, so a truncated dump is never mistaken for a whole one.
``dump`` writes it to a stream or, atomically, to a path. ``load`` (below) peeks
the source's first bytes to detect age encryption, the dump's family and
MariaDB's sandbox line; it never parses SQL (global rule 1).
"""

from __future__ import annotations

import io
import itertools
import os
import subprocess
import threading
import time
import uuid
import weakref
from collections.abc import Iterable, Iterator, Sequence
from contextlib import ExitStack, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

import pymysql

from . import _client
from ._client import ClientTool
from ._observe import VERDICT_KEY, Running, operation
from .connection import Connection
from .credentials import CredentialSource, ResolvedCredentials
from .errors import DatabaseUnreachableError, InvalidArgumentsError, RefusedError, TransferError
from .provision import _as_package_error, _confirmation, _preflight_resolved, _resolve_or_finding
from .server import ServerFamily, ServerInfo, detect_server
from .verdict import Code, Finding, Verdict

CHUNK = 64 * 1024
STDERR_CAP = 64 * 1024

#: Where the option-file pipe is named for the child; absent on Windows.
DEV_FD = Path("/dev/fd")

DUMP_PRIVILEGES = ("SELECT", "SHOW VIEW", "TRIGGER")
LOAD_PRIVILEGES = ("CREATE", "INSERT", "ALTER", "DROP", "INDEX", "REFERENCES", "CREATE VIEW")


@dataclass(frozen=True, slots=True)
class TransferResult:
    """What a dump or load moved, and what its check found."""

    bytes: int
    duration_ms: float
    tool: str
    server: ServerInfo
    verdict: Verdict


class _Stderr:
    """Drains a program's stderr so it can never block, keeping the first STDERR_CAP bytes."""

    def __init__(self, pipe: IO[bytes]) -> None:
        self._pipe = pipe
        self._kept = bytearray()
        self._thread = threading.Thread(target=self._drain, daemon=True)
        self._thread.start()

    def _drain(self) -> None:
        with self._pipe:
            for block in iter(lambda: self._pipe.read(CHUNK), b""):
                room = STDERR_CAP - len(self._kept)
                if room > 0:
                    self._kept += block[:room]

    def text(self, password: str) -> str:
        self._thread.join(timeout=10)
        text = self._kept.decode("utf-8", errors="replace")
        return text.replace(password, "***") if password else text


def _start(
    tool: ClientTool,
    args: Sequence[str],
    credentials: ResolvedCredentials,
    connection: Connection,
    *,
    for_load: bool,
) -> subprocess.Popen[bytes]:
    """Run a client program with its options in a pipe and a minimal environment."""
    with _client.option_pipe(credentials, connection) as fd:
        return subprocess.Popen(  # noqa: S603 - argv built from a found tool and an allow-list
            _client.argv(tool, fd, args),
            stdin=subprocess.PIPE if for_load else subprocess.DEVNULL,
            stdout=subprocess.DEVNULL if for_load else subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_client.child_env(),
            pass_fds=(fd,),
            close_fds=True,
        )


class _DumpRun:
    """A running dump's parts, held apart from its :class:`DumpStream`.

    The stream's finalizer and the encryption thread reference this, never the
    stream, so a stream dropped unfinished can still be collected and stopped.
    """

    def __init__(self, process: subprocess.Popen[bytes], verdict: Verdict, on_finish: Any) -> None:
        if process.stdout is None or process.stderr is None:
            msg = "a dump process needs piped stdout and stderr"
            raise ValueError(msg)
        self.process = process
        self.verdict = verdict
        self.stderr = _Stderr(process.stderr)
        self.reader: IO[bytes] = process.stdout
        self.thread: threading.Thread | None = None
        self.error: BaseException | None = None
        self.bytes = 0
        self._on_finish = on_finish
        self._lock = threading.Lock()

    def notify(self, error: BaseException | None) -> None:
        """Tell ``on_finish`` how the dump ended; only the first call counts."""
        with self._lock:
            callback, self._on_finish = self._on_finish, None
        if callback is not None:
            callback(error, self.bytes)


def _stop(run: _DumpRun) -> None:
    """Kill and reap a dump's program, release its pipes and end its operation."""
    try:
        run.process.kill()
        run.process.wait()
        with suppress(OSError):
            run.reader.close()
        # A collection can run this on the encryption thread itself, which cannot join itself.
        if run.thread is not None and run.thread is not threading.current_thread():
            # Killed, the program closes the plaintext pipe; with the reader closed,
            # a thread blocked writing ciphertext fails with EPIPE.
            run.thread.join(timeout=10)
    finally:
        run.notify(TransferError("dump closed before it finished", run.verdict, None, ""))


def _start_encryption(
    run: _DumpRun,
    *,
    recipients: Sequence[str] | None = None,
    passphrase: str | None = None,
) -> None:
    """Encrypt the program's output on a thread; ``run.reader`` becomes the ciphertext."""
    from . import encryption

    plaintext = run.reader
    read_fd, write_fd = os.pipe()
    run.reader = os.fdopen(read_fd, "rb")
    writer = os.fdopen(write_fd, "wb")

    def encrypt() -> None:
        try:
            if passphrase is not None:
                encryption.encrypt(plaintext, writer, passphrase=passphrase)
            else:
                encryption.encrypt(plaintext, writer, recipients or ())
        except BaseException as exc:  # noqa: BLE001 - re-raised on the consumer's thread
            run.error = exc
        finally:
            with suppress(OSError):  # flushing to a reader that was closed
                writer.close()
            # Unread output would otherwise block the program, and wait() with it.
            plaintext.close()

    run.thread = threading.Thread(target=encrypt, daemon=True)
    run.thread.start()


class DumpStream:
    """A dump as an iterator of byte chunks.

    If the program fails or is killed, iteration raises :class:`TransferError`
    at the end instead of stopping. :meth:`close` (or leaving a ``with`` block)
    before the end stops the program, as does dropping the stream unfinished.
    ``result`` is set once iteration finishes.
    """

    def __init__(
        self,
        process: subprocess.Popen[bytes],
        *,
        tool: ClientTool,
        server: ServerInfo,
        verdict: Verdict,
        recipients: Sequence[str] | None,
        password: str,
        on_finish: Any = None,
        passphrase: str | None = None,
    ) -> None:
        self._run = _DumpRun(process, verdict, on_finish)
        self._tool = tool
        self._server = server
        self._verdict = verdict
        self._password = password
        self._started = time.monotonic()
        self._done = False
        self.result: TransferResult | None = None
        self._finalizer = weakref.finalize(self, _stop, self._run)
        if recipients is not None or passphrase is not None:
            _start_encryption(self._run, recipients=recipients, passphrase=passphrase)

    @property
    def pid(self) -> int:
        """The program's process id, for diagnostics."""
        return self._run.process.pid

    def __iter__(self) -> DumpStream:
        return self

    def __next__(self) -> bytes:
        if self._done:
            raise StopIteration
        run = self._run
        chunk = run.reader.read(CHUNK)
        if chunk:
            run.bytes += len(chunk)
            return chunk
        self._finish()
        raise StopIteration

    def _finish(self) -> None:
        self._done = True
        run = self._run
        if run.thread is not None:
            run.thread.join()
        code = run.process.wait()
        stderr = run.stderr.text(self._password)
        run.reader.close()
        self._finalizer.detach()
        if code != 0 or run.error is not None:
            if run.error is not None:
                msg = f"dump failed: encryption: {run.error}"
            else:
                first = stderr.strip().splitlines()[0] if stderr.strip() else "no error output"
                msg = f"dump failed: {self._tool.name} exited {code}: {first}"
            error = TransferError(msg, self._verdict, code, stderr)
            run.notify(error)
            raise error from run.error
        self.result = TransferResult(
            run.bytes,
            round((time.monotonic() - self._started) * 1000, 1),
            self._tool.label,
            self._server,
            self._verdict,
        )
        run.notify(None)

    def close(self) -> None:
        """Stop the program if it is still running."""
        self._done = True
        self._finalizer()

    def __enter__(self) -> DumpStream:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


@dataclass(frozen=True, slots=True)
class _Plan:
    verdict: Verdict
    credentials: ResolvedCredentials | None
    tool: ClientTool | None
    server: ServerInfo | None


def _platform_and_option_findings(options: Sequence[str], allowed: frozenset[str]) -> list[Finding]:
    findings: list[Finding] = []
    if not DEV_FD.is_dir():
        findings.append(
            Finding(Code.PLATFORM_UNSUPPORTED, "export and import need /dev/fd (Linux or macOS)")
        )
    findings += [
        Finding(
            Code.OPTION_NOT_ALLOWED,
            f"{option.split('=', 1)[0]} is not an allowed option",
            {"option": option.split("=", 1)[0]},
        )
        for option in _client.disallowed_options(options, allowed)
    ]
    return findings


def _tool_findings(purpose: str, server: ServerInfo) -> tuple[ClientTool | None, list[Finding]]:
    tool = _client.find_tool(purpose, server.family)
    if tool is None:
        names = ", ".join(_client.candidates(purpose, server.family))
        return None, [
            Finding(Code.CLIENT_TOOL_MISSING, f"none of {names} is on PATH", {"tools": names})
        ]
    if tool.family is not server.family or tool.version[:2] < server.version[:2]:
        return tool, [
            Finding(
                Code.CLIENT_SERVER_SKEW,
                f"{tool.label} is older than, or a different family from, "
                f"{server.family} {server.version_text}",
                {"tool": tool.label, "server": server.version_text},
            )
        ]
    return tool, []


def _dump_plan(
    connection: Connection, credentials: CredentialSource, options: Sequence[str]
) -> _Plan:
    findings = _platform_and_option_findings(options, _client.DUMP_OPTIONS)
    resolved = _resolve_or_finding(credentials)
    if isinstance(resolved, Finding):
        return _Plan(Verdict("dump", (*findings, resolved)), None, None, None)
    verdict, session = _preflight_resolved(connection, resolved, "dump", DUMP_PRIVILEGES)
    verdict = verdict.with_findings(*findings)
    if session is None:
        return _Plan(verdict, resolved, None, None)
    database = connection.database
    try:
        with session, session.cursor() as cur:
            server = detect_server(cur)
            cur.execute(
                "SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s",
                (database,),
            )
            exists = int(cur.fetchone()[0]) > 0
            stored = 0
            if exists:
                cur.execute(
                    "SELECT (SELECT COUNT(*) FROM information_schema.VIEWS"
                    " WHERE TABLE_SCHEMA = %s)"
                    " + (SELECT COUNT(*) FROM information_schema.TRIGGERS"
                    " WHERE TRIGGER_SCHEMA = %s)",
                    (database, database),
                )
                stored = int(cur.fetchone()[0])
    except pymysql.err.MySQLError as exc:
        raise _as_package_error(exc, DatabaseUnreachableError) from exc
    if not exists:
        verdict = verdict.with_findings(
            Finding(Code.DATABASE_ABSENT, f"{database!r} does not exist")
        )
    elif stored:
        verdict = verdict.with_findings(
            Finding(
                Code.STORED_OBJECTS_PRESENT,
                f"{database!r} has {stored} view(s) or trigger(s); loading them elsewhere needs "
                "privilege for their DEFINER, and MariaDB keeps their original text",
                {"count": stored},
            )
        )
    tool, tool_findings = _tool_findings(_client.PURPOSE_DUMP, server)
    return _Plan(verdict.with_findings(*tool_findings), resolved, tool, server)


def check_dump(
    connection: Connection, credentials: CredentialSource, *, options: Sequence[str] = ()
) -> Verdict:
    """What :func:`dump` would find, without running the dump."""
    with operation("check_dump", connection) as fields:
        verdict = _dump_plan(connection, credentials, options).verdict
        fields[VERDICT_KEY] = verdict
        return verdict


def iter_dump(
    connection: Connection,
    credentials: CredentialSource,
    *,
    recipients: Sequence[str] | None = None,
    passphrase: str | None = None,
    options: Sequence[str] = (),
) -> DumpStream:
    """The dump as a :class:`DumpStream` of byte chunks (age-encrypted if requested)."""
    # The operation outlives this call: a failure here ends it at once, and
    # success hands it to the stream, which ends it when the dump does.
    running = Running("dump", connection)

    def finish(error: BaseException | None, count: int) -> None:
        running.fields["bytes"] = count
        running.end(error)

    try:
        with running.current() as fields:
            return _start_dump(
                connection, credentials, recipients, passphrase, options, fields, finish
            )
    except BaseException as exc:
        running.end(exc)
        raise


def _start_dump(
    connection: Connection,
    credentials: CredentialSource,
    recipients: Sequence[str] | None,
    passphrase: str | None,
    options: Sequence[str],
    fields: dict[str, object],
    finish: Any,
) -> DumpStream:
    if recipients is not None and passphrase is not None:
        msg = "supply recipients= or passphrase=, not both"
        raise InvalidArgumentsError(msg)
    if recipients is not None or passphrase is not None:
        from . import encryption

        if passphrase is not None:
            encryption.check_passphrase(passphrase)
        else:
            encryption.check_recipients(recipients or ())
    plan = _dump_plan(connection, credentials, options)
    fields[VERDICT_KEY] = plan.verdict
    if not plan.verdict.ok or plan.tool is None or plan.server is None or plan.credentials is None:
        raise RefusedError(plan.verdict)
    try:
        process = _start(
            plan.tool,
            _client.dump_args(plan.tool, connection.database, options),
            plan.credentials,
            connection,
            for_load=False,
        )
    except OSError as exc:
        msg = f"could not start {plan.tool.path}: {exc.strerror or exc}"
        raise TransferError(msg, plan.verdict, None, "") from exc
    try:
        return DumpStream(
            process,
            tool=plan.tool,
            server=plan.server,
            verdict=plan.verdict,
            recipients=recipients,
            password=plan.credentials.password,
            on_finish=finish,
            passphrase=passphrase,
        )
    except BaseException:
        _abandon(process)
        raise


@dataclass(frozen=True, slots=True)
class _Partial:
    """A private temporary file beside ``target``, renamed onto it on success."""

    target: Path
    path: Path
    file: IO[bytes]

    def discard(self) -> None:
        self.file.close()
        self.path.unlink(missing_ok=True)


def _open_partial(target: Path) -> _Partial:
    path = target.with_name(f".{target.name}.{uuid.uuid4().hex}.partial")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as exc:
        msg = f"cannot write the dump to {str(target)!r}: {exc.strerror}"
        raise InvalidArgumentsError(msg) from exc
    return _Partial(target, path, os.fdopen(fd, "wb"))


def _write_failed(stream: DumpStream, where: str, exc: OSError) -> TransferError:
    msg = f"writing the dump to {where} failed: {exc.strerror or exc}"
    return TransferError(msg, stream._verdict, None, "")


def _write_atomically(stream: DumpStream, partial: _Partial) -> None:
    """Write a stream into ``partial`` and rename it onto its target on success."""
    try:
        with partial.file as out:
            for chunk in stream:
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        partial.path.replace(partial.target)
    except BaseException as exc:
        stream.close()
        partial.discard()
        if isinstance(exc, OSError):
            raise _write_failed(stream, repr(str(partial.target)), exc) from exc
        raise


def dump(
    connection: Connection,
    credentials: CredentialSource,
    to: IO[bytes] | str | os.PathLike[str],
    *,
    recipients: Sequence[str] | None = None,
    passphrase: str | None = None,
    options: Sequence[str] = (),
) -> TransferResult:
    """Dump to a writable binary stream, or atomically to a path (mode 0600)."""
    if isinstance(to, io.TextIOBase):
        msg = "dump writes bytes: pass a binary stream (sys.stdout.buffer, a file opened 'wb')"
        raise InvalidArgumentsError(msg)
    if isinstance(to, (str, os.PathLike)):
        partial = _open_partial(Path(to))
        try:
            stream = iter_dump(
                connection,
                credentials,
                recipients=recipients,
                passphrase=passphrase,
                options=options,
            )
        except BaseException:
            partial.discard()
            raise
        _write_atomically(stream, partial)
    else:
        stream = iter_dump(
            connection,
            credentials,
            recipients=recipients,
            passphrase=passphrase,
            options=options,
        )
        with stream:
            try:
                for chunk in stream:
                    to.write(chunk)
                # Unflushed, the last chunk could still be lost after success is reported.
                to.flush()
            except OSError as exc:
                stream.close()
                raise _write_failed(stream, "the output stream", exc) from exc
    if stream.result is None:  # pragma: no cover - iteration always sets it or raises
        msg = "dump finished without a result"
        raise TransferError(msg, Verdict("dump"), None, "")
    return stream.result


SANDBOX_LINE = b"/*M!999999\\- enable the sandbox mode */"


@dataclass(frozen=True, slots=True)
class _Header:
    """What the first lines of a source say, compared against fixed strings only."""

    encrypted: bool
    family: ServerFamily | None
    sandboxed: bool
    #: Encrypted, and no decryption secret was supplied, so the plaintext is unknown.
    needs_identity: bool = False


#: Written by both families' tools a few lines below their banner, naming the source server.
SERVER_VERSION_LINE = b"-- Server version\t"


def _family_of(line: bytes) -> ServerFamily:
    return ServerFamily.MARIADB if b"MariaDB" in line else ServerFamily.MYSQL


def _header(plain_head: bytes | None, *, encrypted: bool) -> _Header:
    if not plain_head:
        return _Header(encrypted, None, False)
    lines = plain_head.split(b"\n", 8)[:8]
    sandboxed = lines[0].startswith(SANDBOX_LINE)
    banner: ServerFamily | None = None
    server: ServerFamily | None = None
    for line in lines:
        if banner is None and line.startswith((b"-- MariaDB dump", b"-- MySQL dump")):
            banner = _family_of(line)
        elif banner is not None and line.startswith(SERVER_VERSION_LINE):
            # Either family's tool can dump the other's server; the server decides.
            server = _family_of(line)
            break
    return _Header(encrypted, server or banner, sandboxed)


def _not_bytes(block: object) -> InvalidArgumentsError:
    kind = type(block).__name__
    return InvalidArgumentsError(f"the dump source must yield bytes, not {kind}")


class _IterReader(io.RawIOBase):
    def __init__(self, chunks: Iterable[bytes]) -> None:
        self._chunks: Iterator[bytes] = iter(chunks)
        # A view, so taking a piece of a large chunk never copies the rest of it.
        self._pending = memoryview(b"")

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        while not self._pending:
            try:
                chunk = next(self._chunks)
            except StopIteration:
                return 0
            try:
                self._pending = memoryview(chunk)
            except TypeError as exc:
                raise _not_bytes(chunk) from exc
        size = min(len(buffer), len(self._pending))
        buffer[:size] = self._pending[:size]
        self._pending = self._pending[size:]
        return size


def _as_reader(chunks: Iterable[bytes]) -> IO[bytes]:
    return io.BufferedReader(_IterReader(chunks))


def _prefixed(head: bytes, rest: IO[bytes]) -> IO[bytes]:
    def chunks() -> Iterator[bytes]:
        yield head
        yield from iter(lambda: rest.read(CHUNK), b"")

    return _as_reader(chunks())


class _Decrypting:
    """Decrypts ``source`` into a pipe on a thread; ``reader`` is the plaintext end."""

    def __init__(
        self,
        source: IO[bytes],
        *,
        identities: Sequence[str] | None = None,
        passphrase: str | None = None,
    ) -> None:
        from . import encryption

        read_fd, write_fd = os.pipe()
        self.reader: IO[bytes] = os.fdopen(read_fd, "rb")
        self.error: BaseException | None = None
        writer = os.fdopen(write_fd, "wb")

        def run() -> None:
            try:
                if passphrase is not None:
                    encryption.decrypt(source, writer, passphrase=passphrase)
                else:
                    encryption.decrypt(source, writer, identities or ())
            except BrokenPipeError:
                pass  # the consumer stopped reading
            except BaseException as exc:  # noqa: BLE001 - re-raised on the consumer's thread
                self.error = exc
            finally:
                with suppress(BrokenPipeError):  # flushing to a consumer that stopped reading
                    writer.close()

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def join(self) -> None:
        self._thread.join()

    def close(self) -> None:
        """Stop reading; a thread blocked writing plaintext then fails with EPIPE and exits."""
        self.reader.close()
        self._thread.join(timeout=10)


def _abandon(process: subprocess.Popen[bytes]) -> None:
    """Kill and reap a load program: closing its input instead would run a partial statement."""
    process.kill()
    process.wait()
    if process.stdin is not None:
        with suppress(OSError):
            process.stdin.close()


def _io_failed(exc: OSError, verdict: Verdict) -> TransferError:
    return TransferError(f"load failed: {exc.strerror or exc}", verdict, None, "")


def _feed(stdin: IO[bytes], head: bytes, reader: IO[bytes], decrypt: _Decrypting | None) -> int:
    """Write ``head`` then ``reader`` to ``stdin`` and close it; return the bytes written."""
    delivered = 0
    for block in itertools.chain((head,), iter(lambda: reader.read(CHUNK), b"")):
        if not block:
            continue
        try:
            stdin.write(block)
        except BrokenPipeError:
            break  # the program exited; its exit code says why
        delivered += len(block)
    if decrypt is not None:
        # After an early exit the decrypting thread is blocked writing plaintext
        # nobody reads; closing its reader is what lets it finish.
        decrypt.close()
        if decrypt.error is not None:
            raise decrypt.error
    with suppress(BrokenPipeError):
        stdin.close()
    return delivered


def _pump_load(
    process: subprocess.Popen[bytes],
    head: bytes,
    reader: IO[bytes],
    *,
    decrypt: _Decrypting | None = None,
    password: str,
    verdict: Verdict | None = None,
) -> int:
    """Feed ``head`` then ``reader`` to the program's stdin; return the bytes delivered."""
    if process.stdin is None or process.stderr is None:
        msg = "a load process needs piped stdin and stderr"
        raise ValueError(msg)
    if verdict is None:
        verdict = Verdict("load")
    stderr = _Stderr(process.stderr)
    # Every failure to feed and close stdin cleanly kills the program: otherwise its
    # input would be closed later, on collection or exit, running a partial statement.
    try:
        delivered = _feed(process.stdin, head, reader, decrypt)
    except BaseException as exc:
        _abandon(process)
        if decrypt is not None:
            decrypt.close()
        if isinstance(exc, OSError):  # reading the source, or writing to the program
            raise _io_failed(exc, verdict) from exc
        raise
    code = process.wait()
    text = stderr.text(password)
    if code != 0:
        first = text.strip().splitlines()[0] if text.strip() else "no error output"
        msg = f"load failed: exited {code}: {first}"
        raise TransferError(msg, verdict, code, text)
    return delivered


def _open_source(
    source: IO[bytes] | Iterable[bytes] | str | os.PathLike[str], cleanup: ExitStack
) -> IO[bytes]:
    if isinstance(source, (str, os.PathLike)):
        try:
            file = open(source, "rb")  # noqa: PTH123, SIM115 - closed by cleanup
        except OSError as exc:
            msg = f"cannot read the dump source {os.fspath(source)!r}: {exc.strerror or exc}"
            raise InvalidArgumentsError(msg) from exc
        return cleanup.enter_context(file)
    if isinstance(source, io.TextIOBase):
        msg = "load reads bytes: pass a binary stream (sys.stdin.buffer, a file opened 'rb')"
        raise InvalidArgumentsError(msg)
    if hasattr(source, "read"):
        return source  # type: ignore[return-value]
    return _as_reader(source)


def _read_head(reader: IO[bytes]) -> bytes:
    """Up to CHUNK bytes; an unbuffered stream may return less per read."""
    head = b""
    while len(head) < CHUNK:
        block = reader.read(CHUNK - len(head))
        if not block:
            break
        if not isinstance(block, (bytes, bytearray, memoryview)):
            raise _not_bytes(block)
        head += block
    return head


def _prepare(
    reader: IO[bytes],
    identities: Sequence[str] | None,
    cleanup: ExitStack,
    *,
    passphrase: str | None = None,
) -> tuple[_Header, bytes, IO[bytes], _Decrypting | None]:
    """Peek the source: (header, plaintext head, plaintext reader, decryptor)."""
    from . import encryption

    if identities is not None and passphrase is not None:
        msg = "supply identities= or passphrase=, not both"
        raise InvalidArgumentsError(msg)
    try:
        head = _read_head(reader)
    except OSError as exc:
        msg = f"cannot read the dump source: {exc.strerror or exc}"
        raise InvalidArgumentsError(msg) from exc
    if not head.startswith(encryption.AGE_HEADER):
        return _header(head, encrypted=False), head, reader, None
    if identities is None and passphrase is None:
        return _Header(True, None, False, needs_identity=True), b"", reader, None
    decrypting = _Decrypting(_prefixed(head, reader), identities=identities, passphrase=passphrase)
    cleanup.callback(decrypting.close)
    plain_head = decrypting.reader.read(CHUNK)
    if not plain_head:
        decrypting.join()
        error = decrypting.error
        if isinstance(error, OSError):
            msg = f"cannot read the dump source: {error.strerror or error}"
            raise InvalidArgumentsError(msg) from error
        if error is not None:
            raise error  # wrong identity/passphrase or damage, before anything is loaded
    return _header(plain_head, encrypted=True), plain_head, decrypting.reader, decrypting


def _load_plan(
    connection: Connection,
    credentials: CredentialSource,
    options: Sequence[str],
    *,
    replace: str | None,
    header: _Header | None,
    allow_unsandboxed: bool,
) -> _Plan:
    findings = _platform_and_option_findings(options, _client.LOAD_OPTIONS)
    if header is not None and header.needs_identity:
        findings.append(
            Finding(
                Code.IDENTITY_REQUIRED,
                "the source is age-encrypted; supply identities= or passphrase=",
            )
        )
    resolved = _resolve_or_finding(credentials)
    if isinstance(resolved, Finding):
        return _Plan(Verdict("load", (*findings, resolved)), None, None, None)
    verdict, session = _preflight_resolved(connection, resolved, "load", LOAD_PRIVILEGES)
    verdict = verdict.with_findings(*findings)
    if session is None:
        return _Plan(verdict, resolved, None, None)
    database = connection.database
    try:
        with session, session.cursor() as cur:
            server = detect_server(cur)
            cur.execute(
                "SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s",
                (database,),
            )
            exists = int(cur.fetchone()[0]) > 0
            tables = 0
            if exists:
                cur.execute(
                    "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s",
                    (database,),
                )
                tables = int(cur.fetchone()[0])
    except pymysql.err.MySQLError as exc:
        raise _as_package_error(exc, DatabaseUnreachableError) from exc
    extra: list[Finding] = []
    if not exists:
        extra.append(Finding(Code.DATABASE_ABSENT, f"{database!r} does not exist"))
    elif replace is not None:
        extra += _confirmation(database, replace)
    elif tables:
        extra.append(
            Finding(
                Code.DATABASE_NOT_EMPTY,
                f"{database!r} holds {tables} table(s); "
                f"pass replace={database!r} to load over them",
                {"tables": tables},
            )
        )
    tool, tool_findings = _tool_findings(_client.PURPOSE_LOAD, server)
    extra += tool_findings
    if header is not None and tool is not None:
        if header.family is not None and header.family is not server.family:
            extra.append(
                Finding(
                    Code.CROSS_FAMILY_DUMP,
                    f"the dump comes from {header.family}; its collations may not exist on "
                    f"{server.family} {server.version_text}",
                )
            )
        if header.sandboxed and not tool.understands_sandbox_line and not allow_unsandboxed:
            extra.append(
                Finding(
                    Code.INCOMPATIBLE_DUMP_SOURCE,
                    f"the dump begins with MariaDB's sandbox line, which {tool.label} cannot "
                    "read; pass allow_unsandboxed=True to strip that one line",
                )
            )
    return _Plan(verdict.with_findings(*extra), resolved, tool, server)


def check_load(
    connection: Connection,
    credentials: CredentialSource,
    *,
    source: str | os.PathLike[str] | None = None,
    replace: str | None = None,
    identities: Sequence[str] | None = None,
    passphrase: str | None = None,
    options: Sequence[str] = (),
    allow_unsandboxed: bool = False,
) -> Verdict:
    """What :func:`load` would find. The source header is read only for a path."""
    with operation("check_load", connection) as fields, ExitStack() as cleanup:
        if source is not None and not isinstance(source, (str, os.PathLike)):
            # Reading a stream's head here would leave load() a dump without its head.
            msg = "check_load takes source only as a path; a stream cannot be read twice"
            raise InvalidArgumentsError(msg)
        header = None
        if source is not None:
            header, *_ = _prepare(
                _open_source(source, cleanup), identities, cleanup, passphrase=passphrase
            )
        verdict = _load_plan(
            connection,
            credentials,
            options,
            replace=replace,
            header=header,
            allow_unsandboxed=allow_unsandboxed,
        ).verdict
        fields[VERDICT_KEY] = verdict
        return verdict


def load(
    connection: Connection,
    credentials: CredentialSource,
    source: IO[bytes] | Iterable[bytes] | str | os.PathLike[str],
    *,
    replace: str | None = None,
    identities: Sequence[str] | None = None,
    passphrase: str | None = None,
    options: Sequence[str] = (),
    allow_unsandboxed: bool = False,
) -> TransferResult:
    """Load a dump into this database.

    Damage in a source is found mid-stream, after earlier statements ran, so load
    into a staging database and switch to it only after the load is checked.
    """
    started = time.monotonic()
    with operation("load", connection) as fields, ExitStack() as cleanup:
        header, head, reader, decrypting = _prepare(
            _open_source(source, cleanup), identities, cleanup, passphrase=passphrase
        )
        plan = _load_plan(
            connection,
            credentials,
            options,
            replace=replace,
            header=header,
            allow_unsandboxed=allow_unsandboxed,
        )
        fields[VERDICT_KEY] = plan.verdict
        if (
            not plan.verdict.ok
            or plan.tool is None
            or plan.server is None
            or plan.credentials is None
        ):
            raise RefusedError(plan.verdict)
        if header.sandboxed and not plan.tool.understands_sandbox_line:
            head = head.split(b"\n", 1)[1] if b"\n" in head else b""
        try:
            process = _start(
                plan.tool,
                _client.load_args(connection.database, options),
                plan.credentials,
                connection,
                for_load=True,
            )
        except OSError as exc:
            msg = f"could not start {plan.tool.path}: {exc.strerror or exc}"
            raise TransferError(msg, plan.verdict, None, "") from exc
        delivered = _pump_load(
            process,
            head,
            reader,
            decrypt=decrypting,
            password=plan.credentials.password,
            verdict=plan.verdict,
        )
        fields["bytes"] = delivered
        return TransferResult(
            delivered,
            round((time.monotonic() - started) * 1000, 1),
            plan.tool.label,
            plan.server,
            plan.verdict,
        )
