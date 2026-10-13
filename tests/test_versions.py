"""The db_version lookup, and the derived map it reads.

The original held this as a hand-maintained dict of string keys that stopped at
WordPress 5.5.1, so it returned None for every WordPress from 5.6 onward. These
tests pin both halves of the fix: the data is derived, and the lookup is
numeric and ordered.
"""

from __future__ import annotations

import pytest

from l3io.wp.database._version_map import DB_VERSION_TO_RELEASE, MIN_RELEASE
from l3io.wp.database.versions import (
    CEILING_DB_VERSION,
    FLOOR_DB_VERSION,
    SUPPORTED_FROM,
    SchemaVersion,
    release_for,
)


def test_the_floor_is_the_supported_release() -> None:
    assert SUPPORTED_FROM == MIN_RELEASE == "5.0"
    assert DB_VERSION_TO_RELEASE[FLOOR_DB_VERSION] == "5.0"


def test_an_exact_value_resolves() -> None:
    assert release_for(FLOOR_DB_VERSION) == "5.0"


def test_a_value_between_releases_resolves_to_the_lower_one() -> None:
    """A development build reports a value no release has."""
    known = sorted(DB_VERSION_TO_RELEASE)
    lower, upper = known[0], known[1]
    between = lower + (upper - lower) // 2
    assert between not in DB_VERSION_TO_RELEASE
    assert release_for(between) == DB_VERSION_TO_RELEASE[lower]


def test_below_the_floor_is_none_and_says_so() -> None:
    version = SchemaVersion(FLOOR_DB_VERSION - 1)
    assert version.release is None
    assert version.is_older_than_supported
    assert "older than WordPress 5.0" in str(version)


def test_the_comparison_is_numeric_not_lexicographic() -> None:
    """`'9872' <= '48748'` is False, so a string-ordered lookup was wrong.

    The old map keyed on strings; ordering them would have resolved a 5-digit
    value to a 4-digit release. Numerically 9872 < 48748, so anything below the
    floor must report None rather than picking a spuriously 'greater' key.
    """
    # `not (a <= b)` rather than `a <= b is False`: the latter chains in
    # Python and means `(a <= b) and (b is False)`, which is a different claim.
    assert not ("9872" <= "48748")
    assert release_for(9872) is None


def test_the_mapping_is_many_to_one() -> None:
    """7.0 and 7.1 share a db_version, so a value names what introduced it."""
    assert release_for(CEILING_DB_VERSION) == DB_VERSION_TO_RELEASE[CEILING_DB_VERSION]
    assert len(set(DB_VERSION_TO_RELEASE.values())) == len(DB_VERSION_TO_RELEASE)


def test_a_newer_schema_is_distinguishable_from_an_unknown_one() -> None:
    newer = SchemaVersion(CEILING_DB_VERSION + 1000)
    assert newer.is_newer_than_known
    assert not newer.is_older_than_supported
    assert newer.release is not None
    assert "or newer" in str(newer)


def test_a_known_schema_renders_readably() -> None:
    assert str(SchemaVersion(FLOOR_DB_VERSION)) == (
        f"WordPress 5.0 (db_version {FLOOR_DB_VERSION})"
    )


@pytest.mark.parametrize("db_version", sorted(DB_VERSION_TO_RELEASE))
def test_every_entry_round_trips(db_version: int) -> None:
    assert release_for(db_version) == DB_VERSION_TO_RELEASE[db_version]


def test_the_map_is_derived_and_not_trivial() -> None:
    """Scope attack: a generator that silently produced nothing would pass
    every test above except this one."""
    assert len(DB_VERSION_TO_RELEASE) >= 10
    assert all(isinstance(k, int) for k in DB_VERSION_TO_RELEASE)
    assert all(isinstance(v, str) for v in DB_VERSION_TO_RELEASE.values())
    # Every release at or above the floor, so nothing pre-5.0 leaked in.
    assert all(v.split(".")[0] >= "5" for v in DB_VERSION_TO_RELEASE.values())
