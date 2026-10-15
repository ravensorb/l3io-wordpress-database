"""The GRANT wildcard defect, and identifier validation.

``test_grant_clause_escapes_the_underscore_wildcard`` is the regression test for
a verified privilege-escalation bug: a user granted only on ``wp_site`` could
list and write to ``wpXsite``, because a database-level GRANT matches its
database name as a LIKE pattern.
"""

from __future__ import annotations

import pytest

from l3io.wp.database.errors import InvalidDatabaseNameError, InvalidIdentifierError
from l3io.wp.database.identifiers import (
    quote_grant_database,
    quote_identifier,
    validate_database_name,
    validate_user_name,
)


def test_grant_clause_escapes_the_underscore_wildcard() -> None:
    assert quote_grant_database("wp_site") == r"`wp\_site`"


def test_grant_clause_escapes_the_percent_wildcard() -> None:
    assert quote_grant_database("wp%site") == r"`wp\%site`"


def test_grant_clause_leaves_wildcard_free_names_alone() -> None:
    assert quote_grant_database("wordpress") == "`wordpress`"


def test_plain_quoting_does_not_escape_wildcards() -> None:
    """USE and CREATE DATABASE are not pattern-matched, so they must not escape."""
    assert quote_identifier("wp_site") == "`wp_site`"


def test_quoting_doubles_internal_backticks() -> None:
    assert quote_identifier("we`ird") == "`we``ird`"


@pytest.mark.parametrize(
    "name",
    ["", "a" * 65, " leading", "trailing ", "has`backtick", "has.dot", "has/slash", "has\x00null"],
)
def test_invalid_database_names_are_rejected(name: str) -> None:
    with pytest.raises(InvalidDatabaseNameError):
        validate_database_name(name)


def test_invalid_database_name_error_is_an_identifier_error() -> None:
    with pytest.raises(InvalidIdentifierError):
        validate_database_name("bad.name")


def test_valid_database_name_is_returned() -> None:
    assert validate_database_name("wp_site") == "wp_site"


def test_user_name_limit_is_the_stricter_mysql_one() -> None:
    assert validate_user_name("u" * 32) == "u" * 32
    with pytest.raises(InvalidIdentifierError):
        validate_user_name("u" * 33)


def test_a_user_name_with_a_quote_is_refused() -> None:
    """``'`` breaks the ``'user'@'host'`` grantee form the grant lookup compares against."""
    with pytest.raises(InvalidIdentifierError, match="forbidden"):
        validate_user_name("o'brien")
