"""Credentials must not leak into logs, reprs, exceptions, or argv.

These are the two assertions the handoff's definition of done asked for, made
mechanical rather than left to review: no credential in captured log output,
and no password reachable through an argument vector.

The distinction this package draws deliberately: a secret *value* never appears
anywhere, while a secret *identifier* may appear in an error, because
diagnosing "which secret could not be read" is impossible without it.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest
import structlog

from l3io.wp.database import (
    AwsSecretsManager,
    Connection,
    Database,
    Explicit,
    ResolvedCredentials,
    ensure,
    inspect,
)

SRC = Path(__file__).resolve().parent.parent / "src/l3io/wp/database"
SECRET = "correct-horse-battery-staple"

#: A site whose credentials resolve but whose server cannot be reached.
CONN = Connection(host="127.0.0.1", port=1, database="wp_site")
WORDPRESS = Explicit("wpuser", SECRET)


def test_no_module_spawns_a_subprocess() -> None:
    """A scope guard, not a style rule.

    Nothing here shells out today, so "no password in argv" is currently
    vacuous. This test is what makes it stay true: the moment someone adds a
    mysql or mysqldump call, it fires, and they have to deal with credential
    transport deliberately -- `--defaults-file` at mode 0600 rather than
    `--defaults-extra-file`, which is additive and lets an ambient ~/.my.cnf
    redirect the connection, and never MYSQL_PWD, which MySQL 8.4 calls
    extremely insecure.
    """
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(n.split(".")[0] in {"subprocess", "os"} and "exec" in n for n in names):
                offenders.append(f"{path.name}: {names}")
            if any(n == "subprocess" for n in names):
                offenders.append(f"{path.name}: imports subprocess")
    assert not offenders, (
        "a module now spawns processes; credential transport must be handled "
        f"explicitly before this is allowed: {offenders}"
    )


def test_password_is_absent_from_every_repr() -> None:
    for subject in (
        WORDPRESS,
        CONN,
        Database(CONN),
        ResolvedCredentials("wpuser", SECRET),
    ):
        assert SECRET not in repr(subject), f"{type(subject).__name__} leaked it"


def test_password_is_absent_from_structured_log_output() -> None:
    with structlog.testing.capture_logs() as captured:
        inspect(CONN, WORDPRESS)
    rendered = repr(captured)
    assert SECRET not in rendered, f"a log event carried the password: {rendered}"


def test_password_is_absent_from_stdlib_log_output(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        inspect(CONN, WORDPRESS)
    assert SECRET not in caplog.text


def test_password_is_absent_from_the_failure_raised_to_the_caller() -> None:
    """A traceback is log output by another name."""
    admin = Explicit("root", "admin-" + SECRET)
    with pytest.raises(Exception) as caught:  # noqa: B017 - any failure must be clean
        ensure(CONN, admin, WORDPRESS)
    assert SECRET not in str(caught.value)
    assert "admin-" + SECRET not in str(caught.value)


def test_a_secret_identifier_may_appear_but_never_a_value() -> None:
    """The deliberate asymmetry, pinned so it is not "tidied" either way.

    Banning identifiers too would make an actionable error impossible to write
    -- "a secret could not be read" without saying which one is not actionable.
    The AWS source holds no secret value at all, only the identifier.
    """
    source = AwsSecretsManager("prod/wp/db")
    assert source.source == "aws-secrets-manager:prod/wp/db"
