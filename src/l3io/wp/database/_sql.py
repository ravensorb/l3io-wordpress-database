"""Opening a server connection and classifying driver errors. Internal."""

from __future__ import annotations

import pymysql

from .connection import Connection
from .credentials import ResolvedCredentials
from .state import ConnectionState

CONNECT_TIMEOUT_SECONDS = 10

ER_DBACCESS_DENIED = 1044
ER_ACCESS_DENIED = 1045
ER_BAD_DB = 1049
ER_NONEXISTING_GRANT = 1141
ER_TABLEACCESS_DENIED = 1142


def open_connection(
    connection: Connection, credentials: ResolvedCredentials, *, database: str | None
) -> pymysql.connections.Connection:
    """Open a connection. Credentials are call arguments, never a URI."""
    return pymysql.connect(
        host=connection.host,
        port=connection.port,
        user=credentials.username,
        password=credentials.password,
        database=database,
        connect_timeout=CONNECT_TIMEOUT_SECONDS,
        autocommit=False,
    )


def error_code(exc: pymysql.err.MySQLError) -> int | None:
    """The server error number, when the driver reports one."""
    code = exc.args[0] if exc.args else None
    return code if isinstance(code, int) else None


def classify(exc: pymysql.err.MySQLError) -> ConnectionState:
    """Map a connection failure onto a :class:`ConnectionState`."""
    code = error_code(exc)
    if code == ER_ACCESS_DENIED:
        return ConnectionState.AUTHENTICATION_FAILED
    if code == ER_DBACCESS_DENIED:
        return ConnectionState.ACCESS_DENIED
    if code == ER_BAD_DB:
        return ConnectionState.DATABASE_ABSENT
    return ConnectionState.UNREACHABLE
