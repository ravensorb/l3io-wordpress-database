# tests/test_wpconfig_file.py
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("l3io.wp.config")

from l3io.wp.database.connection import Connection
from l3io.wp.database.credentials import CredentialSource
from l3io.wp.database.errors import CredentialsAbsentError, MissingConfigValueError
from l3io.wp.database.wpconfig import WpConfigFile


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "wp-config.php"
    path.write_text("<?php\n" + body, encoding="utf-8")
    return path


def test_resolves_credentials_and_connection(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "define('DB_NAME', 'wp_site');\ndefine('DB_USER', 'wpuser');\n"
        "define('DB_PASSWORD', 'pw');\ndefine('DB_HOST', 'db:3307');\n"
        "$table_prefix = 'xy_';\n",
    )
    source = WpConfigFile(path)
    assert isinstance(source, CredentialSource)
    resolved = source.resolve()
    assert (resolved.username, resolved.password) == ("wpuser", "pw")
    assert resolved.source == f"wp-config:{path}"
    assert source.connection() == Connection(host="db", database="wp_site", port=3307)
    assert source.table_prefix == "xy_"


def test_no_credentials_defined_is_absent(tmp_path: Path) -> None:
    with pytest.raises(CredentialsAbsentError):
        WpConfigFile(write(tmp_path, "define('DB_NAME', 'wp');\n")).resolve()


def test_half_defined_is_a_failure(tmp_path: Path) -> None:
    with pytest.raises(MissingConfigValueError, match="DB_PASSWORD"):
        WpConfigFile(write(tmp_path, "define('DB_USER', 'u');\n")).resolve()


def test_default_prefix(tmp_path: Path) -> None:
    assert WpConfigFile(write(tmp_path, "define('DB_USER', 'u');\n")).table_prefix == "wp_"
