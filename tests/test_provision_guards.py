"""Guards on destructive operations: the target must be named twice."""

from __future__ import annotations

from l3io.wp.database.provision import _confirmation
from l3io.wp.database.verdict import Code


def test_matching_confirmation_has_no_findings() -> None:
    assert _confirmation("wp_site", "wp_site") == []


def test_mismatched_confirmation_is_a_blocker_naming_both() -> None:
    [finding] = _confirmation("wp_site", "wp_stie")
    assert finding.code is Code.CONFIRMATION_MISMATCH
    assert finding.fields == {"target": "wp_site", "confirm": "wp_stie"}


def test_confirmation_is_exact_not_case_folded() -> None:
    assert _confirmation("wp_site", "WP_SITE")
