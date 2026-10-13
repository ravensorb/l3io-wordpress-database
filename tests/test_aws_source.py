"""AwsSecretsManager against a fake boto3, so every branch runs without AWS."""

from __future__ import annotations

import json
import sys
import types
from typing import Any

import pytest

from l3io.wp.database.credentials import AwsSecretsManager
from l3io.wp.database.errors import (
    CredentialsUnobtainableError,
    MissingDependencyError,
    RegionNotKnownError,
)

SECRET = "aws-held-password"


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    payload: Any = None,
    region: str | None = "us-east-1",
    session_error: Exception | None = None,
    client_error: Exception | None = None,
) -> None:
    def session() -> Any:
        if session_error is not None:
            raise session_error
        return types.SimpleNamespace(region_name=region)

    def client(name: str, region_name: str) -> Any:
        def get_secret_value(SecretId: str) -> dict[str, Any]:  # noqa: N803 - boto3's name
            if client_error is not None:
                raise client_error
            return {"SecretString": payload}

        return types.SimpleNamespace(get_secret_value=get_secret_value)

    fake = types.ModuleType("boto3")
    fake.session = types.SimpleNamespace(Session=session)  # type: ignore[attr-defined]
    fake.client = client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "boto3", fake)


def test_resolves_a_well_shaped_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, payload=json.dumps({"username": "admin", "password": SECRET}))
    resolved = AwsSecretsManager("prod/db").resolve()
    assert (resolved.username, resolved.password) == ("admin", SECRET)
    assert resolved.source == "aws-secrets-manager:prod/db"


def test_missing_extra_names_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "boto3", None)
    with pytest.raises(MissingDependencyError) as info:
        AwsSecretsManager("prod/db").resolve()
    assert info.value.extra == "aws"


def test_unknown_region(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, region=None)
    with pytest.raises(RegionNotKnownError):
        AwsSecretsManager("prod/db").resolve()


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        json.dumps({"username": "admin"}),
        json.dumps({"username": None, "password": SECRET}),
        json.dumps({"username": "admin", "password": 12345}),
        json.dumps(["admin", SECRET]),
    ],
)
def test_a_badly_shaped_secret_says_so(monkeypatch: pytest.MonkeyPatch, payload: str) -> None:
    _install(monkeypatch, payload=payload)
    with pytest.raises(CredentialsUnobtainableError, match="not shaped as expected"):
        AwsSecretsManager("prod/db").resolve()


@pytest.mark.parametrize("error", [RuntimeError("AccessDenied"), ValueError("bad region")])
def test_a_client_failure_is_not_called_a_shape_problem(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    _install(monkeypatch, client_error=error)
    with pytest.raises(CredentialsUnobtainableError, match="could not read") as info:
        AwsSecretsManager("prod/db").resolve()
    assert SECRET not in str(info.value)


def test_a_session_failure_is_package_owned(monkeypatch: pytest.MonkeyPatch) -> None:
    """e.g. botocore's ProfileNotFound when AWS_PROFILE names an unknown profile."""
    _install(monkeypatch, session_error=LookupError("profile not found"), region=None)
    with pytest.raises(CredentialsUnobtainableError):
        AwsSecretsManager("prod/db").resolve()
