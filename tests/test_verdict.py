# tests/test_verdict.py
"""The Verdict vocabulary: one severity per code, and every code described."""

from __future__ import annotations

import pytest

from l3io.wp.database.verdict import Code, Finding, Severity, Verdict


def test_every_code_has_a_severity_and_a_description() -> None:
    for code in Code:
        assert isinstance(code.severity, Severity), code
        assert code.description.strip(), f"{code} has no description"


def test_blockers_and_warnings_are_partitioned() -> None:
    verdict = Verdict(
        "ensure",
        (
            Finding(Code.MISSING_PRIVILEGE, "needs CREATE USER", {"privilege": "CREATE USER"}),
            Finding(Code.END_OF_LIFE_SERVER, "MySQL 8.0 is past end of life"),
        ),
    )
    assert [f.code for f in verdict.blockers] == [Code.MISSING_PRIVILEGE]
    assert [f.code for f in verdict.warnings] == [Code.END_OF_LIFE_SERVER]
    assert not verdict.ok
    assert verdict.codes == frozenset({Code.MISSING_PRIVILEGE, Code.END_OF_LIFE_SERVER})


def test_warnings_alone_are_ok() -> None:
    assert Verdict("ensure", (Finding(Code.END_OF_LIFE_SERVER, "old"),)).ok
    assert Verdict("ensure").ok


def test_with_findings_returns_a_new_verdict() -> None:
    first = Verdict("drop_database")
    second = first.with_findings(Finding(Code.CONFIRMATION_MISMATCH, "wrong name"))
    assert first.findings == ()
    assert not second.ok


@pytest.mark.parametrize(
    ("code", "severity"),
    [
        (Code.UNREACHABLE, Severity.BLOCKER),
        (Code.CONFIRMATION_MISMATCH, Severity.BLOCKER),
        (Code.LIVE_WORDPRESS_SITE, Severity.WARNING),
        (Code.PRIVILEGES_UNVERIFIED, Severity.WARNING),
    ],
)
def test_fixed_severities(code: Code, severity: Severity) -> None:
    assert Finding(code, "x").severity is severity


def test_findings_are_immutable() -> None:
    finding = Finding(Code.UNREACHABLE, "down", {"host": "db"})
    with pytest.raises(TypeError):
        finding.fields["host"] = "other"  # type: ignore[index]
