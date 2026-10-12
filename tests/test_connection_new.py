# tests/test_connection_new.py
from __future__ import annotations

import pytest

from l3io.wp.database.connection import Connection
from l3io.wp.database.errors import InvalidArgumentsError, InvalidDatabaseNameError


def test_from_db_host_parses_port() -> None:
    assert Connection.from_db_host("db.example:3307", "wp_site") == Connection(
        host="db.example", database="wp_site", port=3307
    )


def test_from_db_host_defaults_port() -> None:
    assert Connection.from_db_host("db", "wp").port == 3306


@pytest.mark.parametrize("db_host", ["", "db:notaport"])
def test_bad_db_host(db_host: str) -> None:
    with pytest.raises(InvalidArgumentsError):
        Connection.from_db_host(db_host, "wp")


@pytest.mark.parametrize("port", [0, 65536])
def test_bad_port(port: int) -> None:
    with pytest.raises(InvalidArgumentsError):
        Connection(host="db", database="wp", port=port)


def test_bad_database_name() -> None:
    with pytest.raises(InvalidDatabaseNameError):
        Connection(host="db", database="wp.site")


def test_carries_no_credentials() -> None:
    assert not hasattr(Connection(host="db", database="wp"), "credentials")
