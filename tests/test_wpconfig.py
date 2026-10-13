"""WpConfigFile: a site's wp-config.php as credential source and location.

Skipped when the ``wpconfig`` extra is absent, which is the point of the extra.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("l3io.wp.config", reason="the wpconfig extra is not installed")

from l3io.wp.database import DEFAULT_TABLE_PREFIX
from l3io.wp.database.connection import Connection
from l3io.wp.database.credentials import CredentialSource
from l3io.wp.database.errors import (
    ConfigUnreadableError,
    CredentialsAbsentError,
    MissingConfigValueError,
)
from l3io.wp.database.wpconfig import WpConfigFile

CONFIG = """<?php
define('DB_NAME', 'wp_site');
define('DB_USER', 'wpuser');
define('DB_PASSWORD', 'wp-pass');
define('DB_HOST', '127.0.0.1:3307');
$table_prefix = 'custom_';
"""


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "wp-config.php"
    path.write_text(body, encoding="utf-8")
    return path


def test_resolves_credentials_and_connection(tmp_path: Path) -> None:
    path = write(tmp_path, CONFIG)
    source = WpConfigFile(path)
    assert isinstance(source, CredentialSource)
    resolved = source.resolve()
    assert (resolved.username, resolved.password) == ("wpuser", "wp-pass")
    assert resolved.source == f"wp-config:{path}"
    assert source.connection() == Connection(host="127.0.0.1", database="wp_site", port=3307)


def test_table_prefix_comes_from_the_variable_namespace(tmp_path: Path) -> None:
    """$table_prefix is a PHP variable, so get() cannot see it."""
    assert WpConfigFile(write(tmp_path, CONFIG)).table_prefix == "custom_"


def test_table_prefix_falls_back_to_the_wordpress_default(tmp_path: Path) -> None:
    body = CONFIG.replace("$table_prefix = 'custom_';\n", "")
    assert WpConfigFile(write(tmp_path, body)).table_prefix == DEFAULT_TABLE_PREFIX


def test_no_credentials_defined_is_absent(tmp_path: Path) -> None:
    with pytest.raises(CredentialsAbsentError):
        WpConfigFile(write(tmp_path, "<?php\ndefine('DB_NAME', 'wp');\n")).resolve()


@pytest.mark.parametrize(
    ("defined", "missing"), [("DB_USER", "DB_PASSWORD"), ("DB_PASSWORD", "DB_USER")]
)
def test_half_defined_credentials_name_the_missing_one(
    tmp_path: Path, defined: str, missing: str
) -> None:
    body = f"<?php\ndefine('{defined}', 'x');\n"
    with pytest.raises(MissingConfigValueError, match=missing):
        WpConfigFile(write(tmp_path, body)).resolve()


@pytest.mark.parametrize("key", ["DB_HOST", "DB_NAME"])
def test_a_missing_location_setting_names_itself(tmp_path: Path, key: str) -> None:
    body = "\n".join(line for line in CONFIG.splitlines() if key not in line)
    with pytest.raises(MissingConfigValueError) as caught:
        WpConfigFile(write(tmp_path, body)).connection()
    assert caught.value.key == key


def test_an_empty_password_is_present_not_absent(tmp_path: Path) -> None:
    """MISSING is falsy and so is ''; an empty password is a configured value."""
    body = CONFIG.replace("define('DB_PASSWORD', 'wp-pass');", "define('DB_PASSWORD', '');")
    resolved = WpConfigFile(write(tmp_path, body)).resolve()
    assert (resolved.username, resolved.password) == ("wpuser", "")


def test_a_quoted_numeric_password_stays_text(tmp_path: Path) -> None:
    body = CONFIG.replace("define('DB_PASSWORD', 'wp-pass');", "define('DB_PASSWORD', '3306');")
    resolved = WpConfigFile(write(tmp_path, body)).resolve()
    assert resolved.password == "3306"
    assert isinstance(resolved.password, str)


def test_an_unreadable_file_raises_our_error_not_the_stdlib_one(tmp_path: Path) -> None:
    """AD-14: no dependency's exception type crosses this boundary."""
    with pytest.raises(ConfigUnreadableError):
        WpConfigFile(tmp_path / "does-not-exist.php")
