"""The command line: argument handling, exit codes, and no password on argv."""

from __future__ import annotations

import json
from typing import Any

import pytest

from l3io.wp.database import cli
from l3io.wp.database.provision import EnsureResult, OperationResult
from l3io.wp.database.state import ConnectionState
from l3io.wp.database.verdict import Code, Finding, Verdict

SITE = ["--db-host", "db:3307", "--db-name", "wp_site"]
WP = ["--db-user", "wpuser", "--db-password-env", "WP_PW"]
ADMIN = ["--admin-user", "root", "--admin-password-env", "ADMIN_PW"]


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WP_PW", "wp-secret")
    monkeypatch.setenv("ADMIN_PW", "admin-secret")


def _actions(parser: Any) -> list[Any]:
    found = list(parser._actions)
    for action in parser._actions:
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict):  # subcommand maps; --log-format's choices are a list
            for sub in choices.values():
                found += _actions(sub)
    return found


def test_no_option_takes_a_password_value() -> None:
    offenders = [
        a.option_strings
        for a in _actions(cli.build_parser())
        if any("password" in s for s in a.option_strings)
        and not all(s.endswith("-env") for s in a.option_strings)
    ]
    assert offenders == []


def test_ensure_success_prints_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: dict[str, Any] = {}

    def fake_ensure(connection, admin, wordpress, **kw):  # type: ignore[no-untyped-def]
        calls.update(
            connection=connection, admin=admin.resolve(), wordpress=wordpress.resolve(), kw=kw
        )
        return EnsureResult(True, True, True, True, Verdict("ensure"))

    monkeypatch.setattr(cli, "ensure", fake_ensure)
    assert cli.main(["ensure", *SITE, *WP, *ADMIN]) == cli.Exit.OK
    out = json.loads(capsys.readouterr().out)
    assert out["created_database"] is True
    assert calls["connection"].port == 3307
    assert calls["admin"].password == "admin-secret"
    assert calls["wordpress"].password == "wp-secret"


def test_refusal_maps_to_refused_exit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from l3io.wp.database.errors import RefusedError

    def refuse(*a: Any, **k: Any) -> Any:
        raise RefusedError(Verdict("drop_database", (Finding(Code.CONFIRMATION_MISMATCH, "no"),)))

    monkeypatch.setattr(cli, "drop_database", refuse)
    code = cli.main(["drop-database", *SITE, *ADMIN, "--confirm", "wrong"])
    assert code == cli.Exit.REFUSED
    assert "confirmation_mismatch" in capsys.readouterr().err


def test_unreachable_refusal_maps_to_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    from l3io.wp.database.errors import RefusedError

    def refuse(*a: Any, **k: Any) -> Any:
        raise RefusedError(Verdict("ensure", (Finding(Code.UNREACHABLE, "down"),)))

    monkeypatch.setattr(cli, "ensure", refuse)
    assert cli.main(["ensure", *SITE, *WP, *ADMIN]) == cli.Exit.UNREACHABLE


def test_inspect_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "inspect", lambda *a, **k: ConnectionState.DATABASE_ABSENT)
    assert cli.main(["inspect", *SITE, *WP]) == cli.Exit.NOT_READY


def test_destructive_subcommands_require_confirm() -> None:
    with pytest.raises(SystemExit) as info:
        cli.main(["drop-database", *SITE, *ADMIN])
    assert info.value.code == cli.Exit.USAGE


def test_missing_password_variable_is_a_credentials_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADMIN_PW")
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert (
        cli.main(["drop-database", *SITE, *ADMIN, "--confirm", "wp_site"]) == cli.Exit.CREDENTIALS
    )


def test_check_subcommand_prints_the_verdict(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        cli,
        "check_drop_database",
        lambda *a, **k: Verdict("drop_database", (Finding(Code.LIVE_WORDPRESS_SITE, "live"),)),
    )
    assert (
        cli.main(["check", "drop-database", *SITE, *ADMIN, "--confirm", "wp_site"]) == cli.Exit.OK
    )
    out = json.loads(capsys.readouterr().out)
    assert out["findings"][0]["code"] == "live_wordpress_site"


def test_revoke_passes_user_and_confirm(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake(connection, admin, user, **kw):  # type: ignore[no-untyped-def]
        seen.update(user=user, **kw)
        return OperationResult(True, Verdict("revoke"))

    monkeypatch.setattr(cli, "revoke", fake)
    assert (
        cli.main(["revoke", *SITE, *ADMIN, "--user", "wpuser", "--confirm", "wpuser"])
        == cli.Exit.OK
    )
    assert seen == {"user": "wpuser", "user_host": "%", "confirm": "wpuser"}


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (Code.UNREACHABLE, cli.Exit.UNREACHABLE),
        (Code.CREDENTIALS_UNOBTAINABLE, cli.Exit.CREDENTIALS),
        (Code.CONFIRMATION_MISMATCH, cli.Exit.REFUSED),
    ],
)
def test_check_exits_as_the_operation_would(
    monkeypatch: pytest.MonkeyPatch, code: Code, expected: cli.Exit
) -> None:
    monkeypatch.setattr(
        cli, "check_drop_database", lambda *a, **k: Verdict("drop_database", (Finding(code, "x"),))
    )
    assert cli.main(["check", "drop-database", *SITE, *ADMIN, "--confirm", "wp_site"]) == expected
