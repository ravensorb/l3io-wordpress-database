"""The public surface: no Wp prefix, no name colliding with a submodule."""

from __future__ import annotations

import pkgutil
from pathlib import Path

import l3io.wp.database as pkg

SRC = Path(pkg.__file__).parent


def test_no_public_name_has_a_wp_prefix() -> None:
    offenders = [n for n in pkg.__all__ if n.startswith("Wp") and n != "WpConfigFile"]
    assert offenders == []


def test_no_root_export_shadows_a_submodule() -> None:
    modules = {m.name for m in pkgutil.iter_modules([str(SRC)])}
    assert modules, "no submodules found -- this guard is vacuous"
    assert modules.isdisjoint(pkg.__all__)


def test_every_exported_name_exists() -> None:
    for name in pkg.__all__:
        assert hasattr(pkg, name), name


def test_old_names_are_gone() -> None:
    for name in (
        "WpDatabase",
        "WpConnection",
        "WpCredentials",
        "WpConfigSource",
        "WpDatabaseError",
        "WpDatabaseVersion",
    ):
        assert not hasattr(pkg, name), name
