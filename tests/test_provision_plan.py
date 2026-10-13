"""ensure's planner is pure, so idempotence is provable without a server."""

from __future__ import annotations

import pymysql
import pytest

from l3io.wp.database import provision
from l3io.wp.database.connection import Connection
from l3io.wp.database.credentials import Explicit
from l3io.wp.database.errors import DatabaseError, InvalidArgumentsError
from l3io.wp.database.identifiers import (
    grant_pattern,
    quote_grant_database,
    quote_identifier,
    validate_charset,
)
from l3io.wp.database.provision import EnsureFacts, plan_ensure
from l3io.wp.database.server import Privileges
from l3io.wp.database.verdict import Code


def test_plan_for_converged_site_is_empty() -> None:
    assert plan_ensure(EnsureFacts(True, True, True, True)) == ()


def test_plan_for_fresh_site() -> None:
    assert plan_ensure(EnsureFacts(False, False, False, False)) == (
        "create_database",
        "create_user",
        "grant",
    )


def test_existing_user_with_wrong_password_gets_set_password() -> None:
    assert plan_ensure(EnsureFacts(True, True, False, True)) == ("set_password",)


def test_new_user_never_also_gets_set_password() -> None:
    assert "set_password" not in plan_ensure(EnsureFacts(True, False, False, True))


@pytest.mark.parametrize("name", ["wp_site", "wp%site", "plain"])
def test_grant_pattern_is_the_unquoted_form(name: str) -> None:
    assert quote_grant_database(name) == quote_identifier(grant_pattern(name))


def test_grant_pattern_escapes_wildcards() -> None:
    assert grant_pattern("wp_a%b") == r"wp\_a\%b"


@pytest.mark.parametrize("value", ["utf8mb4", "utf8mb4_unicode_ci"])
def test_charset_accepted(value: str) -> None:
    assert validate_charset(value, "charset") == value


@pytest.mark.parametrize("value", ["utf8mb4; DROP DATABASE x", "", "utf8 mb4"])
def test_charset_rejected(value: str) -> None:
    with pytest.raises(InvalidArgumentsError):
        validate_charset(value, "charset")


def test_privilege_findings_for_ensure() -> None:
    privs = Privileges(frozenset({"CREATE"}), grantable=False, unverified=False)
    codes = provision._privilege_findings(
        privs, ("CREATE", "CREATE USER", "SELECT", "GRANT OPTION")
    )
    assert [f.fields["privilege"] for f in codes] == ["CREATE USER", "SELECT", "GRANT OPTION"]
    assert all(f.code is Code.MISSING_PRIVILEGE for f in codes)


def test_missing_select_is_a_blocker() -> None:
    privs = Privileges(
        frozenset(provision.ENSURE_PRIVILEGES) | {"CREATE USER"},
        grantable=True,
        unverified=False,
        global_names=frozenset(),
    )
    [finding] = provision._privilege_findings(
        privs, provision.ENSURE_PRIVILEGES, provision.ENSURE_GLOBAL_PRIVILEGES
    )
    assert finding.fields["privilege"] == "SELECT"


def test_role_turns_blockers_into_one_warning() -> None:
    privs = Privileges(frozenset(), grantable=False, unverified=True)
    [finding] = provision._privilege_findings(
        privs, provision.ENSURE_PRIVILEGES, provision.ENSURE_GLOBAL_PRIVILEGES
    )
    assert finding.code is Code.PRIVILEGES_UNVERIFIED


def test_database_level_select_does_not_satisfy_global_select() -> None:
    privs = Privileges(
        frozenset({"SELECT"}), grantable=True, unverified=False, global_names=frozenset()
    )
    [finding] = provision._privilege_findings(privs, (), provision.ENSURE_GLOBAL_PRIVILEGES)
    assert finding.fields == {"privilege": "SELECT", "scope": "global"}


def test_every_wordpress_privilege_is_required_of_the_grantor() -> None:
    assert set(provision.ENSURE_PRIVILEGES) >= provision.WORDPRESS_PRIVILEGES


class _ExplodingCursor:
    def __enter__(self) -> _ExplodingCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, *args: object) -> None:
        raise pymysql.err.OperationalError(2013, "lost")


class _Session:
    closed = False

    def cursor(self) -> _ExplodingCursor:
        return _ExplodingCursor()

    def close(self) -> None:
        self.closed = True


def test_server_error_in_preflight_is_package_owned_and_closes_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session()
    monkeypatch.setattr(provision, "open_connection", lambda *a, **k: session)
    with pytest.raises(DatabaseError) as info:
        provision._preflight(
            Connection(host="h", database="wp_x"), Explicit("a", "b"), "ensure", ()
        )
    assert not isinstance(info.value, pymysql.err.MySQLError)
    assert session.closed
