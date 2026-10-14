"""Export and import, through the server's own client programs (spec §7.3).

One engine per direction. :class:`DumpStream` is the dump engine: an iterator of
chunks that raises :class:`TransferError` at the end, instead of stopping, when
the program failed, so a truncated dump is never mistaken for a whole one.
``dump`` writes it to a stream or, atomically, to a path. ``load`` (below) peeks
the source's first bytes to detect age encryption, the dump's family and
MariaDB's sandbox line; it never parses SQL (global rule 1).
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
import uuid
from collections.abc import Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

import pymysql

from . import _client
from ._client import ClientTool
from ._observe import VERDICT_KEY, operation
from .connection import Connection
from .credentials import CredentialSource, ResolvedCredentials
from .errors import DatabaseUnreachableError, InvalidArgumentsError, RefusedError, TransferError
from .provision import _as_package_error, _preflight_resolved, _resolve_or_finding
from .server import ServerInfo, detect_server
from .verdict import Code, Finding, Verdict

CHUNK = 64 * 1024
STDERR_CAP = 64 * 1024

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


class DumpStream:
    """A dump as an iterator of byte chunks.

    If the program fails or is killed, iteration raises :class:`TransferError`
    at the end instead of stopping. :meth:`close` (or leaving a ``with`` block)
    before the end stops the program. ``result`` is set once iteration finishes.
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
    ) -> None:
        self._process = process
        self._tool = tool
        self._server = server
        self._verdict = verdict
        self._password = password
        self._on_finish = on_finish
        self._started = time.monotonic()
        self._bytes = 0
        self._done = False
        self._error: BaseException | None = None
        self.result: TransferResult | None = None
        if process.stdout is None or process.stderr is None:
            msg = "a dump process needs piped stdout and stderr"
            raise ValueError(msg)
        self._stderr = _Stderr(process.stderr)
        self._reader: IO[bytes] = process.stdout
        self._encrypt_thread: threading.Thread | None = None
        if recipients:
            self._start_encryption(process.stdout, recipients)

    @property
    def pid(self) -> int:
        """The program's process id, for diagnostics."""
        return self._process.pid

    def _start_encryption(self, plaintext: IO[bytes], recipients: Sequence[str]) -> None:
        from . import encryption

        read_fd, write_fd = os.pipe()
        self._reader = os.fdopen(read_fd, "rb")
        writer = os.fdopen(write_fd, "wb")

        def run() -> None:
            try:
                encryption.encrypt(plaintext, writer, recipients)
            except BaseException as exc:  # noqa: BLE001 - re-raised on the consumer's thread
                self._error = exc
            finally:
                writer.close()
                # Unread output would otherwise block the program, and wait() with it.
                plaintext.close()

        self._encrypt_thread = threading.Thread(target=run, daemon=True)
        self._encrypt_thread.start()

    def __iter__(self) -> DumpStream:
        return self

    def __next__(self) -> bytes:
        if self._done:
            raise StopIteration
        chunk = self._reader.read(CHUNK)
        if chunk:
            self._bytes += len(chunk)
            return chunk
        self._finish()
        raise StopIteration

    def _finish(self) -> None:
        self._done = True
        if self._encrypt_thread is not None:
            self._encrypt_thread.join()
        code = self._process.wait()
        stderr = self._stderr.text(self._password)
        self._reader.close()
        if code != 0 or self._error is not None:
            if self._error is not None:
                msg = f"dump failed: encryption: {self._error}"
            else:
                first = stderr.strip().splitlines()[0] if stderr.strip() else "no error output"
                msg = f"dump failed: {self._tool.name} exited {code}: {first}"
            error = TransferError(msg, self._verdict, code, stderr)
            self._notify(error)
            raise error from self._error
        self.result = TransferResult(
            self._bytes,
            round((time.monotonic() - self._started) * 1000, 1),
            self._tool.label,
            self._server,
            self._verdict,
        )
        self._notify(None)

    def _notify(self, error: BaseException | None) -> None:
        if self._on_finish is not None:
            callback, self._on_finish = self._on_finish, None
            callback(error, self._bytes)

    def close(self) -> None:
        """Stop the program if it is still running."""
        if self._done:
            return
        self._done = True
        self._process.kill()
        self._process.wait()
        self._reader.close()
        if self._encrypt_thread is not None:
            self._encrypt_thread.join(timeout=10)
        self._notify(TransferError("dump closed before it finished", self._verdict, None, ""))

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
    if not Path("/dev/fd").is_dir():
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
    options: Sequence[str] = (),
) -> DumpStream:
    """The dump as a :class:`DumpStream` of byte chunks (age-encrypted if ``recipients``)."""
    # The operation's span outlives this call: a failure here ends it on leaving
    # the block, and success hands it to the stream, which ends it when the dump does.
    with ExitStack() as stack:
        fields = stack.enter_context(operation("dump", connection))
        plan = _dump_plan(connection, credentials, options)
        fields[VERDICT_KEY] = plan.verdict
        if (
            not plan.verdict.ok
            or plan.tool is None
            or plan.server is None
            or plan.credentials is None
        ):
            raise RefusedError(plan.verdict)
        if recipients is not None:
            from . import encryption

            encryption.check_recipients(recipients)
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

        def finish(error: BaseException | None, count: int) -> None:
            fields["bytes"] = count
            if error is None:
                span.close()
            else:
                span.__exit__(type(error), error, error.__traceback__)

        stream = DumpStream(
            process,
            tool=plan.tool,
            server=plan.server,
            verdict=plan.verdict,
            recipients=recipients,
            password=plan.credentials.password,
            on_finish=finish,
        )
        span = stack.pop_all()
    return stream


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
    options: Sequence[str] = (),
) -> TransferResult:
    """Dump to a writable binary stream, or atomically to a path (mode 0600)."""
    if isinstance(to, (str, os.PathLike)):
        partial = _open_partial(Path(to))
        try:
            stream = iter_dump(connection, credentials, recipients=recipients, options=options)
        except BaseException:
            partial.discard()
            raise
        _write_atomically(stream, partial)
    else:
        stream = iter_dump(connection, credentials, recipients=recipients, options=options)
        with stream:
            try:
                for chunk in stream:
                    to.write(chunk)
            except OSError as exc:
                stream.close()
                raise _write_failed(stream, "the output stream", exc) from exc
    if stream.result is None:  # pragma: no cover - iteration always sets it or raises
        msg = "dump finished without a result"
        raise TransferError(msg, Verdict("dump"), None, "")
    return stream.result
