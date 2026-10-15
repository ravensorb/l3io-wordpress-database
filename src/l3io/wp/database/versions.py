"""Interpreting WordPress's ``db_version``.

WordPress stores a schema revision in its options table. A hand-maintained
dictionary mapping it to a release number stops at whatever release its author
last added, and then returns ``None`` for every WordPress after it: it quietly
stops working rather than merely ageing.

The map is now derived from the source of truth and committed as generated
data, so the runtime needs no network. See ``tools/generate_version_map.py``;
regenerating is a maintenance task, not a deployment step.

Two properties worth stating:

* **The floor is WordPress 5.0**, which is a support decision rather than a
  limit of the derivation -- ``$wp_db_version`` is readable back to 2.0 if the
  floor ever needs lowering. Every one of the 328 releases at or above 5.0
  yields a value, so the map has no gaps within its supported range. Anything
  below the floor reports ``None`` and is distinguishable via
  :attr:`SchemaVersion.is_older_than_supported`.
* **The mapping is many-to-one.** Several releases share a ``db_version``
  (7.0 and 7.1 both report 61833), so a value identifies the release that
  *introduced* that schema, not the exact release installed.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass

from ._version_map import DB_VERSION_TO_RELEASE, MIN_RELEASE

#: Sorted db_version values, for the bisecting lookup below.
_KNOWN: list[int] = sorted(DB_VERSION_TO_RELEASE)

#: The db_version of the oldest supported release.
FLOOR_DB_VERSION: int = _KNOWN[0]

#: The db_version of the newest release the committed map knows about.
CEILING_DB_VERSION: int = _KNOWN[-1]

#: The oldest WordPress release this package reports on.
SUPPORTED_FROM: str = MIN_RELEASE


def release_for(db_version: int) -> str | None:
    """The WordPress release that introduced this schema revision.

    Returns the highest known release whose ``db_version`` is less than or
    equal to the one observed -- not an exact-match lookup, because a site can
    report a value between two releases (a development build), and because the
    map is many-to-one.

    Comparison is numeric. The original stored these values as strings, where
    ``'9872' <= '48748'`` is ``False``, so an ordered lookup over the old map
    would have been wrong even where its data was right.

    Returns ``None`` below :data:`FLOOR_DB_VERSION`.
    """
    if db_version < FLOOR_DB_VERSION:
        return None
    index = bisect.bisect_right(_KNOWN, db_version) - 1
    return DB_VERSION_TO_RELEASE[_KNOWN[index]]


@dataclass(frozen=True, slots=True)
class SchemaVersion:
    """A WordPress schema revision read from a site's options table."""

    db_version: int

    @property
    def release(self) -> str | None:
        """The WordPress release that introduced this schema, if supported.

        A plain property, not cached: `slots=True` leaves no `__dict__` for
        functools to cache into, and a bisect over a handful of entries is not
        worth caching anyway.
        """
        return release_for(self.db_version)

    @property
    def is_newer_than_known(self) -> bool:
        """Whether this schema postdates the committed map.

        Distinct from unsupported: the map needs regenerating, rather than the
        site being too old to report on.
        """
        return self.db_version > CEILING_DB_VERSION

    @property
    def is_older_than_supported(self) -> bool:
        """Whether this site predates the oldest supported release."""
        return self.db_version < FLOOR_DB_VERSION

    def __str__(self) -> str:
        if self.is_older_than_supported:
            return f"db_version {self.db_version} (older than WordPress {SUPPORTED_FROM})"
        if self.release is None:  # pragma: no cover - unreachable above the floor
            return f"db_version {self.db_version} (no known release)"
        suffix = " or newer" if self.is_newer_than_known else ""
        return f"WordPress {self.release}{suffix} (db_version {self.db_version})"
