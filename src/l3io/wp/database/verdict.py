"""What a check found, as data a caller can branch on.

Every check returns a :class:`Verdict`. An operation runs its check first and
refuses with :class:`~l3io.wp.database.errors.RefusedError` carrying the same
verdict when it holds a blocker; on success the verdict's warnings travel on the
result. A caller therefore branches on :class:`Code` values and never parses a
message.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType


class Severity(StrEnum):
    """Whether a finding stops the operation."""

    BLOCKER = "blocker"
    WARNING = "warning"


class Code(StrEnum):
    """Every finding a check can report. Each code has exactly one severity."""

    UNREACHABLE = "unreachable"
    CREDENTIALS_UNOBTAINABLE = "credentials_unobtainable"
    AUTHENTICATION_FAILED = "authentication_failed"
    SERVER_UNSUPPORTED = "server_unsupported"
    MISSING_PRIVILEGE = "missing_privilege"
    PRIVILEGES_UNVERIFIED = "privileges_unverified"
    DATABASE_ABSENT = "database_absent"
    USER_ABSENT = "user_absent"
    CONFIRMATION_MISMATCH = "confirmation_mismatch"
    LIVE_WORDPRESS_SITE = "live_wordpress_site"
    END_OF_LIFE_SERVER = "end_of_life_server"
    MISSING_DEPENDENCY = "missing_dependency"
    PASSWORD_UNVERIFIED = "password_unverified"  # noqa: S105 - a finding code, not a password

    @property
    def severity(self) -> Severity:
        """The fixed severity of this code."""
        return _SEVERITY[self]

    @property
    def description(self) -> str:
        """When this code is raised."""
        return _DESCRIPTION[self]


_B, _W = Severity.BLOCKER, Severity.WARNING

_SEVERITY: Mapping[Code, Severity] = MappingProxyType(
    {
        Code.UNREACHABLE: _B,
        Code.CREDENTIALS_UNOBTAINABLE: _B,
        Code.AUTHENTICATION_FAILED: _B,
        Code.SERVER_UNSUPPORTED: _B,
        Code.MISSING_PRIVILEGE: _B,
        Code.PRIVILEGES_UNVERIFIED: _W,
        Code.DATABASE_ABSENT: _B,
        Code.USER_ABSENT: _B,
        Code.CONFIRMATION_MISMATCH: _B,
        Code.LIVE_WORDPRESS_SITE: _W,
        Code.END_OF_LIFE_SERVER: _W,
        Code.MISSING_DEPENDENCY: _B,
        Code.PASSWORD_UNVERIFIED: _W,
    }
)

_DESCRIPTION: Mapping[Code, str] = MappingProxyType(
    {
        Code.UNREACHABLE: "the server could not be reached",
        Code.CREDENTIALS_UNOBTAINABLE: "a credential source failed to supply credentials",
        Code.AUTHENTICATION_FAILED: "the server rejected the supplied account",
        Code.SERVER_UNSUPPORTED: "the server is below MySQL 8.0 or MariaDB 10.2",
        Code.MISSING_PRIVILEGE: (
            "the account lacks a privilege the operation needs; fields.privilege names it"
        ),
        Code.PRIVILEGES_UNVERIFIED: (
            "the account holds an active role, whose privileges information_schema does "
            "not show, so privilege checks were skipped"
        ),
        Code.DATABASE_ABSENT: "the operation needs an existing database",
        Code.USER_ABSENT: "the operation needs an existing account",
        Code.CONFIRMATION_MISMATCH: "confirm= does not equal the operation's target",
        Code.LIVE_WORDPRESS_SITE: (
            "a destructive target has a WordPress options table and schema version"
        ),
        Code.END_OF_LIFE_SERVER: "the server version is past upstream end of life",
        Code.PASSWORD_UNVERIFIED: (
            "the account's host does not match this machine, so its password could not be "
            "checked by logging in and was left unchanged; use rotate_password to set it"
        ),
        Code.MISSING_DEPENDENCY: (
            "a credential source needs an extra that is not installed; fields.extra names it"
        ),
    }
)


@dataclass(frozen=True, slots=True)
class Finding:
    """One thing a check found."""

    code: Code
    message: str
    fields: Mapping[str, str | int | bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Frozen dataclasses still hold a mutable dict; freeze the view too.
        object.__setattr__(self, "fields", MappingProxyType(dict(self.fields)))

    @property
    def severity(self) -> Severity:
        """The code's fixed severity."""
        return self.code.severity


@dataclass(frozen=True, slots=True)
class Verdict:
    """Everything one check found about one operation."""

    operation: str
    findings: tuple[Finding, ...] = ()

    @property
    def blockers(self) -> tuple[Finding, ...]:
        """Findings that stop the operation."""
        return tuple(f for f in self.findings if f.severity is Severity.BLOCKER)

    @property
    def warnings(self) -> tuple[Finding, ...]:
        """Findings that let the operation run but describe a risk."""
        return tuple(f for f in self.findings if f.severity is Severity.WARNING)

    @property
    def ok(self) -> bool:
        """Whether nothing blocks the operation."""
        return not self.blockers

    @property
    def codes(self) -> frozenset[Code]:
        """Every code present."""
        return frozenset(f.code for f in self.findings)

    def with_findings(self, *findings: Finding) -> Verdict:
        """A new verdict with ``findings`` appended."""
        return Verdict(self.operation, self.findings + findings)
