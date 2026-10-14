"""Optional age encryption of dumps, through ``pyrage`` (extra ``encryption``).

The format is standard age, so any dump this package encrypts can be decrypted
by the stock ``age`` command line. Errors are mapped to package types: a wrong
identity is :class:`DecryptionError`; a damaged, truncated or non-age stream is
:class:`CorruptDumpError` (probe V4). Secret identities never appear in messages.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import IO, Any

from .errors import CorruptDumpError, DecryptionError, InvalidArgumentsError, MissingDependencyError

AGE_HEADER = b"age-encryption.org/v1"
_SECRET_PREFIX = "AGE-SECRET-KEY-"  # noqa: S105 - the prefix age identities carry, not a secret


def _pyrage() -> Any:
    try:
        import pyrage
    except ImportError as exc:
        raise MissingDependencyError(extra="encryption", distribution="pyrage") from exc
    return pyrage


def generate_identity() -> tuple[str, str]:
    """A new age identity and its public recipient: ``(identity, recipient)``."""
    pyrage = _pyrage()
    identity = pyrage.x25519.Identity.generate()
    return str(identity), str(identity.to_public())


def read_identity(path: str | Path, passphrase: str | None = None) -> str:
    """The age identity in a file, optionally passphrase-protected (age's own format)."""
    pyrage = _pyrage()
    data = Path(path).read_bytes()
    if passphrase is not None:
        try:
            data = pyrage.passphrase.decrypt(data, passphrase)
        except pyrage.DecryptError as exc:
            msg = f"could not unlock the identity file {str(path)!r} with that passphrase"
            raise DecryptionError(msg) from exc
    for line in data.decode("utf-8", errors="replace").splitlines():
        if line.strip().startswith(_SECRET_PREFIX):
            return line.strip()
    msg = f"{str(path)!r} holds no age identity"
    raise InvalidArgumentsError(msg)


def _recipients(pyrage: Any, recipients: Sequence[str]) -> list[Any]:
    if not recipients:
        msg = "encryption needs at least one recipient"
        raise InvalidArgumentsError(msg)
    parsed: list[Any] = []
    for recipient in recipients:
        try:
            if recipient.startswith(("ssh-", "ecdsa-")):
                parsed.append(pyrage.ssh.Recipient.from_str(recipient))
            else:
                parsed.append(pyrage.x25519.Recipient.from_str(recipient))
        except Exception as exc:  # noqa: BLE001 - pyrage errors are not a public type (AD-14)
            msg = f"not an age or SSH public key: {recipient[:12]}..."
            raise InvalidArgumentsError(msg) from exc
    return parsed


def _identities(pyrage: Any, identities: Sequence[str]) -> list[Any]:
    if not identities:
        msg = "decryption needs at least one identity"
        raise InvalidArgumentsError(msg)
    parsed: list[Any] = []
    for index, identity in enumerate(identities):
        text = identity.strip()
        try:
            if text.startswith(_SECRET_PREFIX):
                parsed.append(pyrage.x25519.Identity.from_str(text))
            else:
                parsed.append(pyrage.ssh.Identity.from_buffer(text.encode()))
        except Exception as exc:  # noqa: BLE001 - pyrage errors are not a public type (AD-14)
            msg = f"identity #{index + 1} is not a usable age or SSH private key"
            raise InvalidArgumentsError(msg) from exc
    return parsed


def encrypt(reader: IO[bytes], writer: IO[bytes], recipients: Sequence[str]) -> None:
    """Stream ``reader`` into ``writer`` as age, for every recipient."""
    pyrage = _pyrage()
    pyrage.encrypt_io(reader, writer, _recipients(pyrage, recipients))


def decrypt(reader: IO[bytes], writer: IO[bytes], identities: Sequence[str]) -> None:
    """Stream an age ``reader`` into ``writer`` as plaintext."""
    pyrage = _pyrage()
    keys = _identities(pyrage, identities)
    try:
        pyrage.decrypt_io(reader, writer, keys)
    except BrokenPipeError:
        raise  # the consumer stopped reading; not a property of the stream
    except pyrage.DecryptError as exc:
        if "No matching keys" in str(exc):
            msg = "none of the supplied identities can decrypt this dump"
            raise DecryptionError(msg) from exc
        msg = "the encrypted dump is damaged or not an age file"
        raise CorruptDumpError(msg) from exc
    except OSError as exc:
        msg = "the encrypted dump is truncated or damaged"
        raise CorruptDumpError(msg) from exc
