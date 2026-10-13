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
import structlog

from l3io.wp.database import ConnectionState, inspect
from l3io.wp.database.connection import Connection
from l3io.wp.database.credentials import Explicit
from l3io.wp.database.errors import AccessDeniedError, RefusedError
from l3io.wp.database.inspection import schema_version, survey
from l3io.wp.database.provision import (
    check_drop_database,
    check_drop_user,
    check_ensure,
    drop_database,
    drop_user,
    ensure,
    revoke,
    rotate_password,
)
from l3io.wp.database.server import ServerFamily
from l3io.wp.database.verdict import Code

pytestmark = pytest.mark.skipif(
    not os.environ.get("DB_HOST"), reason="DB_HOST not set; integration tests skipped"
)

HOST = os.environ.get("DB_HOST", "127.0.0.1")
PORT = int(os.environ.get("DB_PORT", "3306"))
ADMIN_USER = os.environ.get("DB_ADMIN_USER", "root")
ADMIN_PASSWORD = os.environ.get("DB_ADMIN_PASSWORD", "rootpw")


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
    names = [f"wp_{token}", f"wpX{token}", f"other_{token}", f"wp%{token}"]
    admin_sql(
        *[f"DROP DATABASE IF EXISTS `{n}`" for n in names],
        f"DROP USER IF EXISTS 'u_{token}'@'%'",
    )


def test_fresh_site_reports_authentication_failure_not_absence(suffix: str) -> None:
    """Authentication precedes database resolution on the server.

    With neither the account nor the database present, the server returns 1045
    and never reaches the database, so DATABASE_ABSENT is not observable from
    the WordPress account yet. This is why the administrator is the authority
    on what exists (AD-29).
    """
    state = inspect(new_site(suffix), Explicit(f"u_{suffix}", "wp-pass"))
    assert state is ConnectionState.AUTHENTICATION_FAILED
    assert state.needs_provisioning


def test_absent_database_is_distinguished_once_the_account_exists(suffix: str) -> None:
    """1049 is reachable only after authentication succeeds."""
    admin_sql(
        f"CREATE USER 'u_{suffix}'@'%' IDENTIFIED BY 'wp-pass'",
        f"GRANT ALL PRIVILEGES ON `wp\\_{suffix}`.* TO 'u_{suffix}'@'%'",
    )
    state = inspect(new_site(suffix), Explicit(f"u_{suffix}", "wp-pass"))
    assert state is ConnectionState.DATABASE_ABSENT
    assert state.needs_provisioning


def test_inspect_ready_after_ensure(suffix: str) -> None:
    wp = Explicit(f"u_{suffix}", "wp-pass")
    ensure(new_site(suffix), new_admin(), wp)
    assert inspect(new_site(suffix), wp) is ConnectionState.READY


def test_wrong_password_is_authentication_failure_not_absence(suffix: str) -> None:
    ensure(new_site(suffix), new_admin(), Explicit(f"u_{suffix}", "wp-pass"))
    state = inspect(new_site(suffix), Explicit(f"u_{suffix}", "not-the-password"))
    assert state is ConnectionState.AUTHENTICATION_FAILED


def test_unreachable_server_is_distinguished() -> None:
    conn = Connection(host="127.0.0.1", port=1, database="wp_nowhere")
    state = inspect(conn, Explicit("nobody", "nothing"))
    assert state is ConnectionState.UNREACHABLE
    assert state.blocks_provisioning


def test_ad28_neighbour_database_cannot_be_opened(suffix: str) -> None:
    """AD-28: wp_<s> unescaped matches wpX<s>; opening the neighbour must fail."""
    admin_sql(f"CREATE DATABASE `wpX{suffix}`")
    ensure(new_site(suffix), new_admin(), Explicit(f"u_{suffix}", "wp-pass"))
    with pytest.raises(pymysql.err.MySQLError):
        pymysql.connect(
            host=HOST,
            port=PORT,
            user=f"u_{suffix}",
            password="wp-pass",
            database=f"wpX{suffix}",
            connect_timeout=10,
        ).close()


def test_schema_version_is_none_when_no_row_exists(suffix: str) -> None:
    ensure(new_site(suffix), new_admin(), Explicit(f"u_{suffix}", "wp-pass"))
    admin_sql(
        f"CREATE TABLE `wp_{suffix}`.`wp_options` "  # noqa: S608 - test fixture
        "(option_name VARCHAR(191) PRIMARY KEY, option_value LONGTEXT)"
    )
    assert schema_version(new_site(suffix), Explicit(f"u_{suffix}", "wp-pass")) is None


def test_a_wrong_table_prefix_is_reported_not_silently_empty(suffix: str) -> None:
    """A missing options table means the prefix is wrong, which is worth saying."""
    wp = Explicit(f"u_{suffix}", "wp-pass")
    ensure(new_site(suffix), new_admin(), wp)
    with pytest.raises(AccessDeniedError) as caught:
        schema_version(new_site(suffix), wp, "definitely_not_")
    assert "table prefix" in str(caught.value)


def test_no_credential_appears_in_logs_during_real_provisioning(suffix: str) -> None:
    """The provisioning path, including CREATE USER and ALTER USER, logs cleanly."""
    secret = "integration-only-secret-value"
    with structlog.testing.capture_logs() as captured:
        created = ensure(new_site(suffix), new_admin(), Explicit(f"u_{suffix}", secret))
        rotated = ensure(new_site(suffix), new_admin(), Explicit(f"u_{suffix}", secret + "2"))
    assert created.created_user and rotated.password_set
    rendered = repr(captured)
    assert secret not in rendered, f"a log event carried the password: {rendered}"


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
    with pytest.raises(RefusedError) as info:
        ensure(conn, new_admin(), Explicit("u", "p"))
    assert info.value.verdict == verdict


_WP_PRIVS = "SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, ALTER, INDEX"


def test_admin_lacking_wordpress_privileges_is_refused_before_anything_runs(suffix: str) -> None:
    acct = f"a_{suffix}"
    admin_sql(
        f"CREATE USER '{acct}'@'%' IDENTIFIED BY 'ap'",
        f"GRANT CREATE, CREATE USER, SELECT ON *.* TO '{acct}'@'%' WITH GRANT OPTION",
    )
    try:
        limited = Explicit(acct, "ap")
        wp = Explicit(f"u_{suffix}", "wp-pass")
        verdict = check_ensure(new_site(suffix), limited, wp)
        assert not verdict.ok
        missing = {
            f.fields["privilege"] for f in verdict.findings if f.code is Code.MISSING_PRIVILEGE
        }
        assert missing == {"INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "INDEX"}
        with pytest.raises(RefusedError):
            ensure(new_site(suffix), limited, wp)
        assert not survey(new_site(suffix), new_admin()).database_exists
    finally:
        admin_sql(f"DROP USER IF EXISTS '{acct}'@'%'")


def test_admin_with_only_database_level_select_is_refused(suffix: str) -> None:
    acct = f"a_{suffix}"
    other = ", ".join(p for p in _WP_PRIVS.split(", ") if p != "SELECT")
    admin_sql(
        f"CREATE USER '{acct}'@'%' IDENTIFIED BY 'ap'",
        f"GRANT {other}, CREATE USER ON *.* TO '{acct}'@'%' WITH GRANT OPTION",
        f"GRANT SELECT ON `wp\\_{suffix}`.* TO '{acct}'@'%'",
    )
    try:
        verdict = check_ensure(new_site(suffix), Explicit(acct, "ap"), Explicit("u", "p"))
        [finding] = [f for f in verdict.findings if f.code is Code.MISSING_PRIVILEGE]
        assert finding.fields == {"privilege": "SELECT", "scope": "global"}
    finally:
        admin_sql(f"DROP USER IF EXISTS '{acct}'@'%'")


# --- destructive operations (plan 1, task 11) --------------------------------


def provisioned(suffix: str) -> Connection:
    ensure(new_site(suffix), new_admin(), Explicit(f"u_{suffix}", "wp-pass"))
    return new_site(suffix)


def test_drop_database_refuses_a_wrong_confirmation(suffix: str) -> None:
    conn = provisioned(suffix)
    with pytest.raises(RefusedError) as info:
        drop_database(conn, new_admin(), confirm="wp_something_else")
    assert Code.CONFIRMATION_MISMATCH in info.value.verdict.codes
    assert survey(conn, new_admin()).database_exists


def test_drop_database_warns_on_a_live_site(suffix: str) -> None:
    conn = provisioned(suffix)
    admin_sql(
        f"CREATE TABLE `wp_{suffix}`.`wp_options` "
        "(option_name VARCHAR(191), option_value LONGTEXT)",
        f"INSERT INTO `wp_{suffix}`.`wp_options` VALUES ('db_version', '58975')",  # noqa: S608
    )
    verdict = check_drop_database(conn, new_admin(), confirm=conn.database)
    assert verdict.ok
    assert Code.LIVE_WORDPRESS_SITE in verdict.codes


def test_drop_database_twice(suffix: str) -> None:
    conn = provisioned(suffix)
    assert drop_database(conn, new_admin(), confirm=conn.database).changed is True
    assert drop_database(conn, new_admin(), confirm=conn.database).changed is False


def test_drop_user_twice(suffix: str) -> None:
    conn = provisioned(suffix)
    user = f"u_{suffix}"
    assert drop_user(conn, new_admin(), user, confirm=user).changed is True
    assert drop_user(conn, new_admin(), user, confirm=user).changed is False


def test_revoke_then_revoke_again(suffix: str) -> None:
    conn = provisioned(suffix)
    user = f"u_{suffix}"
    assert revoke(conn, new_admin(), user, confirm=user).changed is True
    assert revoke(conn, new_admin(), user, confirm=user).changed is False
    assert survey(conn, new_admin(), wordpress_user=user).user_privileges == frozenset()


def test_revoke_absent_user_is_a_blocker(suffix: str) -> None:
    conn = new_site(suffix)
    with pytest.raises(RefusedError) as info:
        revoke(conn, new_admin(), f"u_{suffix}", confirm=f"u_{suffix}")
    assert Code.USER_ABSENT in info.value.verdict.codes


def test_rotate_password(suffix: str) -> None:
    conn = provisioned(suffix)
    rotate_password(conn, new_admin(), Explicit(f"u_{suffix}", "rotated"))
    pymysql.connect(host=HOST, port=PORT, user=f"u_{suffix}", password="rotated").close()


# --- final review C1: '%' in a database name -----------------------------------


def test_percent_in_a_database_name_is_provisioned_revoked_and_dropped(suffix: str) -> None:
    """PyMySQL %-formats a statement whenever it has arguments, so a '%' inside a
    quoted identifier must not be read as a format directive."""
    conn = Connection(host=HOST, port=PORT, database=f"wp%{suffix}")
    wp = Explicit(f"u_{suffix}", "wp-pass")
    first = ensure(conn, new_admin(), wp)
    assert (first.created_database, first.granted) == (True, True)
    assert not ensure(conn, new_admin(), wp).changed
    admin_sql(
        f"CREATE TABLE `wp%{suffix}`.`wp_options` "
        "(option_name VARCHAR(191), option_value LONGTEXT)",
        f"INSERT INTO `wp%{suffix}`.`wp_options` VALUES ('db_version', '58975')",  # noqa: S608
    )
    assert schema_version(conn, wp) is not None
    assert (
        Code.LIVE_WORDPRESS_SITE
        in check_drop_database(conn, new_admin(), confirm=conn.database).codes
    )
    assert revoke(conn, new_admin(), wp.username, confirm=wp.username).changed
    assert drop_database(conn, new_admin(), confirm=conn.database).changed


def test_revoke_removes_a_grant_on_the_unescaped_name(suffix: str) -> None:
    """The 0.0.x package granted on the unescaped name, which also matched
    neighbours such as wpX<s>; revoke must remove that grant too."""
    conn = new_site(suffix)
    user = f"u_{suffix}"
    admin_sql(
        f"CREATE DATABASE `wp_{suffix}`",
        f"CREATE USER '{user}'@'%' IDENTIFIED BY 'p'",
        f"GRANT ALL PRIVILEGES ON `wp_{suffix}`.* TO '{user}'@'%'",
    )
    assert revoke(conn, new_admin(), user, confirm=user).changed
    assert survey(conn, new_admin(), wordpress_user=user).user_privileges == frozenset()


def test_drop_user_needs_only_create_user(suffix: str) -> None:
    """The check promises CREATE USER is enough, so the run must not read mysql.user."""
    victim = f"u_{suffix}"
    limited = f"a_{suffix}"
    admin_sql(
        f"CREATE USER '{victim}'@'%' IDENTIFIED BY 'p'",
        f"CREATE USER '{limited}'@'%' IDENTIFIED BY 'limited-pw'",
        f"GRANT CREATE USER ON *.* TO '{limited}'@'%'",
    )
    try:
        admin = Explicit(limited, "limited-pw")
        conn = new_site(suffix)
        assert check_drop_user(conn, admin, victim, confirm=victim).ok
        assert drop_user(conn, admin, victim, confirm=victim).changed is True
        assert drop_user(conn, admin, victim, confirm=victim).changed is False
    finally:
        admin_sql(f"DROP USER IF EXISTS '{limited}'@'%'")


def test_ensure_with_a_user_host_that_excludes_the_runner(suffix: str) -> None:
    """The runner cannot log in as an account whose host it does not match, so
    ensure must not judge the password by trying."""
    conn = new_site(suffix)
    wp = Explicit(f"u_{suffix}", "wp-pass")
    try:
        first = ensure(conn, new_admin(), wp, user_host="10.255.255.%")
        assert (first.created_database, first.created_user, first.granted) == (True, True, True)
        assert Code.PASSWORD_UNVERIFIED in first.verdict.codes
        again = ensure(conn, new_admin(), wp, user_host="10.255.255.%")
        assert not again.changed
    finally:
        admin_sql(f"DROP USER IF EXISTS 'u_{suffix}'@'10.255.255.%'")


def test_a_warning_found_by_a_real_check_is_logged(suffix: str) -> None:
    conn = provisioned(suffix)
    admin_sql(
        f"CREATE TABLE `wp_{suffix}`.`wp_options` "
        "(option_name VARCHAR(191), option_value LONGTEXT)",
        f"INSERT INTO `wp_{suffix}`.`wp_options` VALUES ('db_version', '58975')",  # noqa: S608
    )
    with structlog.testing.capture_logs() as captured:
        check_drop_database(conn, new_admin(), confirm=conn.database)
    codes = [e.get("code") for e in captured if e.get("log_level") == "warning"]
    assert "live_wordpress_site" in codes
