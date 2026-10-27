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


#: The only modules allowed to start processes; each call must pass env=.
SPAWNERS = {"_client.py", "transfer.py", "_passphrase.py"}


def _subprocess_users() -> dict[str, ast.Module]:
    found: dict[str, ast.Module] = {}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Import) and any(a.name == "subprocess" for a in node.names)
            ) or (isinstance(node, ast.ImportFrom) and node.module == "subprocess"):
                found[path.name] = tree
    return found


def test_only_the_client_modules_spawn_processes() -> None:
    users = _subprocess_users()
    assert users, "no module imports subprocess -- this guard is vacuous"
    assert set(users) <= SPAWNERS, f"unexpected process spawners: {set(users) - SPAWNERS}"


def test_every_process_gets_an_explicit_environment() -> None:
    missing = []
    for name, tree in _subprocess_users().items():
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"Popen", "run", "call", "check_call", "check_output"}
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "subprocess"
                and not any(k.arg == "env" for k in node.keywords)
            ):
                missing.append(f"{name}:{node.lineno}")
    assert missing == []


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
