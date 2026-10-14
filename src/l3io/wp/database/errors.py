"""Exception hierarchy owned by this package.

AD-14: no dependency's exception type crosses a public boundary. Driver and SDK
errors are caught and re-raised as one of these, with ``raise ... from``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .verdict import Verdict


class DatabaseError(Exception):
    """Base class for every error this package raises."""


class InvalidArgumentsError(DatabaseError):
    """An invalid combination of arguments was supplied."""


class InvalidIdentifierError(DatabaseError):
    """A database or user name is not usable as a MySQL identifier."""

    def __init__(self, kind: str, value: str, reason: str) -> None:
        self.kind = kind
        self.value = value
        self.reason = reason
        super().__init__(f"{kind} {value!r} is not a valid identifier: {reason}")


class InvalidDatabaseNameError(InvalidIdentifierError):
    """A database name is not usable as a MySQL identifier."""

    def __init__(self, value: str, reason: str = "not a valid database name") -> None:
        super().__init__("database name", value, reason)


class MissingDependencyError(DatabaseError):
    """An optional feature was used without its extra installed.

    AD-8: optional dependencies are imported inside the function that needs
    them, and their absence is reported by naming the extra to install.
    """

    def __init__(self, extra: str, distribution: str) -> None:
        self.extra = extra
        self.distribution = distribution
        super().__init__(
            f"this feature needs {distribution!r}, which is not installed. "
            f"Install it with: pip install 'l3io-wordpress-database[{extra}]'"
        )


class CredentialsUnobtainableError(DatabaseError):
    """Credentials could not be obtained from their source.

    Distinct from authentication failure: nothing was attempted against the
    database, because there was nothing to attempt it with.
    """


class CredentialsAbsentError(DatabaseError):
    """A credential source had nothing to offer.

    Distinct from :class:`CredentialsUnobtainableError`: an unset variable is
    absence, a refused AWS call is failure. A
    :class:`~l3io.wp.database.CredentialChain` moves on only after absence.
    """

    def __init__(self, message: str, sources: tuple[str, ...] = ()) -> None:
        self.sources = sources
        super().__init__(message)


class RegionNotKnownError(CredentialsUnobtainableError):
    """An AWS region was neither supplied nor discoverable from the session."""

    def __init__(self) -> None:
        super().__init__(
            "the AWS region was not supplied and could not be determined from the current session"
        )


class ConfigurationError(DatabaseError):
    """A WordPress configuration file could not be used."""


class ConfigUnreadableError(ConfigurationError):
    """The configuration file could not be read."""

    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        super().__init__(f"could not read WordPress configuration {path!r}: {reason}")


class MissingConfigValueError(ConfigurationError):
    """A setting the database needs is not defined in the configuration."""

    def __init__(self, key: str, path: str) -> None:
        self.key = key
        self.path = path
        super().__init__(f"{key} is not defined in {path!r}")


class DatabaseUnreachableError(DatabaseError):
    """The database server could not be reached at all."""


class AuthenticationFailedError(DatabaseError):
    """The server was reached but rejected the supplied credentials."""


class AccessDeniedError(DatabaseError):
    """Authentication succeeded but the account may not use the database."""


class ProvisioningError(DatabaseError):
    """A provisioning operation started and failed part-way."""

    def __init__(self, message: str, completed: tuple[str, ...] = ()) -> None:
        self.completed = completed
        super().__init__(message)


class RefusedError(DatabaseError):
    """A check found a blocker, so the operation did not run."""

    def __init__(self, verdict: Verdict) -> None:
        self.verdict = verdict
        reasons = "; ".join(f"{f.code}: {f.message}" for f in verdict.blockers)
        super().__init__(f"{verdict.operation} refused: {reasons}")


class TransferError(DatabaseError):
    """A dump or load started and failed. ``stderr`` is capped and redacted."""

    def __init__(self, message: str, verdict: Verdict, exit_code: int | None, stderr: str) -> None:
        self.verdict = verdict
        self.exit_code = exit_code
        self.stderr = stderr
        super().__init__(message)


class DecryptionError(DatabaseError):
    """None of the supplied identities can decrypt the source."""


class CorruptDumpError(DatabaseError):
    """An encrypted source is truncated, damaged, or not an age file."""
