"""Provisioning operations, each checked before it runs.

Every operation's preflight produces a :class:`Verdict`. ``check_X`` returns it;
``X`` raises :class:`RefusedError` with it on a blocker, so the check is never
skipped and never differs from the run. ``ensure`` queries facts, plans with a
pure function, and executes only what the plan names, so a converged server
sees no writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pymysql

from ._observe import operation
from ._sql import classify, open_connection
from .connection import Connection
from .credentials import CredentialSource, Explicit, ResolvedCredentials
from .errors import (
    CredentialsAbsentError,
    CredentialsUnobtainableError,
    ProvisioningError,
    RefusedError,
)
from .identifiers import (
    grant_pattern,
    quote_grant_database,
    quote_identifier,
    validate_charset,
    validate_user_name,
)
from .inspection import inspect
from .server import Privileges, account_privileges, detect_server, grantee
from .state import ConnectionState
from .verdict import Code, Finding, Verdict

WORDPRESS_PRIVILEGES = frozenset(
    {"SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER", "INDEX"}
)
ENSURE_PRIVILEGES = ("CREATE", "CREATE USER", "SELECT", "GRANT OPTION")


@dataclass(frozen=True, slots=True)
class EnsureFacts:
    """What already exists, as the administrator sees it."""

    database_exists: bool
    user_exists: bool
    password_works: bool
    grant_present: bool


@dataclass(frozen=True, slots=True)
class EnsureResult:
    """What :func:`ensure` changed. Each flag is true only if it changed something."""

    created_database: bool
    created_user: bool
    password_set: bool
    granted: bool
    verdict: Verdict

    @property
    def changed(self) -> bool:
        return self.created_database or self.created_user or self.password_set or self.granted


def plan_ensure(facts: EnsureFacts) -> tuple[str, ...]:
    """The steps that converge the server on the desired state, in order."""
    steps: list[str] = []
    if not facts.database_exists:
        steps.append("create_database")
    if not facts.user_exists:
        steps.append("create_user")
    elif not facts.password_works:
        steps.append("set_password")
    if not facts.grant_present:
        steps.append("grant")
    return tuple(steps)


def _privilege_findings(privileges: Privileges, required: tuple[str, ...]) -> list[Finding]:
    if privileges.unverified:
        return [
            Finding(
                Code.PRIVILEGES_UNVERIFIED,
                "the administrator has an active role; its privileges cannot be "
                "checked in advance, so the operation will be attempted",
            )
        ]
    return [
        Finding(
            Code.MISSING_PRIVILEGE,
            f"the administrator lacks {name}",
            {"privilege": name},
        )
        for name in required
        if not privileges.has(name)
    ]


def _preflight(
    connection: Connection,
    admin: CredentialSource,
    operation_name: str,
    required: tuple[str, ...],
) -> tuple[Verdict, Any | None]:
    """Connect as the administrator and check server and privileges.

    Returns the verdict and, only when it holds no blocker, the open session.
    """
    verdict = Verdict(operation_name)
    try:
        resolved = admin.resolve()
    except (CredentialsUnobtainableError, CredentialsAbsentError) as exc:
        return verdict.with_findings(Finding(Code.CREDENTIALS_UNOBTAINABLE, str(exc))), None
    try:
        session = open_connection(connection, resolved, database=None)
    except pymysql.err.MySQLError as exc:
        if classify(exc) is ConnectionState.AUTHENTICATION_FAILED:
            finding = Finding(
                Code.AUTHENTICATION_FAILED,
                f"the administrator account {resolved.username!r} was rejected",
            )
        else:
            finding = Finding(
                Code.UNREACHABLE,
                f"{connection.host}:{connection.port} could not be reached",
                {"host": connection.host, "port": connection.port},
            )
        return verdict.with_findings(finding), None

    with session.cursor() as cur:
        server = detect_server(cur)
        findings: list[Finding] = []
        if not server.is_supported:
            findings.append(
                Finding(
                    Code.SERVER_UNSUPPORTED,
                    f"{server.family} {server.version_text} is below the supported floor",
                    {"version": server.version_text},
                )
            )
        elif server.is_end_of_life:
            findings.append(
                Finding(
                    Code.END_OF_LIFE_SERVER,
                    f"{server.family} {server.version_text} is past upstream end of life",
                    {"version": server.version_text},
                )
            )
        findings += _privilege_findings(account_privileges(cur, connection.database), required)
    verdict = verdict.with_findings(*findings)
    if not verdict.ok:
        session.close()
        return verdict, None
    return verdict, session


def _ensure_facts(
    cur: Any, connection: Connection, wordpress: ResolvedCredentials, user_host: str
) -> EnsureFacts:
    database = connection.database
    cur.execute(
        "SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s", (database,)
    )
    database_exists = int(cur.fetchone()[0]) > 0
    cur.execute(
        "SELECT COUNT(*) FROM mysql.user WHERE User = %s AND Host = %s",
        (wordpress.username, user_host),
    )
    user_exists = int(cur.fetchone()[0]) > 0
    password_works = False
    if user_exists:
        try:
            open_connection(connection, wordpress, database=None).close()
            password_works = True
        except pymysql.err.MySQLError as exc:
            if classify(exc) is not ConnectionState.AUTHENTICATION_FAILED:
                msg = f"could not test {wordpress.username!r}'s password"
                raise ProvisioningError(msg) from exc
    cur.execute(
        "SELECT PRIVILEGE_TYPE FROM information_schema.SCHEMA_PRIVILEGES "
        "WHERE GRANTEE = %s AND TABLE_SCHEMA = %s",
        (grantee(wordpress.username, user_host), grant_pattern(database)),
    )
    held = frozenset(str(r[0]) for r in cur.fetchall())
    return EnsureFacts(database_exists, user_exists, password_works, held >= WORDPRESS_PRIVILEGES)


def check_ensure(
    connection: Connection,
    admin: CredentialSource,
    wordpress: CredentialSource,
    *,
    user_host: str = "%",  # noqa: ARG001 - kept so check_ensure mirrors ensure's signature
) -> Verdict:
    """What :func:`ensure` would find, without changing anything."""
    with operation("check_ensure", connection):
        verdict, session = _preflight(connection, admin, "ensure", ENSURE_PRIVILEGES)
        if session is not None:
            session.close()
        try:
            validate_user_name(wordpress.resolve().username)
        except (CredentialsUnobtainableError, CredentialsAbsentError) as exc:
            verdict = verdict.with_findings(Finding(Code.CREDENTIALS_UNOBTAINABLE, str(exc)))
        return verdict


def ensure(
    connection: Connection,
    admin: CredentialSource,
    wordpress: CredentialSource,
    *,
    user_host: str = "%",
    charset: str = "utf8mb4",
    collation: str = "utf8mb4_unicode_ci",
) -> EnsureResult:
    """Converge the server on: database exists, account exists with this password,
    account holds ALL on this database only.

    Raises:
        RefusedError: the check found a blocker; nothing ran.
        ProvisioningError: a statement failed, or the account still cannot use
            the database afterwards; ``completed`` lists the steps that ran.
    """
    validate_charset(charset, "charset")
    validate_charset(collation, "collation")
    with operation("ensure", connection) as fields:
        verdict, session = _preflight(connection, admin, "ensure", ENSURE_PRIVILEGES)
        try:
            wp = wordpress.resolve()
        except (CredentialsUnobtainableError, CredentialsAbsentError) as exc:
            if session is not None:
                session.close()
            verdict = verdict.with_findings(Finding(Code.CREDENTIALS_UNOBTAINABLE, str(exc)))
            raise RefusedError(verdict) from exc
        if session is None:
            raise RefusedError(verdict)
        username = validate_user_name(wp.username)
        database = connection.database
        statements = {
            "create_database": (
                f"CREATE DATABASE {quote_identifier(database)} "
                f"CHARACTER SET {charset} COLLATE {collation}",
                None,
            ),
            "create_user": (
                "CREATE USER %s@%s IDENTIFIED BY %s",
                (username, user_host, wp.password),
            ),
            "set_password": (
                "ALTER USER %s@%s IDENTIFIED BY %s",
                (username, user_host, wp.password),
            ),
            "grant": (
                f"GRANT ALL PRIVILEGES ON {quote_grant_database(database)}.* TO %s@%s",
                (username, user_host),
            ),
        }
        completed: list[str] = []
        with session, session.cursor() as cur:
            steps = plan_ensure(_ensure_facts(cur, connection, wp, user_host))
            try:
                for step in steps:
                    sql, args = statements[step]
                    cur.execute(sql, args)
                    completed.append(step)
                session.commit()
            except pymysql.err.MySQLError as exc:
                msg = f"ensuring {database!r} failed after {len(completed)} step(s)"
                raise ProvisioningError(msg, completed=tuple(completed)) from exc

        final = inspect(connection, Explicit(wp.username, wp.password))
        if not final.is_ready:
            msg = f"ensure ran but {database!r} is still not usable by {username!r}: {final}"
            raise ProvisioningError(msg, completed=tuple(completed))

        result = EnsureResult(
            created_database="create_database" in completed,
            created_user="create_user" in completed,
            password_set="create_user" in completed or "set_password" in completed,
            granted="grant" in completed,
            verdict=verdict,
        )
        fields.update(
            created_database=result.created_database,
            created_user=result.created_user,
            password_set=result.password_set,
            granted=result.granted,
        )
        return result
