"""Client tools: versions, option files, argument vectors, environment."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from l3io.wp.database import _client
from l3io.wp.database._client import ClientTool, parse_client_version
from l3io.wp.database.connection import Connection
from l3io.wp.database.credentials import ResolvedCredentials
from l3io.wp.database.errors import InvalidArgumentsError
from l3io.wp.database.server import ServerFamily

CONN = Connection(host="db.example", database="wp_site", port=3307)
SECRET = "p#a;s\"s\\w'o rd)"


@pytest.mark.parametrize(
    ("text", "family", "version"),
    [
        (
            "mysqldump  Ver 8.4.11 for Linux on x86_64 (MySQL Community Server - GPL)",
            ServerFamily.MYSQL,
            (8, 4, 11),
        ),
        (
            "mysql  Ver 8.0.46-0ubuntu0.24.04.4 for Linux on x86_64 ((Ubuntu))",
            ServerFamily.MYSQL,
            (8, 0, 46),
        ),
        (
            "mysqldump  Ver 10.19 Distrib 10.2.44-MariaDB, for debian-linux-gnu (x86_64)",
            ServerFamily.MARIADB,
            (10, 2, 44),
        ),
        (
            "mysql  Ver 15.1 Distrib 10.2.44-MariaDB, for debian-linux-gnu (x86_64)",
            ServerFamily.MARIADB,
            (10, 2, 44),
        ),
        (
            "mariadb-dump from 11.4.13-MariaDB, client 10.19 for debian-linux-gnu (x86_64)",
            ServerFamily.MARIADB,
            (11, 4, 13),
        ),
    ],
)
def test_parse_client_version(
    text: str, family: ServerFamily, version: tuple[int, int, int]
) -> None:
    tool = parse_client_version("tool", "/usr/bin/tool", text)
    assert (tool.family, tool.version) == (family, version)


def test_unrecognised_version_is_rejected() -> None:
    with pytest.raises(ValueError, match="version"):
        parse_client_version("tool", "/x", "something else")


@pytest.mark.parametrize(
    ("family", "version", "expected"),
    [
        (ServerFamily.MYSQL, (8, 0, 46), True),
        (ServerFamily.MARIADB, (10, 2, 44), False),
        (ServerFamily.MARIADB, (10, 6, 17), False),
        (ServerFamily.MARIADB, (10, 6, 18), True),
        (ServerFamily.MARIADB, (11, 4, 13), True),
        (ServerFamily.MARIADB, (11, 8, 0), True),
        (ServerFamily.MARIADB, (11, 3, 9), False),
    ],
)
def test_sandbox_line_support(
    family: ServerFamily, version: tuple[int, int, int], expected: bool
) -> None:
    tool = ClientTool("t", "/t", family, version, "t")
    assert tool.understands_sandbox_line is expected


def test_option_values_are_quoted_and_escaped() -> None:
    text = _client.option_file_text(ResolvedCredentials("wp user", SECRET), CONN)
    assert text.splitlines() == [
        "[client]",
        'user="wp user"',
        'password="p#a;s\\"s\\\\w\'o rd)"',
        'host="db.example"',
        "port=3307",
        "protocol=TCP",
    ]


def test_a_nul_in_a_value_is_rejected() -> None:
    with pytest.raises(InvalidArgumentsError):
        _client.option_file_text(ResolvedCredentials("u", "a\x00b"), CONN)


LONG = "A" * 4084 + "plugin-dir=/tmp/evil#"


@pytest.mark.parametrize(
    ("field", "credentials", "connection"),
    [
        ("user", ResolvedCredentials(LONG, "pw"), CONN),
        ("password", ResolvedCredentials("u", LONG), CONN),
        ("host", ResolvedCredentials("u", "pw"), Connection(host=LONG, database="wp_site")),
    ],
)
def test_a_value_long_enough_to_split_an_option_line_is_rejected(
    field: str, credentials: ResolvedCredentials, connection: Connection
) -> None:
    """MariaDB reads a line longer than its buffer as two, so the tail becomes an option."""
    with pytest.raises(InvalidArgumentsError) as caught:
        _client.option_file_text(credentials, connection)
    assert field in str(caught.value)
    assert "1024" in str(caught.value)
    assert "plugin-dir" not in str(caught.value)
    assert "A" * 64 not in str(caught.value)


def test_the_length_cap_counts_the_escaped_utf8_bytes() -> None:
    _client.option_file_text(ResolvedCredentials("u", "a" * 1024), CONN)
    for over in ("a" * 1025, "\\" * 513, "é" * 513):
        with pytest.raises(InvalidArgumentsError):
            _client.option_file_text(ResolvedCredentials("u", over), CONN)


def test_a_value_that_is_not_utf8_is_rejected_without_chaining_the_secret() -> None:
    secret = b"hunter2\xff".decode("utf-8", "surrogateescape")
    with pytest.raises(InvalidArgumentsError) as caught:
        _client.option_file_text(ResolvedCredentials("u", secret), CONN)
    assert "password" in str(caught.value)
    assert "hunter2" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_option_pipe_is_readable_once_and_closed_after() -> None:
    with _client.option_pipe(ResolvedCredentials("u", SECRET), CONN) as fd:
        data = os.read(fd, 65536).decode()
    assert "protocol=TCP" in data
    with pytest.raises(OSError):
        os.fstat(fd)


def test_child_env_holds_no_secret_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("MYSQL_PWD", "MYSQL_HOST", "HOME", "MYSQL_TCP_PORT"):
        monkeypatch.setenv(name, "inherited")
    env = _client.child_env()
    assert set(env) == {"PATH", "LANG", "LC_ALL", "MYSQL_TEST_LOGIN_FILE"}
    assert not Path(env["MYSQL_TEST_LOGIN_FILE"]).exists()


def test_argv_puts_the_defaults_file_first() -> None:
    mysql84 = ClientTool("mysqldump", "/usr/bin/mysqldump", ServerFamily.MYSQL, (8, 4, 11), "v")
    mysql80 = ClientTool("mysqldump", "/usr/bin/mysqldump", ServerFamily.MYSQL, (8, 0, 46), "v")
    maria = ClientTool(
        "mariadb-dump", "/usr/bin/mariadb-dump", ServerFamily.MARIADB, (11, 4, 13), "v"
    )
    assert _client.argv(mysql84, 7, ["x"]) == [
        "/usr/bin/mysqldump",
        "--defaults-file=/dev/fd/7",
        "--no-login-paths",
        "x",
    ]
    assert "--no-login-paths" not in _client.argv(mysql80, 7, [])
    assert "--no-login-paths" not in _client.argv(maria, 7, [])


def test_dump_args() -> None:
    mysql = ClientTool("mysqldump", "/m", ServerFamily.MYSQL, (8, 4, 11), "v")
    maria = ClientTool("mariadb-dump", "/m", ServerFamily.MARIADB, (11, 4, 13), "v")
    base = [
        "--single-transaction",
        "--quick",
        "--hex-blob",
        "--default-character-set=utf8mb4",
        "--no-tablespaces",
    ]
    assert _client.dump_args(mysql, "wp_site", ["--routines"]) == [
        *base,
        "--set-gtid-purged=OFF",
        "--routines",
        "wp_site",
    ]
    assert _client.dump_args(maria, "wp_site", []) == [*base, "wp_site"]


def test_load_args() -> None:
    assert _client.load_args("wp_stage", []) == [
        "--default-character-set=utf8mb4",
        "--database=wp_stage",
    ]


@pytest.mark.parametrize(
    ("options", "allowed", "bad"),
    [
        (["--routines", "--ignore-table=wp.t"], _client.DUMP_OPTIONS, []),
        (
            ["--defaults-extra-file=/x", "--host=evil", "--result-file=/tmp/x"],
            _client.DUMP_OPTIONS,
            ["--defaults-extra-file=/x", "--host=evil", "--result-file=/tmp/x"],
        ),
        (["--binary-mode"], _client.LOAD_OPTIONS, []),
        (["--force"], _client.LOAD_OPTIONS, ["--force"]),
    ],
)
def test_option_allow_list(options: list[str], allowed: frozenset[str], bad: list[str]) -> None:
    assert _client.disallowed_options(options, allowed) == bad


def test_find_tool_prefers_the_servers_family(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, text in [
        ("mariadb-dump", "mariadb-dump from 11.4.13-MariaDB, client 10.19"),
        ("mysqldump", "mysqldump  Ver 8.4.11 for Linux"),
    ]:
        script = tmp_path / name
        script.write_text(f"#!/bin/sh\necho '{text}'\n")
        script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    found = _client.find_tool(_client.PURPOSE_DUMP, ServerFamily.MARIADB)
    assert found is not None and found.name == "mariadb-dump"
    found = _client.find_tool(_client.PURPOSE_DUMP, ServerFamily.MYSQL)
    assert found is not None and found.name == "mysqldump"


def test_find_tool_returns_none_when_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    assert _client.find_tool(_client.PURPOSE_LOAD, ServerFamily.MYSQL) is None
