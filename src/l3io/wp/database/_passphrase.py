"""Passphrase age streaming: binder preferred, age+batchpass CLI fallback.

Selection via ``L3IO_AGE_PASSPHRASE_BACKEND``:

- ``auto`` (default): binder if importable, else CLI if ``age`` and
  ``age-plugin-batchpass`` are on ``PATH``
- ``binder`` / ``cli``: that backend only

Passphrases never appear on argv. The CLI path uses ``AGE_PASSPHRASE_FD``.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import threading
from typing import IO, Any, Literal

from .errors import CorruptDumpError, DecryptionError, InvalidArgumentsError, MissingDependencyError

BackendName = Literal["binder", "cli"]
_ENV = "L3IO_AGE_PASSPHRASE_BACKEND"


def _requested() -> str:
    return os.environ.get(_ENV, "auto").strip().lower() or "auto"


def binder_available() -> bool:
    try:
        import l3io_age_passphrase  # noqa: F401
    except ImportError:
        return False
    return True


def cli_available() -> bool:
    return shutil.which("age") is not None and shutil.which("age-plugin-batchpass") is not None


def resolve_backend() -> BackendName:
    choice = _requested()
    if choice not in {"auto", "binder", "cli"}:
        msg = f"{_ENV} must be auto, binder, or cli (got {choice!r})"
        raise InvalidArgumentsError(msg)
    if choice == "binder":
        if not binder_available():
            raise MissingDependencyError(extra="encryption", distribution="l3io-age-passphrase")
        return "binder"
    if choice == "cli":
        if not cli_available():
            msg = (
                "passphrase CLI backend needs age >=1.3 and age-plugin-batchpass on PATH "
                f"(set {_ENV}=binder to use the in-process binder instead)"
            )
            raise InvalidArgumentsError(msg)
        return "cli"
    if binder_available():
        return "binder"
    if cli_available():
        return "cli"
    raise MissingDependencyError(extra="encryption", distribution="l3io-age-passphrase")


def check_ready(passphrase: str) -> None:
    if passphrase == "":
        msg = "passphrase must not be empty"
        raise InvalidArgumentsError(msg)
    resolve_backend()


def encrypt_io(reader: IO[bytes], writer: IO[bytes], passphrase: str) -> None:
    backend = resolve_backend()
    if backend == "binder":
        _binder_encrypt(reader, writer, passphrase)
    else:
        _cli_crypt(reader, writer, passphrase, encrypt=True)


def decrypt_io(reader: IO[bytes], writer: IO[bytes], passphrase: str) -> None:
    backend = resolve_backend()
    if backend == "binder":
        _binder_decrypt(reader, writer, passphrase)
    else:
        _cli_crypt(reader, writer, passphrase, encrypt=False)


def _binder() -> Any:
    try:
        import l3io_age_passphrase
    except ImportError as exc:
        raise MissingDependencyError(
            extra="encryption",
            distribution="l3io-age-passphrase",
        ) from exc
    return l3io_age_passphrase


def _binder_encrypt(reader: IO[bytes], writer: IO[bytes], passphrase: str) -> None:
    mod = _binder()
    try:
        mod.encrypt_io(reader, writer, passphrase)
    except mod.EncryptError as exc:
        if str(exc).startswith("BrokenPipeError"):
            raise BrokenPipeError(str(exc)) from exc
        raise OSError(str(exc)) from exc


def _binder_decrypt(reader: IO[bytes], writer: IO[bytes], passphrase: str) -> None:
    mod = _binder()
    try:
        mod.decrypt_io(reader, writer, passphrase)
    except BrokenPipeError:
        raise
    except mod.DecryptError as exc:
        text = str(exc)
        if text == "Decryption failed":
            msg = "the passphrase cannot decrypt this dump"
            raise DecryptionError(msg) from exc
        msg = "the encrypted dump is damaged or not an age file"
        raise CorruptDumpError(msg) from exc
    except OSError as exc:
        if type(exc) is not OSError or exc.errno is not None:
            raise
        msg = "the encrypted dump is truncated or damaged"
        raise CorruptDumpError(msg) from exc


def _open_passphrase_fd(passphrase: str) -> int:
    """Write the passphrase to a pipe; return the inheritable read FD."""
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, passphrase.encode("utf-8") + b"\n")
    finally:
        os.close(write_fd)
    os.set_inheritable(read_fd, True)
    return read_fd


def _cli_crypt(
    reader: IO[bytes],
    writer: IO[bytes],
    passphrase: str,
    *,
    encrypt: bool,
) -> None:
    age_bin = shutil.which("age")
    if age_bin is None or shutil.which("age-plugin-batchpass") is None:
        msg = "age and age-plugin-batchpass must be on PATH for the CLI passphrase backend"
        raise InvalidArgumentsError(msg)

    pass_fd = _open_passphrase_fd(passphrase)
    drop = {"AGE_PASSPHRASE", "AGE_PASSPHRASE_FILE"}
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env["AGE_PASSPHRASE_FD"] = str(pass_fd)
    args = [age_bin, "-e" if encrypt else "-d", "-j", "batchpass"]
    try:
        proc = subprocess.Popen(  # noqa: S603 - absolute age from PATH, fixed args
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=(pass_fd,),
            env=env,
            close_fds=True,
        )
    finally:
        os.close(pass_fd)

    stdin = proc.stdin
    stdout = proc.stdout
    stderr_pipe = proc.stderr
    if stdin is None or stdout is None or stderr_pipe is None:
        proc.kill()
        msg = "age subprocess pipes were not created"
        raise OSError(msg)

    write_error: list[BaseException] = []

    def _pump_in() -> None:
        try:
            shutil.copyfileobj(reader, stdin)
            stdin.close()
        except BaseException as exc:  # noqa: BLE001 - surface on join
            write_error.append(exc)
            with contextlib.suppress(OSError):
                stdin.close()

    inlet = threading.Thread(target=_pump_in, name="age-passphrase-stdin", daemon=True)
    inlet.start()
    try:
        shutil.copyfileobj(stdout, writer)
    finally:
        stdout.close()
        inlet.join(timeout=3600)
        stderr = stderr_pipe.read()
        stderr_pipe.close()
        code = proc.wait(timeout=60)

    if write_error:
        exc = write_error[0]
        if isinstance(exc, BrokenPipeError):
            raise BrokenPipeError(str(exc)) from exc
        if isinstance(exc, OSError):
            raise exc
        raise OSError(str(exc)) from exc

    if code == 0:
        return

    err = stderr.decode("utf-8", errors="replace")
    _map_cli_failure(encrypt=encrypt, err=err, code=code)


def _map_cli_failure(*, encrypt: bool, err: str, code: int) -> None:
    lower = err.lower()
    if not encrypt:
        if "no identity matched" in lower or "incorrect" in lower or "wrong" in lower:
            msg = "the passphrase cannot decrypt this dump"
            raise DecryptionError(msg)
        if "failed to read header" in lower or "not an age" in lower or "parsing" in lower:
            msg = "the encrypted dump is damaged or not an age file"
            raise CorruptDumpError(msg)
        # Truncated STREAM bodies often surface as read/MAC errors.
        if "unexpected eof" in lower or "mac" in lower or "truncated" in lower:
            msg = "the encrypted dump is truncated or damaged"
            raise CorruptDumpError(msg)
        msg = "the encrypted dump is damaged or not an age file"
        raise CorruptDumpError(msg)
    detail = err.strip() or "unknown error"
    msg = f"age passphrase encrypt failed (exit {code}): {detail}"
    raise OSError(msg)
