# tests/test_server.py
from __future__ import annotations

from typing import Any

import pymysql
import pytest

from l3io.wp.database._sql import classify
from l3io.wp.database.server import (
    Privileges,
    ServerFamily,
    account_privileges,
    grantee,
    parse_version,
)
from l3io.wp.database.state import ConnectionState


@pytest.mark.parametrize(
    ("text", "family", "version"),
    [
        ("8.4.11", ServerFamily.MYSQL, (8, 4, 11)),
        ("8.0.46", ServerFamily.MYSQL, (8, 0, 46)),
        ("9.7.2", ServerFamily.MYSQL, (9, 7, 2)),
        ("11.4.5-MariaDB-ubu2404", ServerFamily.MARIADB, (11, 4, 5)),
        ("10.2.44-MariaDB-1:10.2.44+maria~bionic", ServerFamily.MARIADB, (10, 2, 44)),
    ],
)
def test_parse_version(text: str, family: ServerFamily, version: tuple[int, int, int]) -> None:
    info = parse_version(text)
    assert (info.family, info.version, info.version_text) == (family, version, text)


@pytest.mark.parametrize(
    ("text", "supported", "eol"),
    [
        ("5.7.44", False, True),
        ("8.0.46", True, True),
        ("8.4.11", True, False),
        ("10.1.48-MariaDB", False, True),
        ("10.2.44-MariaDB", True, True),
        ("11.4.5-MariaDB", True, False),
    ],
)
def test_support_and_end_of_life(text: str, supported: bool, eol: bool) -> None:
    info = parse_version(text)
    assert (info.is_supported, info.is_end_of_life) == (supported, eol)


def test_unparseable_version_is_rejected() -> None:
    with pytest.raises(ValueError, match="version"):
        parse_version("not-a-version")


@pytest.mark.parametrize(
    ("code", "state"),
    [
        (1045, ConnectionState.AUTHENTICATION_FAILED),
        (1044, ConnectionState.ACCESS_DENIED),
        (1049, ConnectionState.DATABASE_ABSENT),
        (2003, ConnectionState.UNREACHABLE),
    ],
)
def test_classify(code: int, state: ConnectionState) -> None:
    assert classify(pymysql.err.OperationalError(code, "x")) is state


def test_grantee_format() -> None:
    assert grantee("wpuser", "%") == "'wpuser'@'%'"


class _Cursor:
    """A cursor that answers the queries account_privileges issues, in order."""

    def __init__(self, answers: list[Any]) -> None:
        self._answers = answers
        self.executed: list[tuple[str, Any]] = []

    def execute(self, sql: str, args: Any = None) -> None:
        self.executed.append((sql, args))
        self._current = self._answers.pop(0)

    def fetchone(self) -> Any:
        return self._current

    def fetchall(self) -> Any:
        return self._current


def test_account_privileges_merges_global_and_schema() -> None:
    cursor = _Cursor(
        [
            ("admin@%",),  # CURRENT_USER()
            ("NONE",),  # CURRENT_ROLE()
            [("CREATE USER", "YES"), ("SELECT", "YES")],  # USER_PRIVILEGES
            [("DROP", "NO")],  # SCHEMA_PRIVILEGES matching the database
        ]
    )
    privs = account_privileges(cursor, "wp_site")
    assert privs == Privileges(frozenset({"CREATE USER", "SELECT", "DROP"}), True, False)
    assert privs.has("GRANT OPTION")
    assert cursor.executed[2][1] == ("'admin'@'%'",)
    assert cursor.executed[3][1] == ("'admin'@'%'", "wp_site")


def test_role_makes_privileges_unverified() -> None:
    cursor = _Cursor([("admin@%",), ("`r_admin`@`%`",), [], []])
    assert account_privileges(cursor, "wp_site").unverified


def test_mariadb_null_role_is_no_role() -> None:
    cursor = _Cursor([("admin@localhost",), (None,), [], []])
    assert not account_privileges(cursor, "wp_site").unverified
