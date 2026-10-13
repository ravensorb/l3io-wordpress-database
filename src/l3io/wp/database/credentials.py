"""Database credentials and their sources.

AD-9: resolution is an explicit call, never a property read. The original
exposed ``username`` and ``password`` as property *getters* that performed an
AWS round trip and mutated ``self`` -- hidden network I/O behind attribute
access, with failures surfacing deep inside an unrelated database call.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import structlog

from .errors import (
    CredentialsAbsentError,
    CredentialsUnobtainableError,
    InvalidArgumentsError,
    MissingDependencyError,
    RegionNotKnownError,
)

_log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ResolvedCredentials:
    """A concrete username and password, and which source produced them.

    The password is redacted in ``repr`` so it cannot reach a log line or a
    traceback frame summary by accident.
    """

    username: str
    password: str
    source: str = "explicit"

    def __repr__(self) -> str:
        return (
            f"ResolvedCredentials(username={self.username!r}, password='***', "
            f"source={self.source!r})"
        )


@runtime_checkable
class CredentialSource(Protocol):
    """Anything that can produce credentials. Nothing needs to subclass a package type."""

    @property
    def source(self) -> str:
        """A label for logs and errors. Never the secret."""
        ...

    def resolve(self) -> ResolvedCredentials:
        """Obtain the credentials, performing I/O if the source requires it.

        Raises:
            CredentialsAbsentError: the source has nothing to offer.
            CredentialsUnobtainableError: the source tried and failed.
        """
        ...


@dataclass(frozen=True, slots=True, repr=False)
class Explicit:
    """Credentials given directly."""

    username: str
    password: str

    @property
    def source(self) -> str:
        return "explicit"

    def resolve(self) -> ResolvedCredentials:
        return ResolvedCredentials(self.username, self.password, self.source)

    def __repr__(self) -> str:
        return f"Explicit(username={self.username!r}, password='***')"


@dataclass(frozen=True, slots=True)
class Environment:
    """Credentials held in two environment variables."""

    username_var: str = "DB_USER"
    password_var: str = "DB_PASSWORD"  # noqa: S105 - name of an environment variable, not a secret

    @property
    def source(self) -> str:
        return f"environment:{self.username_var},{self.password_var}"

    def resolve(self) -> ResolvedCredentials:
        username = os.environ.get(self.username_var)
        password = os.environ.get(self.password_var)
        if username is None and password is None:
            msg = f"neither {self.username_var} nor {self.password_var} is set"
            raise CredentialsAbsentError(msg, sources=(self.source,))
        if username is None or password is None:
            unset = self.username_var if username is None else self.password_var
            msg = f"{unset} is not set, although its partner variable is"
            raise CredentialsUnobtainableError(msg)
        return ResolvedCredentials(username, password, self.source)


@dataclass(frozen=True, slots=True)
class AwsSecretsManager:
    """Credentials held in AWS Secrets Manager as JSON ``username``/``password``.

    Needs the ``aws`` extra.
    """

    secret_id: str
    region: str | None = None

    @property
    def source(self) -> str:
        return f"aws-secrets-manager:{self.secret_id}"

    def resolve(self) -> ResolvedCredentials:
        # AD-8: the optional dependency is imported inside the function that uses it.
        try:
            import boto3
        except ImportError as exc:
            raise MissingDependencyError(extra="aws", distribution="boto3") from exc

        # botocore's exceptions are not a public type (AD-14): everything that
        # talks to AWS is in one block, and parsing what came back in another,
        # so a client-side ValueError is never reported as a malformed secret.
        try:
            region = self.region or boto3.session.Session().region_name
        except Exception as exc:  # noqa: BLE001 - botocore session errors (e.g. ProfileNotFound)
            msg = f"could not read secret {self.secret_id!r}: the AWS session could not be set up"
            raise CredentialsUnobtainableError(msg) from exc
        if not region:
            raise RegionNotKnownError

        _log.debug("resolving secret", source=self.source, region=region)
        try:
            client = boto3.client("secretsmanager", region_name=region)
            payload: Any = client.get_secret_value(SecretId=self.secret_id)["SecretString"]
        except Exception as exc:  # noqa: BLE001 - boto3 errors are not a public type (AD-14)
            msg = f"could not read secret {self.secret_id!r} from AWS Secrets Manager"
            raise CredentialsUnobtainableError(msg) from exc

        shape = (
            f"secret {self.secret_id!r} is not shaped as expected: it must be a JSON "
            "object whose 'username' and 'password' are strings"
        )
        try:
            document = json.loads(payload)
        except (TypeError, ValueError) as exc:
            raise CredentialsUnobtainableError(shape) from exc
        if not isinstance(document, dict):
            raise CredentialsUnobtainableError(shape)
        username, password = document.get("username"), document.get("password")
        if not isinstance(username, str) or not isinstance(password, str):
            raise CredentialsUnobtainableError(shape)
        return ResolvedCredentials(username, password, self.source)


class CredentialChain:
    """The first source with an answer.

    Moves to the next source only when one is *absent*. A source that *failed*
    stops the chain, because falling through to a different credential after a
    failure is a silent substitution.
    """

    __slots__ = ("_sources",)

    def __init__(self, *sources: CredentialSource) -> None:
        if not sources:
            msg = "a CredentialChain needs at least one source"
            raise InvalidArgumentsError(msg)
        self._sources = sources

    @property
    def source(self) -> str:
        return "chain(" + ", ".join(s.source for s in self._sources) + ")"

    def resolve(self) -> ResolvedCredentials:
        tried: list[str] = []
        for candidate in self._sources:
            try:
                return candidate.resolve()
            except CredentialsAbsentError:
                tried.append(candidate.source)
        msg = "no credential source had an answer: " + ", ".join(tried)
        raise CredentialsAbsentError(msg, sources=tuple(tried))

    def __repr__(self) -> str:
        return f"CredentialChain({self.source})"
