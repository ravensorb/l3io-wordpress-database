"""Validating and quoting MySQL identifiers.

A database-level ``GRANT`` matches its database name as a ``LIKE`` pattern, so
``_`` is a single-character wildcard. Granting on ``wp_site`` therefore also
grants on ``wpXsite``:

    GRANT ALL PRIVILEGES ON `wp_site`.* TO 'victim'@'%';
    -- victim can then SHOW and CREATE TABLE in wpXsite

Backticks do not suppress this; only escaping the wildcard does. Essentially
every WordPress database is named with an underscore, so an unescaped
``GRANT ALL PRIVILEGES ON {n}.*`` over-grants every user it creates.
"""

from __future__ import annotations

import re

from .errors import InvalidArgumentsError, InvalidDatabaseNameError, InvalidIdentifierError

#: MySQL caps database names at 64 characters. MariaDB allows longer user names
#: than MySQL's 32, so the stricter MySQL limit is applied to both.
MAX_DATABASE_NAME = 64
MAX_USER_NAME = 32

_FORBIDDEN = {"\x00", "\n", "\r", "`", "/", "\\", "."}
#: The grant lookup compares against the unescaped ``'user'@'host'`` form.
_FORBIDDEN_IN_USER_NAME = frozenset("'")


def _check(kind: str, value: str, limit: int, forbidden: frozenset[str] = frozenset()) -> None:
    if not isinstance(value, str) or not value:
        raise InvalidIdentifierError(kind, str(value), "must be a non-empty string")
    if len(value) > limit:
        raise InvalidIdentifierError(kind, value, f"longer than {limit} characters")
    if value != value.strip():
        raise InvalidIdentifierError(kind, value, "has leading or trailing whitespace")
    found = (_FORBIDDEN | forbidden).intersection(value)
    if found:
        chars = ", ".join(repr(c) for c in sorted(found))
        raise InvalidIdentifierError(kind, value, f"contains forbidden characters: {chars}")


def validate_database_name(name: str) -> str:
    """Return ``name`` if it is usable as a database identifier, else raise."""
    try:
        _check("database name", name, MAX_DATABASE_NAME)
    except InvalidIdentifierError as exc:
        raise InvalidDatabaseNameError(str(name), exc.reason) from exc
    return name


def validate_user_name(name: str) -> str:
    """Return ``name`` if it is usable as a user identifier, else raise."""
    _check("user name", name, MAX_USER_NAME, _FORBIDDEN_IN_USER_NAME)
    return name


def quote_identifier(name: str) -> str:
    """Backtick-quote an identifier, doubling any internal backticks."""
    return "`" + name.replace("`", "``") + "`"


def grant_pattern(name: str) -> str:
    """The database name as the ``LIKE`` pattern a GRANT stores, unquoted.

    ``information_schema.SCHEMA_PRIVILEGES.TABLE_SCHEMA`` holds this form, so
    comparing against it finds exactly the grant :func:`quote_grant_database`
    wrote.
    """
    return name.replace("\\", "\\\\").replace("_", r"\_").replace("%", r"\%")


def quote_grant_database(name: str) -> str:
    """Quote a database name for the ``ON <db>.*`` clause of a GRANT.

    The clause is matched as a ``LIKE`` pattern, so ``_`` and ``%`` must be
    escaped or the grant silently widens to every database matching it.
    """
    return quote_identifier(grant_pattern(name))


_CHARSET = re.compile(r"^[A-Za-z0-9_]+$")


def validate_charset(value: str, kind: str) -> str:
    """Return a character set or collation name, or raise.

    These cannot be parameterised, so they are restricted to the characters
    every real name uses.
    """
    if not isinstance(value, str) or not _CHARSET.match(value):
        msg = f"{kind} {value!r} is not a valid name"
        raise InvalidArgumentsError(msg)
    return value
