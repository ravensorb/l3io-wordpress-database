"""Read-only questions about a database, answered by the right account.

:func:`survey` runs as the administrator and is the authority on what exists
(AD-29). :func:`inspect` is the WordPress account's own login probe: it
describes the account, never whether the database exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pymysql

from ._observe import operation
from ._sql import (
    ER_DBACCESS_DENIED,
    ER_TABLEACCESS_DENIED,
    classify,
    error_code,
    literal,
    open_connection,
)
from .connection import Connection
from .credentials import CredentialSource, ResolvedCredentials
from .errors import (
    AccessDeniedError,
    AuthenticationFailedError,
    ConfigurationError,
    CredentialsAbsentError,
    CredentialsUnobtainableError,
    DatabaseUnreachableError,
    MissingDependencyError,
)
from .identifiers import quote_identifier, validate_user_name
from .server import ServerInfo, detect_server, grantee
from .state import ConnectionState
from .versions import SchemaVersion


@dataclass(frozen=True, slots=True)
class Survey:
    """What the administrator can see about one database."""

    server: ServerInfo
    database_exists: bool
    table_count: int
    size_bytes: int
    is_wordpress: bool
    schema_version: SchemaVersion | None
    user_exists: bool | None
    user_privileges: frozenset[str] | None


def _resolve(source: CredentialSource) -> ResolvedCredentials:
    return source.resolve()


def _connect_or_raise(
    connection: Connection, credentials: ResolvedCredentials, database: str | None
) -> Any:
    """Open a session, or raise a package error saying why it could not be."""
    try:
        return open_connection(connection, credentials, database=database)
    except pymysql.err.MySQLError as exc:
        if classify(exc) is ConnectionState.AUTHENTICATION_FAILED:
            msg = f"the account {credentials.username!r} was rejected"
            raise AuthenticationFailedError(msg) from exc
        msg = f"{connection.host}:{connection.port} could not be reached"
        raise DatabaseUnreachableError(msg) from exc


def _admin_session(connection: Connection, admin: ResolvedCredentials) -> Any:
    """An admin connection with no default database, or a package error."""
    return _connect_or_raise(connection, admin, None)


def _as_package_error(exc: pymysql.err.MySQLError) -> Exception:
    """Translate a server error raised mid-session into a package-owned one."""
    if error_code(exc) in (ER_TABLEACCESS_DENIED, ER_DBACCESS_DENIED):
        return AccessDeniedError(f"the administrator lacks a privilege the survey needs: {exc}")
    return DatabaseUnreachableError(f"the server failed during the survey: {exc}")


def _read_schema_version(cursor: Any, database: str, table_prefix: str) -> SchemaVersion | None:
    table = f"{quote_identifier(database)}.{quote_identifier(table_prefix + 'options')}"
    cursor.execute(
        f"SELECT option_value FROM {literal(table)} WHERE option_name = %s",  # noqa: S608 - quoted identifiers
        ("db_version",),
    )
    row = cursor.fetchone()
    if row is None or row[0] is None:
        return None
    try:
        return SchemaVersion(int(row[0]))
    except (TypeError, ValueError) as exc:
        msg = f"db_version {row[0]!r} in {table} is not an integer"
        raise AccessDeniedError(msg) from exc


def survey(
    connection: Connection,
    admin: CredentialSource,
    *,
    wordpress_user: str | None = None,
    user_host: str = "%",
    table_prefix: str = "wp_",
) -> Survey:
    """Everything the administrator can see about this database and account."""
    with operation("survey", connection) as fields:
        session = _admin_session(connection, _resolve(admin))
        database = connection.database
        try:
            with session, session.cursor() as cur:
                server = detect_server(cur)
                cur.execute(
                    "SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s",
                    (database,),
                )
                exists = int(cur.fetchone()[0]) > 0
                cur.execute(
                    "SELECT COUNT(*), COALESCE(SUM(DATA_LENGTH + INDEX_LENGTH), 0) "
                    "FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s",
                    (database,),
                )
                table_count, size_bytes = (int(v) for v in cur.fetchone())
                cur.execute(
                    "SELECT COUNT(*) FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
                    (database, f"{table_prefix}options"),
                )
                is_wordpress = int(cur.fetchone()[0]) > 0
                version = (
                    _read_schema_version(cur, database, table_prefix) if is_wordpress else None
                )

                user_exists: bool | None = None
                user_privileges: frozenset[str] | None = None
                if wordpress_user is not None:
                    validate_user_name(wordpress_user)
                    try:
                        cur.execute(
                            "SELECT COUNT(*) FROM mysql.user WHERE User = %s AND Host = %s",
                            (wordpress_user, user_host),
                        )
                        user_exists = int(cur.fetchone()[0]) > 0
                    except pymysql.err.MySQLError as exc:
                        if error_code(exc) != ER_TABLEACCESS_DENIED:
                            raise
                    cur.execute(
                        "SELECT PRIVILEGE_TYPE FROM information_schema.SCHEMA_PRIVILEGES "
                        "WHERE GRANTEE = %s AND %s LIKE TABLE_SCHEMA",
                        (grantee(wordpress_user, user_host), database),
                    )
                    user_privileges = frozenset(str(r[0]) for r in cur.fetchall())
        except pymysql.err.MySQLError as exc:
            raise _as_package_error(exc) from exc
        fields.update(database_exists=exists, table_count=table_count, is_wordpress=is_wordpress)
        return Survey(
            server,
            exists,
            table_count,
            size_bytes,
            is_wordpress,
            version,
            user_exists,
            user_privileges,
        )


def inspect(connection: Connection, credentials: CredentialSource) -> ConnectionState:
    """Whether this account can use this database, and if not, why."""
    with operation("inspect", connection) as fields:
        try:
            resolved = _resolve(credentials)
        except (
            CredentialsUnobtainableError,
            CredentialsAbsentError,
            ConfigurationError,
            MissingDependencyError,
        ):
            fields["state"] = str(ConnectionState.CREDENTIALS_UNOBTAINABLE)
            return ConnectionState.CREDENTIALS_UNOBTAINABLE
        try:
            session = open_connection(connection, resolved, database=connection.database)
        except pymysql.err.MySQLError as exc:
            state = classify(exc)
        else:
            session.close()
            state = ConnectionState.READY
        fields["state"] = str(state)
        return state


def schema_version(
    connection: Connection, credentials: CredentialSource, table_prefix: str = "wp_"
) -> SchemaVersion | None:
    """The WordPress schema revision recorded in the options table."""
    with operation("schema_version", connection):
        resolved = _resolve(credentials)
        session = _connect_or_raise(connection, resolved, connection.database)
        try:
            with session, session.cursor() as cur:
                return _read_schema_version(cur, connection.database, table_prefix)
        except pymysql.err.MySQLError as exc:
            msg = f"could not read {table_prefix}options; is the table prefix correct?"
            raise AccessDeniedError(msg) from exc
