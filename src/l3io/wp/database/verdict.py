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
    CLIENT_TOOL_MISSING = "client_tool_missing"
    CLIENT_SERVER_SKEW = "client_server_skew"
    PLATFORM_UNSUPPORTED = "platform_unsupported"
    OPTION_NOT_ALLOWED = "option_not_allowed"
    DATABASE_NOT_EMPTY = "database_not_empty"
    INCOMPATIBLE_DUMP_SOURCE = "incompatible_dump_source"
    CROSS_FAMILY_DUMP = "cross_family_dump"
    STORED_OBJECTS_PRESENT = "stored_objects_present"
    IDENTITY_REQUIRED = "identity_required"

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
        Code.CLIENT_TOOL_MISSING: _B,
        Code.CLIENT_SERVER_SKEW: _W,
        Code.PLATFORM_UNSUPPORTED: _B,
        Code.OPTION_NOT_ALLOWED: _B,
        Code.DATABASE_NOT_EMPTY: _B,
        Code.INCOMPATIBLE_DUMP_SOURCE: _B,
        Code.CROSS_FAMILY_DUMP: _W,
        Code.STORED_OBJECTS_PRESENT: _W,
        Code.IDENTITY_REQUIRED: _B,
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
        Code.CLIENT_TOOL_MISSING: (
            "no suitable dump or client program is on PATH; fields.tools names those tried"
        ),
        Code.CLIENT_SERVER_SKEW: (
            "the client program's family, or its major.minor version, is older than or differs "
            "from the server's"
        ),
        Code.PLATFORM_UNSUPPORTED: "export and import need /dev/fd, which this platform lacks",
        Code.OPTION_NOT_ALLOWED: (
            "a caller-supplied client option is not on the allow-list; fields.option names it"
        ),
        Code.DATABASE_NOT_EMPTY: "the load target holds tables and replace= was not given",
        Code.INCOMPATIBLE_DUMP_SOURCE: (
            "the dump begins with MariaDB's sandbox line and this client cannot read it; "
            "allow_unsandboxed=True strips that line"
        ),
        Code.CROSS_FAMILY_DUMP: (
            "the dump comes from the other server family; collations it uses may not exist here"
        ),
        Code.STORED_OBJECTS_PRESENT: (
            "the database has views or triggers: they carry DEFINER clauses that loading needs "
            "privilege for, and MariaDB keeps their original text, which may name this schema"
        ),
        Code.IDENTITY_REQUIRED: "the source is age-encrypted and no identity was supplied",
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
