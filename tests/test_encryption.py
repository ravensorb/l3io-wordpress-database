"""age encryption through pyrage (extra: encryption)."""

from __future__ import annotations

import errno
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


class _FailingWriter(io.BytesIO):
    def __init__(self, error: OSError) -> None:
        super().__init__()
        self.error = error

    def write(self, data: object) -> int:
        raise self.error


def _disk_full() -> OSError:
    return OSError(errno.ENOSPC, "No space left on device")


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


def test_decrypt_passes_the_callers_own_write_failure_through() -> None:
    identity, recipient = encryption.generate_identity()
    data = _encrypt(recipient)
    with pytest.raises(OSError) as info:
        encryption.decrypt(io.BytesIO(data), _FailingWriter(_disk_full()), [identity])
    assert info.value.errno == errno.ENOSPC
    assert not isinstance(info.value, CorruptDumpError)


def test_encrypt_reports_a_write_failure_as_an_os_error() -> None:
    _, recipient = encryption.generate_identity()
    with pytest.raises(OSError) as info:
        encryption.encrypt(io.BytesIO(PLAIN), _FailingWriter(_disk_full()), [recipient])
    assert type(info.value).__module__ == "builtins"


def test_encrypt_reports_a_closed_consumer_as_a_broken_pipe() -> None:
    _, recipient = encryption.generate_identity()
    with pytest.raises(BrokenPipeError):
        encryption.encrypt(io.BytesIO(PLAIN), _FailingWriter(BrokenPipeError()), [recipient])


def test_read_identity_of_a_missing_file_names_the_path(tmp_path: Path) -> None:
    missing = tmp_path / "no-such-identity.txt"
    with pytest.raises(InvalidArgumentsError) as info:
        encryption.read_identity(missing)
    assert str(missing) in str(info.value)


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


def test_check_recipients_accepts_a_usable_recipient() -> None:
    _, recipient = encryption.generate_identity()
    encryption.check_recipients([recipient])


@pytest.mark.parametrize("recipients", [[], ["not-a-key-at-all"]])
def test_check_recipients_refuses_what_encrypt_could_not_use(recipients: list[str]) -> None:
    with pytest.raises(InvalidArgumentsError):
        encryption.check_recipients(recipients)


def test_check_recipients_names_the_missing_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    _, recipient = encryption.generate_identity()
    monkeypatch.setitem(sys.modules, "pyrage", None)
    with pytest.raises(MissingDependencyError) as info:
        encryption.check_recipients([recipient])
    assert info.value.extra == "encryption"


def test_missing_extra_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "pyrage", None)
    with pytest.raises(MissingDependencyError) as info:
        encryption.generate_identity()
    assert info.value.extra == "encryption"
