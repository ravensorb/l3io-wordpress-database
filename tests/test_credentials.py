"""Credential sources: absent versus failed, and the chain that respects it."""

from __future__ import annotations

import pytest

from l3io.wp.database.credentials import (
    AwsSecretsManager,
    CredentialChain,
    CredentialSource,
    Environment,
    Explicit,
    ResolvedCredentials,
)
from l3io.wp.database.errors import (
    CredentialsAbsentError,
    CredentialsUnobtainableError,
    InvalidArgumentsError,
)

SECRET = "s3cr3t-value"


class _Failing:
    source = "failing"

    def resolve(self) -> ResolvedCredentials:
        msg = "refused"
        raise CredentialsUnobtainableError(msg)


class _Absent:
    source = "absent"

    def resolve(self) -> ResolvedCredentials:
        msg = "nothing here"
        raise CredentialsAbsentError(msg, sources=(self.source,))


def test_protocol_accepts_a_plain_object() -> None:
    assert isinstance(_Failing(), CredentialSource)
    assert isinstance(Explicit("u", "p"), CredentialSource)


def test_explicit_resolves_and_redacts() -> None:
    source = Explicit("wpuser", SECRET)
    resolved = source.resolve()
    assert resolved == ResolvedCredentials("wpuser", SECRET, "explicit")
    assert SECRET not in repr(source)
    assert SECRET not in repr(resolved)


def test_empty_password_is_a_value() -> None:
    assert Explicit("u", "").resolve().password == ""


def test_environment_both_unset_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("X_USER", raising=False)
    monkeypatch.delenv("X_PASS", raising=False)
    with pytest.raises(CredentialsAbsentError) as info:
        Environment("X_USER", "X_PASS").resolve()
    assert info.value.sources == ("environment:X_USER,X_PASS",)


def test_environment_half_set_is_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("X_USER", "u")
    monkeypatch.delenv("X_PASS", raising=False)
    with pytest.raises(CredentialsUnobtainableError, match="X_PASS"):
        Environment("X_USER", "X_PASS").resolve()


def test_environment_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("X_USER", "u")
    monkeypatch.setenv("X_PASS", SECRET)
    resolved = Environment("X_USER", "X_PASS").resolve()
    assert (resolved.username, resolved.password) == ("u", SECRET)
    assert resolved.source == "environment:X_USER,X_PASS"


def test_chain_skips_absent_and_names_who_answered() -> None:
    resolved = CredentialChain(_Absent(), Explicit("u", "p")).resolve()
    assert resolved.source == "explicit"


def test_chain_stops_on_failure() -> None:
    with pytest.raises(CredentialsUnobtainableError):
        CredentialChain(_Failing(), Explicit("u", "p")).resolve()


def test_chain_all_absent_names_every_source() -> None:
    with pytest.raises(CredentialsAbsentError) as info:
        CredentialChain(_Absent(), _Absent()).resolve()
    assert info.value.sources == ("absent", "absent")


def test_empty_chain_is_rejected() -> None:
    with pytest.raises(InvalidArgumentsError):
        CredentialChain()


def test_aws_source_label_names_the_secret_not_its_value() -> None:
    assert AwsSecretsManager("prod/wp-admin", region="us-east-1").source == (
        "aws-secrets-manager:prod/wp-admin"
    )
