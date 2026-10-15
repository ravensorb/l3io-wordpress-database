"""The sdist carries the package and its metadata, and nothing of the workspace."""

from __future__ import annotations

import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
UV = shutil.which("uv") or "uv"
ALLOWED = ("src/l3io/", "pyproject.toml", "README.md", "LICENSE", "PKG-INFO", ".gitignore")
REQUIRED = ("src/l3io/wp/database/__init__.py", "pyproject.toml", "README.md", "LICENSE")


def strays(members: list[str]) -> list[str]:
    inside = [name.split("/", 1)[1] for name in members if "/" in name]
    return [name for name in inside if not name.startswith(ALLOWED)]


def test_a_workspace_file_in_the_sdist_is_caught() -> None:
    planted = ["pkg-0.1.0/src/l3io/wp/database/cli.py", "pkg-0.1.0/_bmad/config.yaml"]
    assert strays(planted) == ["_bmad/config.yaml"]


@pytest.mark.slow
def test_the_sdist_holds_only_the_package(tmp_path: Path) -> None:
    subprocess.run(  # noqa: S603
        [UV, "build", "--sdist", "--no-sources", "--out-dir", str(tmp_path), str(ROOT)],
        check=True,
        capture_output=True,
    )
    [sdist] = tmp_path.glob("*.tar.gz")
    with tarfile.open(sdist) as archive:
        members = [m.name for m in archive.getmembers() if m.isfile()]
    assert strays(members) == []
    inside = {name.split("/", 1)[1] for name in members}
    for name in REQUIRED:
        assert name in inside, name
