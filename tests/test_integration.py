"""Tests against a real database server.

Skipped unless ``DB_HOST`` is set. CI provides MySQL 8.0, MySQL 8.4 and MariaDB
as service containers; locally, point the env vars at any of them.

MySQL 8.0 is carried deliberately: it is the only server where
``mysql_native_password`` is still active, so it is the only row that exercises
the auth-plugin divergence the matrix exists for.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pymysql
import pytest

from l3io.wp.database import (
    ConnectionState,
    WpConnection,
    WpCredentials,
    WpDatabase,
)
from l3io.wp.database.errors import RefusedError
from l3io.wp.database.provision import check_ensure, ensure
from l3io.wp.database.verdict import Code

pytestmark = pytest.mark.skipif(
    not os.environ.get("DB_HOST"), reason="DB_HOST not set; integration tests skipped"
)

HOST = os.environ.get("DB_HOST", "127.0.0.1")
PORT = int(os.environ.get("DB_PORT", "3306"))
ADMIN_USER = os.environ.get("DB_ADMIN_USER", "root")
ADMIN_PASSWORD = os.environ.get("DB_ADMIN_PASSWORD", "rootpw")


def admin() -> WpCredentials:
    return WpCredentials.from_username_and_password(ADMIN_USER, ADMIN_PASSWORD)


def admin_sql(*statements: str) -> None:
    conn = pymysql.connect(
        host=HOST, port=PORT, user=ADMIN_USER, password=ADMIN_PASSWORD, connect_timeout=10
    )
    with conn, conn.cursor() as cur:
        for statement in statements:
            cur.execute(statement)
        conn.commit()


@pytest.fixture
def suffix() -> Iterator[str]:
    """A unique suffix so parallel runs and reruns cannot collide."""
    token = uuid.uuid4().hex[:8]
    yield token
    names = [f"wp_{token}", f"wpX{token}", f"other_{token}"]
    admin_sql(
        *[f"DROP DATABASE IF EXISTS `{n}`" for n in names],
        f"DROP USER IF EXISTS 'u_{token}'@'%'",
    )


def site(suffix: str, password: str = "wp-pass") -> WpDatabase:
    creds = WpCredentials.from_username_and_password(f"u_{suffix}", password)
    return WpDatabase(
        WpConnection(host=HOST, port=PORT, database=f"wp_{suffix}", credentials=creds)
    )


def test_fresh_site_reports_authentication_failure_not_absence(suffix: str) -> None:
    """Authentication precedes database resolution on the server.

    With neither the account nor the database present, the server returns 1045
    and never reaches the database, so DATABASE_ABSENT is simply not observable
    from the WordPress account yet. Verified against MySQL 8.0. This is the
    concrete reason the administrator must be the authority on what exists.
    """
    state = site(suffix).inspect()
    assert state is ConnectionState.AUTHENTICATION_FAILED
    assert state.needs_provisioning


def test_absent_database_is_distinguished_once_the_account_exists(suffix: str) -> None:
    """1049 is reachable only after authentication succeeds."""
    admin_sql(
        f"CREATE USER 'u_{suffix}'@'%' IDENTIFIED BY 'wp-pass'",
        f"GRANT ALL PRIVILEGES ON `wp\\_{suffix}`.* TO 'u_{suffix}'@'%'",
    )
    state = site(suffix).inspect()
    assert state is ConnectionState.DATABASE_ABSENT
    assert state.needs_provisioning


def test_ensure_provisions_from_nothing(suffix: str) -> None:
    result = site(suffix).ensure(admin())
    assert result.ok
    assert result.changed
    assert result.state is ConnectionState.READY


def test_second_ensure_changes_nothing_and_writes_nothing(suffix: str) -> None:
    """FR-7 idempotence, stated as convergence rather than as a no-op promise."""
    db = site(suffix)
    db.ensure(admin())
    again = db.ensure(admin())
    assert again.ok
    assert not again.changed
    assert again.actions == ()


def test_database_present_but_user_absent_still_provisions(suffix: str) -> None:
    """The `wp db create` / MYSQL_DATABASE case.

    Inspecting as the WordPress account fails here, because that account does
    not exist yet. Treating that failure as a refusal to provision would reject
    the most common input this package serves.
    """
    admin_sql(f"CREATE DATABASE `wp_{suffix}`")
    db = site(suffix)
    assert db.inspect() is ConnectionState.AUTHENTICATION_FAILED
    assert db.inspect().needs_provisioning
    result = db.ensure(admin())
    assert result.ok


def test_rotated_config_password_is_converged(suffix: str) -> None:
    """wp-config.php is the desired state; the server is converged onto it."""
    site(suffix).ensure(admin())
    rotated = site(suffix, password="a-different-password")
    assert rotated.inspect() is ConnectionState.AUTHENTICATION_FAILED
    result = rotated.ensure(admin())
    assert result.ok
    assert any("set password" in action for action in result.actions)


def test_wrong_password_is_authentication_failure_not_absence(suffix: str) -> None:
    site(suffix).ensure(admin())
    wrong = site(suffix, password="not-the-password")
    assert wrong.inspect() is ConnectionState.AUTHENTICATION_FAILED


def test_unreachable_server_is_distinguished(suffix: str) -> None:
    creds = WpCredentials.from_username_and_password("nobody", "nothing")
    db = WpDatabase(
        WpConnection(host="127.0.0.1", port=1, database="wp_nowhere", credentials=creds)
    )
    assert db.inspect() is ConnectionState.UNREACHABLE
    assert db.inspect().blocks_provisioning


def test_ad28_grant_does_not_reach_a_name_matching_the_unescaped_pattern(
    suffix: str,
) -> None:
    """AD-28 regression. This is the shape that proves the escaping works.

    `wp_<suffix>` unescaped is a LIKE pattern in which `_` matches any single
    character, so a grant on it would also cover `wpX<suffix>`. The assertion is
    that the neighbouring database is *unreachable*, not merely that the SQL
    text looks escaped.
    """
    admin_sql(f"CREATE DATABASE `wpX{suffix}`")
    result = site(suffix).ensure(admin())
    assert result.ok

    neighbour = pymysql.connect(
        host=HOST,
        port=PORT,
        user=f"u_{suffix}",
        password="wp-pass",
        connect_timeout=10,
    )
    with neighbour, neighbour.cursor() as cur:
        cur.execute("SHOW DATABASES")
        visible = {row[0] for row in cur.fetchall()}

    assert f"wp_{suffix}" in visible, "the granted database should be visible"
    assert f"wpX{suffix}" not in visible, (
        f"AD-28 violated: wpX{suffix} matches the unescaped pattern wp_{suffix} "
        "and is reachable by an account granted only on the latter"
    )

    with pytest.raises(pymysql.err.MySQLError):
        conn = pymysql.connect(
            host=HOST,
            port=PORT,
            user=f"u_{suffix}",
            password="wp-pass",
            database=f"wpX{suffix}",
            connect_timeout=10,
        )
        conn.close()


def test_database_version_honours_a_custom_table_prefix(suffix: str) -> None:
    """The original hardcoded `wp_options`, so it failed on any prefixed site.

    WordPress's $table_prefix is configurable and frequently changed, so
    reading the version from a fixed table name broke on exactly the installs
    that most need inspecting.
    """
    site(suffix).ensure(admin())
    prefix = "custom_"
    admin_sql(
        f"CREATE TABLE `wp_{suffix}`.`{prefix}options` "  # noqa: S608 - test fixture, generated name
        "(option_name VARCHAR(191) PRIMARY KEY, option_value LONGTEXT)",
        f"INSERT INTO `wp_{suffix}`.`{prefix}options` (option_name, option_value) "  # noqa: S608
        "VALUES ('db_version', '58975')",
    )
    version = site(suffix).database_version(table_prefix=prefix)
    assert version is not None
    assert version.db_version == 58975
    # 6.7 introduced this schema and 6.8 still reports it, so the answer names
    # the INTRODUCING release -- the mapping is many-to-one by nature.
    assert version.release == "6.7"
    assert not version.is_newer_than_known


def test_database_version_is_none_when_no_row_exists(suffix: str) -> None:
    site(suffix).ensure(admin())
    admin_sql(
        f"CREATE TABLE `wp_{suffix}`.`wp_options` "  # noqa: S608 - test fixture
        "(option_name VARCHAR(191) PRIMARY KEY, option_value LONGTEXT)"
    )
    assert site(suffix).database_version() is None


def test_a_wrong_table_prefix_is_reported_not_silently_empty(suffix: str) -> None:
    """A missing options table means the prefix is wrong, which is worth saying."""
    from l3io.wp.database.errors import AccessDeniedError

    site(suffix).ensure(admin())
    with pytest.raises(AccessDeniedError) as caught:
        site(suffix).database_version(table_prefix="definitely_not_")
    assert "table prefix" in str(caught.value)


def test_no_credential_appears_in_logs_during_real_provisioning(suffix: str) -> None:
    """The provisioning path is the one that logs an action list.

    Unit coverage coaxes credentials through inspect(); this covers the path
    that actually emits `actions=[...]`, including the ALTER USER step whose
    action text names the account whose password was just set.
    """
    import structlog

    secret = "integration-only-secret-value"
    db = site(suffix, password=secret)
    with structlog.testing.capture_logs() as captured:
        result = db.ensure(admin())
    assert result.ok
    rendered = repr(captured)
    assert secret not in rendered, f"a log event carried the password: {rendered}"
    # The action list should name what happened without quoting the value.
    assert any("set password" in action for action in result.actions)
    assert all(secret not in action for action in result.actions)


# --- new API (plan 1, task 9) ---------------------------------------------------
from l3io.wp.database.connection import Connection  # noqa: E402
from l3io.wp.database.credentials import Explicit  # noqa: E402
from l3io.wp.database.inspection import schema_version, survey  # noqa: E402
from l3io.wp.database.server import ServerFamily  # noqa: E402


def new_admin() -> Explicit:
    return Explicit(ADMIN_USER, ADMIN_PASSWORD)


def test_survey_of_an_absent_database(suffix: str) -> None:
    result = survey(Connection(host=HOST, port=PORT, database=f"wp_{suffix}"), new_admin())
    assert result.database_exists is False
    assert result.table_count == 0
    assert result.is_wordpress is False
    assert result.server.family in (ServerFamily.MYSQL, ServerFamily.MARIADB)


def test_survey_of_a_wordpress_database(suffix: str) -> None:
    name = f"wp_{suffix}"
    admin_sql(
        f"CREATE DATABASE `{name}`",
        f"CREATE TABLE `{name}`.`xy_options` (option_name VARCHAR(191), option_value LONGTEXT)",
        f"INSERT INTO `{name}`.`xy_options` VALUES ('db_version', '58975')",  # noqa: S608 - test fixture
        f"CREATE USER 'u_{suffix}'@'%' IDENTIFIED BY 'p'",
        f"GRANT SELECT ON `{name}`.* TO 'u_{suffix}'@'%'",
    )
    result = survey(
        Connection(host=HOST, port=PORT, database=name),
        new_admin(),
        wordpress_user=f"u_{suffix}",
        table_prefix="xy_",
    )
    assert result.database_exists and result.table_count == 1 and result.is_wordpress
    assert result.schema_version is not None and result.schema_version.release == "6.7"
    assert result.user_exists is True
    assert result.user_privileges == frozenset({"SELECT"})


def test_schema_version_with_custom_prefix_via_new_api(suffix: str) -> None:
    name = f"wp_{suffix}"
    admin_sql(
        f"CREATE DATABASE `{name}`",
        f"CREATE TABLE `{name}`.`xy_options` (option_name VARCHAR(191), option_value LONGTEXT)",
        f"INSERT INTO `{name}`.`xy_options` VALUES ('db_version', '58975')",  # noqa: S608 - test fixture
    )
    version = schema_version(Connection(host=HOST, port=PORT, database=name), new_admin(), "xy_")
    assert version is not None and version.release == "6.7"


def test_schema_version_with_wrong_password_is_an_authentication_failure(suffix: str) -> None:
    from l3io.wp.database.errors import AuthenticationFailedError

    name = f"wp_{suffix}"
    admin_sql(
        f"CREATE DATABASE `{name}`",
        f"CREATE USER 'u_{suffix}'@'%' IDENTIFIED BY 'right'",
        f"GRANT SELECT ON `{name}`.* TO 'u_{suffix}'@'%'",
    )
    with pytest.raises(AuthenticationFailedError):
        schema_version(
            Connection(host=HOST, port=PORT, database=name), Explicit(f"u_{suffix}", "wrong")
        )


def test_survey_without_select_on_options_raises_access_denied(suffix: str) -> None:
    from l3io.wp.database.errors import AccessDeniedError

    name = f"wp_{suffix}"
    viewer = f"v_{suffix}"
    admin_sql(
        f"CREATE DATABASE `{name}`",
        f"CREATE TABLE `{name}`.`wp_options` (option_name VARCHAR(191), option_value LONGTEXT)",
        f"CREATE USER '{viewer}'@'%' IDENTIFIED BY 'p'",
        f"GRANT SHOW VIEW ON `{name}`.* TO '{viewer}'@'%'",
    )
    try:
        with pytest.raises(AccessDeniedError):
            survey(Connection(host=HOST, port=PORT, database=name), Explicit(viewer, "p"))
    finally:
        admin_sql(f"DROP USER IF EXISTS '{viewer}'@'%'")


def new_site(suffix: str) -> Connection:
    return Connection(host=HOST, port=PORT, database=f"wp_{suffix}")


def test_ensure_fresh_site_reports_what_it_created(suffix: str) -> None:
    result = ensure(new_site(suffix), new_admin(), Explicit(f"u_{suffix}", "wp-pass"))
    assert (result.created_database, result.created_user, result.password_set, result.granted) == (
        True,
        True,
        True,
        True,
    )


def test_second_ensure_changes_nothing_with_underscore_name(suffix: str) -> None:
    wp = Explicit(f"u_{suffix}", "wp-pass")
    ensure(new_site(suffix), new_admin(), wp)
    again = ensure(new_site(suffix), new_admin(), wp)
    assert not again.changed


def test_existing_database_without_user_is_not_reported_as_created(suffix: str) -> None:
    admin_sql(f"CREATE DATABASE `wp_{suffix}`")
    result = ensure(new_site(suffix), new_admin(), Explicit(f"u_{suffix}", "wp-pass"))
    assert result.created_database is False
    assert result.created_user is True


def test_wrong_password_is_reset_and_reported(suffix: str) -> None:
    ensure(new_site(suffix), new_admin(), Explicit(f"u_{suffix}", "first"))
    result = ensure(new_site(suffix), new_admin(), Explicit(f"u_{suffix}", "second"))
    assert (result.created_user, result.password_set, result.granted) == (False, True, False)


@pytest.mark.parametrize(
    "password", ["q'uo\"te", "back\\slash", "hash#semi;", "ab);cd", " spaced "]
)
def test_awkward_password_round_trips(suffix: str, password: str) -> None:
    ensure(new_site(suffix), new_admin(), Explicit(f"u_{suffix}", password))
    conn = pymysql.connect(
        host=HOST, port=PORT, user=f"u_{suffix}", password=password, database=f"wp_{suffix}"
    )
    conn.close()


def test_grant_does_not_reach_a_name_matching_the_unescaped_pattern(suffix: str) -> None:
    admin_sql(f"CREATE DATABASE `wpX{suffix}`")
    ensure(new_site(suffix), new_admin(), Explicit(f"u_{suffix}", "wp-pass"))
    conn = pymysql.connect(host=HOST, port=PORT, user=f"u_{suffix}", password="wp-pass")
    with conn, conn.cursor() as cur:
        cur.execute("SHOW DATABASES")
        visible = {r[0] for r in cur.fetchall()}
    assert f"wp_{suffix}" in visible
    assert f"wpX{suffix}" not in visible


def test_wrong_admin_password_is_a_coded_refusal(suffix: str) -> None:
    verdict = check_ensure(new_site(suffix), Explicit(ADMIN_USER, "wrong"), Explicit("u", "p"))
    assert verdict.codes == frozenset({Code.AUTHENTICATION_FAILED})
    with pytest.raises(RefusedError) as info:
        ensure(new_site(suffix), Explicit(ADMIN_USER, "wrong"), Explicit("u", "p"))
    assert info.value.verdict == verdict


def test_check_and_run_agree_on_unreachable() -> None:
    conn = Connection(host="127.0.0.1", port=1, database="wp_x")
    verdict = check_ensure(conn, new_admin(), Explicit("u", "p"))
    assert Code.UNREACHABLE in verdict.codes
