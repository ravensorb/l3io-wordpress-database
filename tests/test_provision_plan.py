"""ensure's planner is pure, so idempotence is provable without a server."""

from __future__ import annotations

import pytest

from l3io.wp.database import provision
from l3io.wp.database.errors import InvalidArgumentsError
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
    privs = Privileges(frozenset({"CREATE", "CREATE USER"}), grantable=True, unverified=False)
    [finding] = provision._privilege_findings(privs, provision.ENSURE_PRIVILEGES)
    assert finding.fields["privilege"] == "SELECT"


def test_role_turns_blockers_into_one_warning() -> None:
    privs = Privileges(frozenset(), grantable=False, unverified=True)
    [finding] = provision._privilege_findings(privs, provision.ENSURE_PRIVILEGES)
    assert finding.code is Code.PRIVILEGES_UNVERIFIED
