"""Optional age encryption of dumps (extra ``encryption``).

Recipients / identities go through ``pyrage``. Passphrase streaming uses
``l3io-age-passphrase`` (preferred) or stock ``age`` with
``age-plugin-batchpass`` (see ``L3IO_AGE_PASSPHRASE_BACKEND``). The format is
standard age, so any dump this package encrypts can be decrypted by the stock
``age`` command line. Errors are mapped to package types: a wrong identity or
passphrase is :class:`DecryptionError`; a damaged, truncated or non-age stream
is :class:`CorruptDumpError` (probe V4). Secret identities and passphrases
never appear in messages.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import IO, Any

from . import _passphrase
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
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        msg = f"cannot read the identity file {str(path)!r}: {exc.strerror}"
        raise InvalidArgumentsError(msg) from exc
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


def _mutex_secret(
    named: str,
    sequence: Sequence[str] | None,
    passphrase: str | None,
    *,
    action: str,
) -> None:
    has_seq = sequence is not None
    has_pass = passphrase is not None
    if has_seq == has_pass:
        if has_seq:
            msg = f"supply {named}= or passphrase=, not both"
        else:
            msg = f"{action} needs {named}= or passphrase="
        raise InvalidArgumentsError(msg)
    if has_pass and passphrase == "":
        msg = "passphrase must not be empty"
        raise InvalidArgumentsError(msg)


def check_recipients(recipients: Sequence[str]) -> None:
    """Refuse recipients :func:`encrypt` could not use, before any data moves."""
    _recipients(_pyrage(), recipients)


def check_passphrase(passphrase: str) -> None:
    """Refuse a passphrase :func:`encrypt` could not use, before any data moves."""
    _passphrase.check_ready(passphrase)


def encrypt(
    reader: IO[bytes],
    writer: IO[bytes],
    recipients: Sequence[str] | None = None,
    *,
    passphrase: str | None = None,
) -> None:
    """Stream ``reader`` into ``writer`` as age.

    Exactly one of ``recipients`` or ``passphrase``. Passphrase mode emits a
    sole scrypt recipient (stock ``age -d``).
    """
    _mutex_secret("recipients", recipients, passphrase, action="encryption")
    if passphrase is not None:
        _passphrase.encrypt_io(reader, writer, passphrase)
        return
    pyrage = _pyrage()
    try:
        keys = _recipients(pyrage, recipients or ())
        pyrage.encrypt_io(reader, writer, keys)
    except pyrage.EncryptError as exc:
        # pyrage flattens the caller's I/O exception into text, e.g. "OSError: [Errno 28] ..."
        if str(exc).startswith("BrokenPipeError"):
            raise BrokenPipeError(str(exc)) from exc
        raise OSError(str(exc)) from exc


def decrypt(
    reader: IO[bytes],
    writer: IO[bytes],
    identities: Sequence[str] | None = None,
    *,
    passphrase: str | None = None,
) -> None:
    """Stream an age ``reader`` into ``writer`` as plaintext.

    Exactly one of ``identities`` or ``passphrase``.
    """
    _mutex_secret("identities", identities, passphrase, action="decryption")
    if passphrase is not None:
        _passphrase.decrypt_io(reader, writer, passphrase)
        return
    pyrage = _pyrage()
    try:
        keys = _identities(pyrage, identities or ())
        pyrage.decrypt_io(reader, writer, keys)
    except BrokenPipeError:
        raise  # the consumer stopped reading; not a property of the stream
    except pyrage.DecryptError as exc:
        text = str(exc)
        if "No matching keys" in text:
            msg = "none of the supplied identities can decrypt this dump"
            raise DecryptionError(msg) from exc
        msg = "the encrypted dump is damaged or not an age file"
        raise CorruptDumpError(msg) from exc
    except OSError as exc:
        # pyrage's own stream failure is a bare OSError without errno; anything else is
        # the caller's reader or writer failing and keeps its type and errno.
        if type(exc) is not OSError or exc.errno is not None:
            raise
        msg = "the encrypted dump is truncated or damaged"
        raise CorruptDumpError(msg) from exc
