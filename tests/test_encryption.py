"""age encryption (extra: encryption) — pyrage recipients, passphrase backends."""

from __future__ import annotations

import errno
import io
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import IO, cast

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
PASSPHRASE = "test-passphrase-not-a-secret"


class _ChunkedReader(io.RawIOBase):
    """Yields plaintext in fixed-size chunks (not one bytes buffer)."""

    def __init__(self, data: bytes, chunk_size: int = 17) -> None:
        super().__init__()
        self._data = data
        self._chunk_size = chunk_size
        self._offset = 0

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        if self._offset >= len(self._data):
            return b""
        if size is None or size < 0:
            size = self._chunk_size
        size = min(size, self._chunk_size, len(self._data) - self._offset)
        start = self._offset
        self._offset += size
        return self._data[start : self._offset]


def _encrypt(recipient: str) -> bytes:
    out = io.BytesIO()
    encryption.encrypt(io.BytesIO(PLAIN), out, [recipient])
    return out.getvalue()


def _encrypt_passphrase(passphrase: str = PASSPHRASE) -> bytes:
    out = io.BytesIO()
    encryption.encrypt(io.BytesIO(PLAIN), out, passphrase=passphrase)
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


def test_passphrase_round_trip() -> None:
    data = _encrypt_passphrase()
    assert data.startswith(encryption.AGE_HEADER)
    out = io.BytesIO()
    encryption.decrypt(io.BytesIO(data), out, passphrase=PASSPHRASE)
    assert out.getvalue() == PLAIN


def test_passphrase_chunked_reader_round_trip() -> None:
    encrypted = io.BytesIO()
    encryption.encrypt(cast(IO[bytes], _ChunkedReader(PLAIN)), encrypted, passphrase=PASSPHRASE)
    encrypted.seek(0)
    out = io.BytesIO()
    encryption.decrypt(encrypted, out, passphrase=PASSPHRASE)
    assert out.getvalue() == PLAIN


def test_wrong_passphrase_is_a_decryption_error() -> None:
    with pytest.raises(DecryptionError) as info:
        encryption.decrypt(io.BytesIO(_encrypt_passphrase()), io.BytesIO(), passphrase="wrong")
    assert PASSPHRASE not in str(info.value)
    assert "wrong" not in str(info.value)


@pytest.mark.parametrize("damage", ["truncate", "flip_body", "not_age"])
def test_passphrase_damage_is_a_corrupt_dump_error(damage: str) -> None:
    data = bytearray(_encrypt_passphrase())
    if damage == "truncate":
        data = data[: max(8, len(data) // 2)]
    elif damage == "flip_body":
        data[len(data) // 2] ^= 0xFF
    else:
        data = bytearray(b"hello, not age at all")
    with pytest.raises(CorruptDumpError):
        encryption.decrypt(io.BytesIO(bytes(data)), io.BytesIO(), passphrase=PASSPHRASE)


def test_passphrase_mutex() -> None:
    _, recipient = encryption.generate_identity()
    with pytest.raises(InvalidArgumentsError):
        encryption.encrypt(io.BytesIO(b"x"), io.BytesIO(), [recipient], passphrase=PASSPHRASE)
    with pytest.raises(InvalidArgumentsError):
        encryption.encrypt(io.BytesIO(b"x"), io.BytesIO())
    with pytest.raises(InvalidArgumentsError):
        encryption.encrypt(io.BytesIO(b"x"), io.BytesIO(), passphrase="")
    identity, _ = encryption.generate_identity()
    with pytest.raises(InvalidArgumentsError):
        encryption.decrypt(io.BytesIO(b"x"), io.BytesIO(), [identity], passphrase=PASSPHRASE)


def test_check_passphrase_refuses_empty() -> None:
    with pytest.raises(InvalidArgumentsError):
        encryption.check_passphrase("")
    encryption.check_passphrase(PASSPHRASE)


def test_root_reexports_encryption_api() -> None:
    from l3io.wp import database as pkg

    assert pkg.encrypt is encryption.encrypt
    assert pkg.decrypt is encryption.decrypt
    assert pkg.check_passphrase is encryption.check_passphrase
    assert pkg.check_recipients is encryption.check_recipients


@pytest.mark.skipif(shutil.which("age") is None, reason="age CLI not installed")
def test_passphrase_decrypts_with_stock_age() -> None:
    age_bin = shutil.which("age")
    if age_bin is None:  # pragma: no cover - skipif already gated
        pytest.skip("age CLI not installed")
    data = _encrypt_passphrase()
    with tempfile.TemporaryDirectory() as tempdir:
        encrypted_path = Path(tempdir) / "payload.age"
        decrypted_path = Path(tempdir) / "payload.out"
        encrypted_path.write_bytes(data)
        import pty

        master, slave = pty.openpty()
        try:
            proc = subprocess.Popen(  # noqa: S603 - absolute age from PATH, fixed args
                [age_bin, "--decrypt", "-o", str(decrypted_path), str(encrypted_path)],
                stdin=slave,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
            )
            os.close(slave)
            slave = -1
            os.write(master, (PASSPHRASE + "\n").encode())
            stdout, stderr = proc.communicate(timeout=60)
        finally:
            os.close(master)
            if slave >= 0:
                os.close(slave)
        assert proc.returncode == 0, (stdout, stderr)
        assert decrypted_path.read_bytes() == PLAIN
