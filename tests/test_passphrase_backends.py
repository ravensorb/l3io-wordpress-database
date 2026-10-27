"""Passphrase backend selection: binder preferred, age+batchpass CLI fallback."""

from __future__ import annotations

import io
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("l3io_age_passphrase")

from l3io.wp.database import _passphrase, encryption
from l3io.wp.database.errors import DecryptionError, InvalidArgumentsError, MissingDependencyError

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
