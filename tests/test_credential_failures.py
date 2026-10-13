"""Every kind of credential-source failure becomes a coded verdict, never an exception.

No server is needed: the connection points at a closed port, and the failing
source is resolved before or alongside the unreachable preflight.
"""

from __future__ import annotations

import pytest

from l3io.wp.database import (
    Connection,
    ConnectionState,
    Explicit,
    ResolvedCredentials,
    check_ensure,
    check_rotate_password,
    ensure,
    inspect,
)
from l3io.wp.database.errors import (
    CredentialsUnobtainableError,
    MissingConfigValueError,
    MissingDependencyError,
    RefusedError,
)
from l3io.wp.database.verdict import Code

CONN = Connection(host="127.0.0.1", port=1, database="wp_site")


class _Raises:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.source = "test"

    def resolve(self) -> ResolvedCredentials:
        raise self._exc


HALF_CONFIG = _Raises(MissingConfigValueError("DB_PASSWORD", "/srv/wp-config.php"))
NO_EXTRA = _Raises(MissingDependencyError(extra="aws", distribution="boto3"))
REFUSED = _Raises(CredentialsUnobtainableError("AWS refused"))


@pytest.mark.parametrize("source", [HALF_CONFIG, NO_EXTRA, REFUSED])
def test_inspect_never_raises_for_a_credential_failure(source: _Raises) -> None:
    assert inspect(CONN, source) is ConnectionState.CREDENTIALS_UNOBTAINABLE


def test_a_missing_extra_is_a_coded_blocker() -> None:
    verdict = check_ensure(CONN, NO_EXTRA, Explicit("u", "p"))
    [finding] = [f for f in verdict.findings if f.code is Code.MISSING_DEPENDENCY]
    assert finding.fields == {"extra": "aws"}


def test_a_half_defined_wordpress_config_is_a_coded_blocker() -> None:
    verdict = check_ensure(CONN, Explicit("root", "x"), HALF_CONFIG)
    assert Code.CREDENTIALS_UNOBTAINABLE in verdict.codes


def test_ensure_refuses_with_the_same_verdict() -> None:
    expected = check_ensure(CONN, Explicit("root", "x"), NO_EXTRA)
    with pytest.raises(RefusedError) as info:
        ensure(CONN, Explicit("root", "x"), NO_EXTRA)
    assert info.value.verdict == expected


@pytest.mark.parametrize("source", [HALF_CONFIG, NO_EXTRA, REFUSED])
def test_check_rotate_password_returns_a_verdict(source: _Raises) -> None:
    verdict = check_rotate_password(CONN, Explicit("root", "x"), source)
    assert not verdict.ok
    assert verdict.codes & {Code.CREDENTIALS_UNOBTAINABLE, Code.MISSING_DEPENDENCY}


def test_check_and_run_raise_the_same_error_for_a_bad_user_name() -> None:
    from l3io.wp.database.errors import InvalidIdentifierError

    bad = Explicit("has.dot", "p")
    with pytest.raises(InvalidIdentifierError):
        check_ensure(CONN, Explicit("root", "x"), bad)
    with pytest.raises(InvalidIdentifierError):
        ensure(CONN, Explicit("root", "x"), bad)
