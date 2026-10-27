"""Passphrase backend selection: binder preferred, age+batchpass CLI fallback."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("l3io_age_passphrase")

from l3io.wp.database import _passphrase, encryption
from l3io.wp.database.errors import (
    CorruptDumpError,
    DecryptionError,
    InvalidArgumentsError,
    MissingDependencyError,
)

PLAIN = b"backend-probe\n" * 200
PASSPHRASE = "backend-secret"
TOOLS = Path(__file__).resolve().parents[1] / ".tools"


def test_auto_prefers_binder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("L3IO_AGE_PASSPHRASE_BACKEND", raising=False)
    monkeypatch.setattr(_passphrase, "binder_available", lambda: True)
    monkeypatch.setattr(_passphrase, "cli_available", lambda: True)
    assert _passphrase.resolve_backend() == "binder"


def test_auto_falls_back_to_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("L3IO_AGE_PASSPHRASE_BACKEND", "auto")
    monkeypatch.setattr(_passphrase, "binder_available", lambda: False)
    monkeypatch.setattr(_passphrase, "cli_available", lambda: True)
    assert _passphrase.resolve_backend() == "cli"


def test_forced_binder_without_module_names_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("L3IO_AGE_PASSPHRASE_BACKEND", "binder")
    monkeypatch.setattr(_passphrase, "binder_available", lambda: False)
    with pytest.raises(MissingDependencyError) as info:
        _passphrase.resolve_backend()
    assert info.value.distribution == "l3io-age-passphrase"
    assert info.value.extra == "encryption"


def test_forced_cli_without_binaries_is_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("L3IO_AGE_PASSPHRASE_BACKEND", "cli")
    monkeypatch.setattr(_passphrase, "cli_available", lambda: False)
    with pytest.raises(InvalidArgumentsError):
        _passphrase.resolve_backend()


def test_bad_backend_env_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("L3IO_AGE_PASSPHRASE_BACKEND", "gpg")
    with pytest.raises(InvalidArgumentsError):
        _passphrase.resolve_backend()


def test_binder_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("L3IO_AGE_PASSPHRASE_BACKEND", "binder")
    out = io.BytesIO()
    encryption.encrypt(io.BytesIO(PLAIN), out, passphrase=PASSPHRASE)
    assert out.getvalue().startswith(encryption.AGE_HEADER)
    plain = io.BytesIO()
    encryption.decrypt(io.BytesIO(out.getvalue()), plain, passphrase=PASSPHRASE)
    assert plain.getvalue() == PLAIN


@pytest.mark.skipif(
    not (TOOLS / "age").is_file() or not (TOOLS / "age-plugin-batchpass").is_file(),
    reason="age 1.3+ tools not in .tools/",
)
def test_cli_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("L3IO_AGE_PASSPHRASE_BACKEND", "cli")
    monkeypatch.setenv("PATH", f"{TOOLS}{os.pathsep}{os.environ.get('PATH', '')}")
    out = io.BytesIO()
    encryption.encrypt(io.BytesIO(PLAIN), out, passphrase=PASSPHRASE)
    data = out.getvalue()
    assert data.startswith(encryption.AGE_HEADER)
    plain = io.BytesIO()
    encryption.decrypt(io.BytesIO(data), plain, passphrase=PASSPHRASE)
    assert plain.getvalue() == PLAIN


@pytest.mark.skipif(
    not (TOOLS / "age").is_file() or not (TOOLS / "age-plugin-batchpass").is_file(),
    reason="age 1.3+ tools not in .tools/",
)
def test_binder_ciphertext_decrypts_via_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", f"{TOOLS}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("L3IO_AGE_PASSPHRASE_BACKEND", "binder")
    sealed = io.BytesIO()
    encryption.encrypt(io.BytesIO(PLAIN), sealed, passphrase=PASSPHRASE)
    monkeypatch.setenv("L3IO_AGE_PASSPHRASE_BACKEND", "cli")
    plain = io.BytesIO()
    encryption.decrypt(io.BytesIO(sealed.getvalue()), plain, passphrase=PASSPHRASE)
    assert plain.getvalue() == PLAIN


@pytest.mark.skipif(
    not (TOOLS / "age").is_file() or not (TOOLS / "age-plugin-batchpass").is_file(),
    reason="age 1.3+ tools not in .tools/",
)
def test_cli_does_not_put_passphrase_on_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("L3IO_AGE_PASSPHRASE_BACKEND", "cli")
    monkeypatch.setenv("PATH", f"{TOOLS}{os.pathsep}{os.environ.get('PATH', '')}")
    seen: list[list[str]] = []
    real_popen = subprocess.Popen

    def _wrap(*args: Any, **kwargs: Any) -> Any:
        cmd = args[0] if args else kwargs["args"]
        seen.append([str(c) for c in cmd])
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", _wrap)
    out = io.BytesIO()
    encryption.encrypt(io.BytesIO(PLAIN), out, passphrase=PASSPHRASE)
    assert seen
    flat = " ".join(seen[0])
    assert PASSPHRASE not in flat
    assert "-j" in seen[0] and "batchpass" in seen[0]


def test_wrong_passphrase_binder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("L3IO_AGE_PASSPHRASE_BACKEND", "binder")
    data = io.BytesIO()
    encryption.encrypt(io.BytesIO(PLAIN), data, passphrase=PASSPHRASE)
    with pytest.raises(DecryptionError) as info:
        encryption.decrypt(io.BytesIO(data.getvalue()), io.BytesIO(), passphrase="nope")
    assert PASSPHRASE not in str(info.value)
    assert "nope" not in str(info.value)


def test_binder_available_false_on_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def _block(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "l3io_age_passphrase" or name.startswith("l3io_age_passphrase."):
            msg = "blocked for test"
            raise ImportError(msg)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block)
    assert _passphrase.binder_available() is False


def test_cli_available_requires_both_binaries(monkeypatch: pytest.MonkeyPatch) -> None:
    def _age_only(name: str) -> str | None:
        return "/bin/age" if name == "age" else None

    monkeypatch.setattr(shutil, "which", _age_only)
    assert _passphrase.cli_available() is False
    monkeypatch.setattr(shutil, "which", lambda name: f"/bin/{name}")
    assert _passphrase.cli_available() is True


def test_forced_cli_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("L3IO_AGE_PASSPHRASE_BACKEND", "cli")
    monkeypatch.setattr(_passphrase, "cli_available", lambda: True)
    assert _passphrase.resolve_backend() == "cli"


def test_auto_with_neither_backend_names_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("L3IO_AGE_PASSPHRASE_BACKEND", raising=False)
    monkeypatch.setattr(_passphrase, "binder_available", lambda: False)
    monkeypatch.setattr(_passphrase, "cli_available", lambda: False)
    with pytest.raises(MissingDependencyError) as info:
        _passphrase.resolve_backend()
    assert info.value.distribution == "l3io-age-passphrase"


def test_binder_encrypt_maps_broken_pipe(monkeypatch: pytest.MonkeyPatch) -> None:
    import l3io_age_passphrase as binder

    class _Mod:
        EncryptError = binder.EncryptError

        @staticmethod
        def encrypt_io(*_a: Any, **_k: Any) -> None:
            msg = "BrokenPipeError: writer closed"
            raise binder.EncryptError(msg)

    monkeypatch.setenv("L3IO_AGE_PASSPHRASE_BACKEND", "binder")
    monkeypatch.setattr(_passphrase, "_binder", lambda: _Mod)
    with pytest.raises(BrokenPipeError):
        _passphrase.encrypt_io(io.BytesIO(b"x"), io.BytesIO(), PASSPHRASE)


def test_binder_encrypt_maps_other_encrypt_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import l3io_age_passphrase as binder

    class _Mod:
        EncryptError = binder.EncryptError

        @staticmethod
        def encrypt_io(*_a: Any, **_k: Any) -> None:
            msg = "scrypt failed"
            raise binder.EncryptError(msg)

    monkeypatch.setenv("L3IO_AGE_PASSPHRASE_BACKEND", "binder")
    monkeypatch.setattr(_passphrase, "_binder", lambda: _Mod)
    with pytest.raises(OSError, match="scrypt failed"):
        _passphrase.encrypt_io(io.BytesIO(b"x"), io.BytesIO(), PASSPHRASE)


def test_binder_decrypt_reraises_broken_pipe(monkeypatch: pytest.MonkeyPatch) -> None:
    import l3io_age_passphrase as binder

    class _Mod:
        DecryptError = binder.DecryptError

        @staticmethod
        def decrypt_io(*_a: Any, **_k: Any) -> None:
            msg = "closed"
            raise BrokenPipeError(msg)

    monkeypatch.setenv("L3IO_AGE_PASSPHRASE_BACKEND", "binder")
    monkeypatch.setattr(_passphrase, "_binder", lambda: _Mod)
    with pytest.raises(BrokenPipeError):
        _passphrase.decrypt_io(io.BytesIO(b"age-encryption.org/v1\n"), io.BytesIO(), PASSPHRASE)


def test_binder_decrypt_maps_oserror_without_errno(monkeypatch: pytest.MonkeyPatch) -> None:
    import l3io_age_passphrase as binder

    class _Mod:
        DecryptError = binder.DecryptError

        @staticmethod
        def decrypt_io(*_a: Any, **_k: Any) -> None:
            msg = "truncated stream"
            raise OSError(msg)

    monkeypatch.setenv("L3IO_AGE_PASSPHRASE_BACKEND", "binder")
    monkeypatch.setattr(_passphrase, "_binder", lambda: _Mod)
    with pytest.raises(CorruptDumpError, match="truncated"):
        _passphrase.decrypt_io(io.BytesIO(b"age-encryption.org/v1\n"), io.BytesIO(), PASSPHRASE)


def test_binder_import_error_inside_binder_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def _block(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "l3io_age_passphrase" or name.startswith("l3io_age_passphrase."):
            msg = "blocked"
            raise ImportError(msg)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block)
    with pytest.raises(MissingDependencyError) as info:
        _passphrase._binder()
    assert info.value.distribution == "l3io-age-passphrase"


class _FakeProc:
    def __init__(
        self,
        *,
        code: int = 0,
        stdout: bytes = b"",
        stderr: bytes = b"",
        write_raises: BaseException | None = None,
    ) -> None:
        self._code = code
        self.stdin: Any = io.BytesIO()
        if write_raises is not None:

            def _write(_data: bytes) -> int:
                raise write_raises

            self.stdin.write = _write  # type: ignore[assignment]
        self.stdout: Any = io.BytesIO(stdout)
        self.stderr: Any = io.BytesIO(stderr)

    def kill(self) -> None:
        return None

    def wait(self, timeout: float | None = None) -> int:
        return self._code


def test_cli_crypt_success_and_maps_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("L3IO_AGE_PASSPHRASE_BACKEND", "cli")
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")

    sealed = b"age-encryption.org/v1\n" + b"\x00" * 32
    calls: list[str] = []

    def _popen(*_a: Any, **_k: Any) -> _FakeProc:
        mode = "encrypt" if "-e" in (_a[0] if _a else _k.get("args", [])) else "decrypt"
        calls.append(mode)
        if mode == "encrypt":
            return _FakeProc(code=0, stdout=sealed)
        return _FakeProc(code=0, stdout=PLAIN)

    monkeypatch.setattr(subprocess, "Popen", _popen)
    out = io.BytesIO()
    _passphrase.encrypt_io(io.BytesIO(PLAIN), out, PASSPHRASE)
    assert out.getvalue() == sealed
    plain = io.BytesIO()
    _passphrase.decrypt_io(io.BytesIO(sealed), plain, PASSPHRASE)
    assert plain.getvalue() == PLAIN
    assert calls == ["encrypt", "decrypt"]

    def _fail_decrypt(*_a: Any, **_k: Any) -> _FakeProc:
        return _FakeProc(code=1, stderr=b"no identity matched\n")

    monkeypatch.setattr(subprocess, "Popen", _fail_decrypt)
    with pytest.raises(DecryptionError):
        _passphrase.decrypt_io(io.BytesIO(sealed), io.BytesIO(), PASSPHRASE)

    def _fail_header(*_a: Any, **_k: Any) -> _FakeProc:
        return _FakeProc(code=1, stderr=b"failed to read header\n")

    monkeypatch.setattr(subprocess, "Popen", _fail_header)
    with pytest.raises(CorruptDumpError, match="damaged"):
        _passphrase.decrypt_io(io.BytesIO(sealed), io.BytesIO(), PASSPHRASE)

    def _fail_mac(*_a: Any, **_k: Any) -> _FakeProc:
        return _FakeProc(code=1, stderr=b"unexpected eof / bad MAC\n")

    monkeypatch.setattr(subprocess, "Popen", _fail_mac)
    with pytest.raises(CorruptDumpError, match="truncated"):
        _passphrase.decrypt_io(io.BytesIO(sealed), io.BytesIO(), PASSPHRASE)

    def _fail_encrypt(*_a: Any, **_k: Any) -> _FakeProc:
        return _FakeProc(code=2, stderr=b"plugin missing\n")

    monkeypatch.setattr(subprocess, "Popen", _fail_encrypt)
    with pytest.raises(OSError, match="exit 2"):
        _passphrase.encrypt_io(io.BytesIO(PLAIN), io.BytesIO(), PASSPHRASE)


def test_cli_crypt_surfaces_stdin_broken_pipe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("L3IO_AGE_PASSPHRASE_BACKEND", "cli")
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    msg = "closed"

    def _popen(*_a: Any, **_k: Any) -> _FakeProc:
        return _FakeProc(code=0, write_raises=BrokenPipeError(msg))

    monkeypatch.setattr(subprocess, "Popen", _popen)
    with pytest.raises(BrokenPipeError):
        _passphrase.encrypt_io(io.BytesIO(PLAIN), io.BytesIO(), PASSPHRASE)


def test_cli_crypt_requires_binaries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("L3IO_AGE_PASSPHRASE_BACKEND", "cli")
    monkeypatch.setattr(_passphrase, "resolve_backend", lambda: "cli")
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(InvalidArgumentsError, match="age and age-plugin-batchpass"):
        _passphrase.encrypt_io(io.BytesIO(b"x"), io.BytesIO(), PASSPHRASE)


def test_map_cli_failure_default_decrypt_path() -> None:
    with pytest.raises(CorruptDumpError, match="damaged"):
        _passphrase._map_cli_failure(encrypt=False, err="something else", code=1)


def test_check_ready_rejects_empty_passphrase() -> None:
    with pytest.raises(InvalidArgumentsError, match="empty"):
        _passphrase.check_ready("")


def test_binder_decrypt_maps_non_passphrase_decrypt_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import l3io_age_passphrase as binder

    class _Mod:
        DecryptError = binder.DecryptError

        @staticmethod
        def decrypt_io(*_a: Any, **_k: Any) -> None:
            msg = "not an age file"
            raise binder.DecryptError(msg)

    monkeypatch.setenv("L3IO_AGE_PASSPHRASE_BACKEND", "binder")
    monkeypatch.setattr(_passphrase, "_binder", lambda: _Mod)
    with pytest.raises(CorruptDumpError, match="damaged"):
        _passphrase.decrypt_io(io.BytesIO(b"x"), io.BytesIO(), PASSPHRASE)


def test_binder_decrypt_reraises_oserror_with_errno(monkeypatch: pytest.MonkeyPatch) -> None:
    import errno

    import l3io_age_passphrase as binder

    class _Mod:
        DecryptError = binder.DecryptError

        @staticmethod
        def decrypt_io(*_a: Any, **_k: Any) -> None:
            raise OSError(errno.EIO, "io error")

    monkeypatch.setenv("L3IO_AGE_PASSPHRASE_BACKEND", "binder")
    monkeypatch.setattr(_passphrase, "_binder", lambda: _Mod)
    with pytest.raises(OSError) as info:
        _passphrase.decrypt_io(io.BytesIO(b"x"), io.BytesIO(), PASSPHRASE)
    assert info.value.errno == errno.EIO


def test_cli_crypt_surfaces_stdin_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("L3IO_AGE_PASSPHRASE_BACKEND", "cli")
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    msg = "disk full"

    def _popen(*_a: Any, **_k: Any) -> _FakeProc:
        return _FakeProc(code=0, write_raises=OSError(msg))

    monkeypatch.setattr(subprocess, "Popen", _popen)
    with pytest.raises(OSError, match="disk full"):
        _passphrase.encrypt_io(io.BytesIO(PLAIN), io.BytesIO(), PASSPHRASE)


def test_cli_crypt_surfaces_stdin_other_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("L3IO_AGE_PASSPHRASE_BACKEND", "cli")
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    msg = "boom"

    def _popen(*_a: Any, **_k: Any) -> _FakeProc:
        return _FakeProc(code=0, write_raises=RuntimeError(msg))

    monkeypatch.setattr(subprocess, "Popen", _popen)
    with pytest.raises(OSError, match="boom"):
        _passphrase.encrypt_io(io.BytesIO(PLAIN), io.BytesIO(), PASSPHRASE)


def test_cli_crypt_rejects_missing_pipes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("L3IO_AGE_PASSPHRASE_BACKEND", "cli")
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")

    class _NoPipes:
        stdin = None
        stdout = None
        stderr = None

        def kill(self) -> None:
            return None

    monkeypatch.setattr(subprocess, "Popen", lambda *_a, **_k: _NoPipes())
    with pytest.raises(OSError, match="pipes"):
        _passphrase.encrypt_io(io.BytesIO(PLAIN), io.BytesIO(), PASSPHRASE)
