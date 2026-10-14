"""age encryption through pyrage (extra: encryption)."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

pytest.importorskip("pyrage")

from l3io.wp.database import encryption
from l3io.wp.database.errors import (
    CorruptDumpError,
    DecryptionError,
    InvalidArgumentsError,
    MissingDependencyError,
)

PLAIN = b"INSERT INTO t VALUES (1);\n" * 5000


def _encrypt(recipient: str) -> bytes:
    out = io.BytesIO()
    encryption.encrypt(io.BytesIO(PLAIN), out, [recipient])
    return out.getvalue()


def test_round_trip() -> None:
    identity, recipient = encryption.generate_identity()
    data = _encrypt(recipient)
    assert data.startswith(encryption.AGE_HEADER)
    out = io.BytesIO()
    encryption.decrypt(io.BytesIO(data), out, [identity])
    assert out.getvalue() == PLAIN


def test_wrong_identity_is_a_decryption_error() -> None:
    _, recipient = encryption.generate_identity()
    other, _ = encryption.generate_identity()
    with pytest.raises(DecryptionError):
        encryption.decrypt(io.BytesIO(_encrypt(recipient)), io.BytesIO(), [other])


@pytest.mark.parametrize("damage", ["truncate", "flip_body", "not_age"])
def test_damage_is_a_corrupt_dump_error(damage: str) -> None:
    identity, recipient = encryption.generate_identity()
    data = bytearray(_encrypt(recipient))
    if damage == "truncate":
        data = data[:-50]
    elif damage == "flip_body":
        data[len(data) // 2] ^= 0xFF
    else:
        data = bytearray(b"hello, not age at all")
    with pytest.raises(CorruptDumpError):
        encryption.decrypt(io.BytesIO(bytes(data)), io.BytesIO(), [identity])


def test_a_bad_recipient_does_not_echo_much(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(InvalidArgumentsError):
        encryption.encrypt(io.BytesIO(b"x"), io.BytesIO(), ["not-a-key-at-all-xxxxxxxxxxxxxxxx"])


def test_a_bad_identity_is_not_echoed() -> None:
    secret = "AGE-SECRET-KEY-NOT-REALLY-VALID-1234567890"
    with pytest.raises(InvalidArgumentsError) as info:
        encryption.decrypt(io.BytesIO(b"x"), io.BytesIO(), [secret])
    assert secret not in str(info.value)


def test_no_recipients_is_rejected() -> None:
    with pytest.raises(InvalidArgumentsError):
        encryption.encrypt(io.BytesIO(b"x"), io.BytesIO(), [])


def test_read_identity_plain_and_passphrase_protected(tmp_path: Path) -> None:
    import pyrage

    identity, _ = encryption.generate_identity()
    plain = tmp_path / "id.txt"
    plain.write_text(f"# created: today\n{identity}\n")
    assert encryption.read_identity(plain) == identity
    wrapped = tmp_path / "id.age"
    wrapped.write_bytes(pyrage.passphrase.encrypt(plain.read_bytes(), "pw"))
    assert encryption.read_identity(wrapped, "pw") == identity
    with pytest.raises(DecryptionError):
        encryption.read_identity(wrapped, "wrong")


def test_missing_extra_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "pyrage", None)
    with pytest.raises(MissingDependencyError) as info:
        encryption.generate_identity()
    assert info.value.extra == "encryption"
