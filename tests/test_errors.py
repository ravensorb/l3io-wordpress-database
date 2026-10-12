# tests/test_errors.py
from __future__ import annotations

from l3io.wp.database import errors
from l3io.wp.database.verdict import Code, Finding, Verdict


def test_every_error_derives_from_database_error() -> None:
    for name in dir(errors):
        obj = getattr(errors, name)
        if isinstance(obj, type) and issubclass(obj, Exception) and obj is not Exception:
            assert issubclass(obj, errors.DatabaseError), name


def test_refused_error_carries_the_verdict_and_names_each_blocker() -> None:
    verdict = Verdict(
        "drop_database",
        (
            Finding(Code.CONFIRMATION_MISMATCH, "confirm='wp_a' but the target is 'wp_b'"),
            Finding(Code.LIVE_WORDPRESS_SITE, "looks live"),
        ),
    )
    exc = errors.RefusedError(verdict)
    assert exc.verdict is verdict
    assert "drop_database refused" in str(exc)
    assert "confirmation_mismatch" in str(exc)
    assert "live_wordpress_site" not in str(exc)  # warnings are not reasons for refusal


def test_credentials_absent_lists_sources() -> None:
    exc = errors.CredentialsAbsentError("nothing", sources=("environment:A,B",))
    assert exc.sources == ("environment:A,B",)


def test_provisioning_error_records_completed_steps() -> None:
    exc = errors.ProvisioningError("grant failed", completed=("create_database",))
    assert exc.completed == ("create_database",)
