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

from ._observe import VERDICT_KEY, operation
from ._sql import (
    ER_CANNOT_USER,
    ER_DBACCESS_DENIED,
    ER_NONEXISTING_GRANT,
    ER_TABLEACCESS_DENIED,
    classify,
    error_code,
    literal,
    open_connection,
)
from .connection import Connection
from .credentials import CredentialSource, Explicit, ResolvedCredentials
from .errors import (
    AccessDeniedError,
    ConfigurationError,
    CredentialsAbsentError,
    CredentialsUnobtainableError,
    DatabaseError,
    DatabaseUnreachableError,
    InvalidIdentifierError,
    MissingDependencyError,
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
#: GRANT ALL needs the grantor to hold what it grants, not only GRANT OPTION.
ENSURE_PRIVILEGES = (
    "CREATE",
    "CREATE USER",
    "GRANT OPTION",
    *sorted(WORDPRESS_PRIVILEGES - {"CREATE"}),
)
#: Reading ``mysql.user`` needs SELECT on ``*.*``; a database-level SELECT is not enough.
ENSURE_GLOBAL_PRIVILEGES = ("SELECT",)


@dataclass(frozen=True, slots=True)
class EnsureFacts:
    """What already exists, as the administrator sees it."""

    database_exists: bool
    user_exists: bool
    password_works: bool
    grant_present: bool
    #: Whether this machine matches the account's host, so a login proves anything.
    verifiable: bool = True


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


def _privilege_findings(
    privileges: Privileges,
    required: tuple[str, ...],
    global_required: tuple[str, ...] = (),
) -> list[Finding]:
    if privileges.unverified:
        return [
            Finding(
                Code.PRIVILEGES_UNVERIFIED,
                "the administrator has an active role; its privileges cannot be "
                "checked in advance, so the operation will be attempted",
            )
        ]
    missing = [
        Finding(
            Code.MISSING_PRIVILEGE,
            f"the administrator lacks {name}",
            {"privilege": name},
        )
        for name in required
        if not privileges.has(name)
    ]
    missing += [
        Finding(
            Code.MISSING_PRIVILEGE,
            f"the administrator lacks {name} on *.*",
            {"privilege": name, "scope": "global"},
        )
        for name in global_required
        if not privileges.has_global(name)
    ]
    return missing


def _as_package_error(
    exc: pymysql.err.MySQLError, fallback: type[DatabaseError], message: str | None = None
) -> DatabaseError:
    """Translate a server error raised mid-session into a package-owned one."""
    if error_code(exc) in (ER_TABLEACCESS_DENIED, ER_DBACCESS_DENIED):
        return AccessDeniedError(f"the administrator lacks a privilege this operation needs: {exc}")
    return fallback(message or f"the server failed during the operation: {exc}")


def _resolve_or_finding(source: CredentialSource) -> ResolvedCredentials | Finding:
    """Resolve a source, or say why it could not be, as a finding.

    Every failure a source can have is a verdict, never an exception: an absent
    or failed source, a config file that cannot supply the pair, and a missing
    extra.
    """
    try:
        return source.resolve()
    except MissingDependencyError as exc:
        return Finding(Code.MISSING_DEPENDENCY, str(exc), {"extra": exc.extra})
    except (CredentialsUnobtainableError, CredentialsAbsentError, ConfigurationError) as exc:
        return Finding(Code.CREDENTIALS_UNOBTAINABLE, str(exc))


def _preflight(
    connection: Connection,
    admin: CredentialSource,
    operation_name: str,
    required: tuple[str, ...],
    global_required: tuple[str, ...] = (),
) -> tuple[Verdict, Any | None]:
    """Resolve the account, then :func:`_preflight_resolved`."""
    resolved = _resolve_or_finding(admin)
    if isinstance(resolved, Finding):
        return Verdict(operation_name, (resolved,)), None
    return _preflight_resolved(connection, resolved, operation_name, required, global_required)


def _preflight_resolved(
    connection: Connection,
    resolved: ResolvedCredentials,
    operation_name: str,
    required: tuple[str, ...],
    global_required: tuple[str, ...] = (),
) -> tuple[Verdict, Any | None]:
    """Connect as this account and check server and privileges.

    Returns the verdict and, only when it holds no blocker, the open session.
    """
    verdict = Verdict(operation_name)
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

    try:
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
            findings += _privilege_findings(
                account_privileges(cur, connection.database), required, global_required
            )
        verdict = verdict.with_findings(*findings)
    except pymysql.err.MySQLError as exc:
        session.close()
        raise _as_package_error(exc, DatabaseUnreachableError) from exc
    except BaseException:
        session.close()
        raise
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
    # A login from here only says something about the account if the server
    # would match this machine to user_host; ask the server, which applies its
    # own host-pattern rules.
    cur.execute("SELECT SUBSTRING_INDEX(USER(), '@', -1) LIKE %s", (user_host,))
    verifiable = bool(cur.fetchone()[0])
    password_works = not verifiable  # unverifiable: leave an existing password alone
    if user_exists and verifiable:
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
    return EnsureFacts(
        database_exists, user_exists, password_works, held >= WORDPRESS_PRIVILEGES, verifiable
    )


def check_ensure(
    connection: Connection,
    admin: CredentialSource,
    wordpress: CredentialSource,
    *,
    user_host: str = "%",  # noqa: ARG001 - kept so check_ensure mirrors ensure's signature
) -> Verdict:
    """What :func:`ensure` would find, without changing anything."""
    with operation("check_ensure", connection) as fields:
        verdict, session = _preflight(
            connection, admin, "ensure", ENSURE_PRIVILEGES, ENSURE_GLOBAL_PRIVILEGES
        )
        if session is not None:
            session.close()
        wp = _resolve_or_finding(wordpress)
        if isinstance(wp, Finding):
            return _note(fields, verdict.with_findings(wp))
        validate_user_name(wp.username)
        return _note(fields, verdict)


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
        verdict, session = _preflight(
            connection, admin, "ensure", ENSURE_PRIVILEGES, ENSURE_GLOBAL_PRIVILEGES
        )
        wp = _resolve_or_finding(wordpress)
        if isinstance(wp, Finding):
            if session is not None:
                session.close()
            raise RefusedError(verdict.with_findings(wp))
        try:
            # Validated before the session check, exactly as check_ensure does,
            # so both raise the same error for a bad name.
            username = validate_user_name(wp.username)
        except InvalidIdentifierError:
            if session is not None:
                session.close()
            raise
        if session is None:
            raise RefusedError(verdict)
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
                f"GRANT ALL PRIVILEGES ON {literal(quote_grant_database(database))}.* TO %s@%s",
                (username, user_host),
            ),
        }
        completed: list[str] = []
        with session, session.cursor() as cur:
            try:
                facts = _ensure_facts(cur, connection, wp, user_host)
                steps = plan_ensure(facts)
            except pymysql.err.MySQLError as exc:
                raise _as_package_error(exc, ProvisioningError) from exc
            try:
                for step in steps:
                    sql, args = statements[step]
                    cur.execute(sql, args)
                    completed.append(step)
                session.commit()
            except pymysql.err.MySQLError as exc:
                msg = f"ensuring {database!r} failed after {len(completed)} step(s)"
                raise ProvisioningError(msg, completed=tuple(completed)) from exc

        if facts.verifiable:
            final = inspect(connection, Explicit(wp.username, wp.password))
            if not final.is_ready:
                msg = f"ensure ran but {database!r} is still not usable by {username!r}: {final}"
                raise ProvisioningError(msg, completed=tuple(completed))
        else:
            verdict = verdict.with_findings(
                Finding(
                    Code.PASSWORD_UNVERIFIED,
                    f"{username!r}@{user_host!r} does not match this machine, so the result "
                    "was not verified by logging in and an existing password was left unchanged",
                    {"user_host": user_host},
                )
            )

        result = EnsureResult(
            created_database="create_database" in completed,
            created_user="create_user" in completed,
            password_set="create_user" in completed or "set_password" in completed,
            granted="grant" in completed,
            verdict=verdict,
        )
        fields[VERDICT_KEY] = verdict
        fields.update(
            created_database=result.created_database,
            created_user=result.created_user,
            password_set=result.password_set,
            granted=result.granted,
        )
        return result


@dataclass(frozen=True, slots=True)
class OperationResult:
    """Whether an operation changed anything, and what its check found."""

    changed: bool
    verdict: Verdict


#: Reading mysql.user to answer "does this account exist?" needs global SELECT.
_ACCOUNT_LOOKUP = ("SELECT",)


def _confirmation(target: str, confirm: str) -> list[Finding]:
    if confirm == target:
        return []
    return [
        Finding(
            Code.CONFIRMATION_MISMATCH,
            f"confirm={confirm!r} does not match the target {target!r}",
            {"target": target, "confirm": confirm},
        )
    ]


def _user_exists(cur: Any, user: str, user_host: str) -> bool:
    cur.execute("SELECT COUNT(*) FROM mysql.user WHERE User = %s AND Host = %s", (user, user_host))
    return int(cur.fetchone()[0]) > 0


def _looks_live(cur: Any, database: str) -> bool:
    """Whether the database holds a WordPress options table with a schema version."""
    cur.execute(
        "SELECT TABLE_NAME FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME LIKE %s",
        (database, "%options"),
    )
    for (table,) in cur.fetchall():
        try:
            cur.execute(
                f"SELECT COUNT(*) FROM {literal(quote_identifier(database))}"  # noqa: S608 - quoted identifiers
                f".{literal(quote_identifier(table))} "
                "WHERE option_name = %s",
                ("db_version",),
            )
        except pymysql.err.MySQLError:
            continue  # an "...options" table that is not WordPress's
        if int(cur.fetchone()[0]) > 0:
            return True
    return False


def _guarded(
    connection: Connection,
    admin: CredentialSource,
    name: str,
    required: tuple[str, ...],
    extra: list[Finding],
    *,
    user: tuple[str, str] | None = None,
    live_check: bool = False,
) -> tuple[Verdict, Any | None]:
    """The preflight, plus confirmation, account existence and the live-site warning.

    Returns the verdict and, only when it holds no blocker, the open session.
    """
    verdict, session = _preflight(
        connection, admin, name, required, _ACCOUNT_LOOKUP if user else ()
    )
    verdict = verdict.with_findings(*extra)
    if session is None:
        return verdict, None
    try:
        with session.cursor() as cur:
            if user is not None and not _user_exists(cur, *user):
                verdict = verdict.with_findings(
                    Finding(Code.USER_ABSENT, f"{user[0]!r}@{user[1]!r} does not exist")
                )
            if live_check and _looks_live(cur, connection.database):
                verdict = verdict.with_findings(
                    Finding(
                        Code.LIVE_WORDPRESS_SITE,
                        f"{connection.database!r} holds a WordPress options table with a "
                        "schema version",
                    )
                )
    except pymysql.err.MySQLError as exc:
        session.close()
        raise _as_package_error(exc, DatabaseUnreachableError) from exc
    except BaseException:
        session.close()
        raise
    if not verdict.ok:
        session.close()
        return verdict, None
    return verdict, session


def _note(fields: dict[str, object], verdict: Verdict) -> Verdict:
    """Hand a check's verdict to the operation wrapper, which logs its warnings."""
    fields[VERDICT_KEY] = verdict
    return verdict


def _check(verdict_and_session: tuple[Verdict, Any | None]) -> Verdict:
    verdict, session = verdict_and_session
    if session is not None:
        session.close()
    return verdict


def _rotate_guard(
    connection: Connection, admin: CredentialSource, username: str, user_host: str
) -> tuple[Verdict, Any | None]:
    return _guarded(
        connection, admin, "rotate_password", ("CREATE USER",), [], user=(username, user_host)
    )


def check_rotate_password(
    connection: Connection,
    admin: CredentialSource,
    wordpress: CredentialSource,
    *,
    user_host: str = "%",
) -> Verdict:
    """What :func:`rotate_password` would find, without changing anything."""
    with operation("check_rotate_password", connection) as fields:
        wp = _resolve_or_finding(wordpress)
        if isinstance(wp, Finding):
            return _note(fields, Verdict("rotate_password", (wp,)))
        username = validate_user_name(wp.username)
        return _note(fields, _check(_rotate_guard(connection, admin, username, user_host)))


def rotate_password(
    connection: Connection,
    admin: CredentialSource,
    wordpress: CredentialSource,
    *,
    user_host: str = "%",
) -> OperationResult:
    """Set the account's password to the one ``wordpress`` resolves to."""
    with operation("rotate_password", connection) as fields:
        wp = _resolve_or_finding(wordpress)
        if isinstance(wp, Finding):
            raise RefusedError(Verdict("rotate_password", (wp,)))
        username = validate_user_name(wp.username)
        verdict, session = _rotate_guard(connection, admin, username, user_host)
        if session is None:
            raise RefusedError(verdict)
        with session, session.cursor() as cur:
            try:
                cur.execute("ALTER USER %s@%s IDENTIFIED BY %s", (username, user_host, wp.password))
                session.commit()
            except pymysql.err.MySQLError as exc:
                msg = f"setting the password for {username!r} failed"
                raise ProvisioningError(msg) from exc
        fields["changed"] = True
        fields[VERDICT_KEY] = verdict
        return OperationResult(True, verdict)


def _revoke_guard(
    connection: Connection, admin: CredentialSource, user: str, user_host: str, confirm: str
) -> tuple[Verdict, Any | None]:
    return _guarded(
        connection,
        admin,
        "revoke",
        ("GRANT OPTION",),
        _confirmation(user, confirm),
        user=(user, user_host),
    )


def check_revoke(
    connection: Connection,
    admin: CredentialSource,
    user: str,
    *,
    user_host: str = "%",
    confirm: str,
) -> Verdict:
    """What :func:`revoke` would find, without changing anything."""
    with operation("check_revoke", connection) as fields:
        validate_user_name(user)
        return _note(fields, _check(_revoke_guard(connection, admin, user, user_host, confirm)))


def revoke(
    connection: Connection,
    admin: CredentialSource,
    user: str,
    *,
    user_host: str = "%",
    confirm: str,
) -> OperationResult:
    """Revoke the account's privileges on this database only.

    An account holding no grant here is ``changed=False``.
    """
    with operation("revoke", connection) as fields:
        validate_user_name(user)
        verdict, session = _revoke_guard(connection, admin, user, user_host, confirm)
        if session is None:
            raise RefusedError(verdict)
        # The escaped pattern is what ensure grants; the unescaped name is what
        # the 0.0.x package granted, and it also matched neighbouring names.
        targets = dict.fromkeys(
            [quote_grant_database(connection.database), quote_identifier(connection.database)]
        )
        changed = False
        with session, session.cursor() as cur:
            for target in targets:
                try:
                    cur.execute(
                        f"REVOKE ALL PRIVILEGES ON {literal(target)}.* FROM %s@%s",  # noqa: S608 - quoted identifier
                        (user, user_host),
                    )
                except pymysql.err.MySQLError as exc:
                    if error_code(exc) != ER_NONEXISTING_GRANT:
                        msg = f"revoking {user!r} on {connection.database!r} failed"
                        raise _as_package_error(exc, ProvisioningError, msg) from exc
                else:
                    changed = True
            session.commit()
        fields["changed"] = changed
        fields[VERDICT_KEY] = verdict
        return OperationResult(changed, verdict)


def _drop_user_guard(
    connection: Connection, admin: CredentialSource, user: str, confirm: str
) -> tuple[Verdict, Any | None]:
    return _guarded(connection, admin, "drop_user", ("CREATE USER",), _confirmation(user, confirm))


def check_drop_user(
    connection: Connection,
    admin: CredentialSource,
    user: str,
    *,
    user_host: str = "%",  # noqa: ARG001 - kept so check_drop_user mirrors drop_user's signature
    confirm: str,
) -> Verdict:
    """What :func:`drop_user` would find, without changing anything."""
    with operation("check_drop_user", connection) as fields:
        validate_user_name(user)
        return _note(fields, _check(_drop_user_guard(connection, admin, user, confirm)))


def drop_user(
    connection: Connection,
    admin: CredentialSource,
    user: str,
    *,
    user_host: str = "%",
    confirm: str,
) -> OperationResult:
    """Drop the account. An absent account is ``changed=False``."""
    with operation("drop_user", connection) as fields:
        validate_user_name(user)
        verdict, session = _drop_user_guard(connection, admin, user, confirm)
        if session is None:
            raise RefusedError(verdict)
        with session, session.cursor() as cur:
            # Existence is decided by the DROP itself (1396 = no such account), so
            # the run needs only CREATE USER, exactly what the check verified.
            existed = True
            try:
                cur.execute("DROP USER %s@%s", (user, user_host))
                session.commit()
            except pymysql.err.MySQLError as exc:
                if error_code(exc) != ER_CANNOT_USER:
                    msg = f"dropping {user!r} failed"
                    raise _as_package_error(exc, ProvisioningError, msg) from exc
                existed = False
        fields["changed"] = existed
        fields[VERDICT_KEY] = verdict
        return OperationResult(existed, verdict)


def _drop_database_guard(
    connection: Connection, admin: CredentialSource, confirm: str
) -> tuple[Verdict, Any | None]:
    return _guarded(
        connection,
        admin,
        "drop_database",
        ("DROP",),
        _confirmation(connection.database, confirm),
        live_check=True,
    )


def check_drop_database(
    connection: Connection, admin: CredentialSource, *, confirm: str
) -> Verdict:
    """What :func:`drop_database` would find, without changing anything."""
    with operation("check_drop_database", connection) as fields:
        return _note(fields, _check(_drop_database_guard(connection, admin, confirm)))


def drop_database(
    connection: Connection, admin: CredentialSource, *, confirm: str
) -> OperationResult:
    """Drop the database. An absent database is ``changed=False``."""
    with operation("drop_database", connection) as fields:
        verdict, session = _drop_database_guard(connection, admin, confirm)
        if session is None:
            raise RefusedError(verdict)
        with session, session.cursor() as cur:
            try:
                cur.execute(
                    "SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s",
                    (connection.database,),
                )
                existed = int(cur.fetchone()[0]) > 0
                cur.execute(f"DROP DATABASE IF EXISTS {quote_identifier(connection.database)}")
                session.commit()
            except pymysql.err.MySQLError as exc:
                msg = f"dropping {connection.database!r} failed"
                raise _as_package_error(exc, ProvisioningError, msg) from exc
        fields["changed"] = existed
        fields[VERDICT_KEY] = verdict
        return OperationResult(existed, verdict)
