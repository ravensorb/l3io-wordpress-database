"""The wpdatabase2 tombstone: installs nothing, and its import names the successor."""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

TOMBSTONE = Path(__file__).resolve().parent.parent / "tombstone" / "wpdatabase2"
UV = shutil.which("uv") or "uv"


@pytest.mark.slow
def test_the_tombstone_depends_on_nothing_and_points_at_its_successor(tmp_path: Path) -> None:
    subprocess.run(  # noqa: S603
        [UV, "build", "--wheel", "--out-dir", str(tmp_path), str(TOMBSTONE)],
        check=True,
        capture_output=True,
    )
    [wheel] = tmp_path.glob("wpdatabase2-0.0.16-*.whl")
    metadata = zipfile.ZipFile(wheel).read("wpdatabase2-0.0.16.dist-info/METADATA").decode()
    assert "Requires-Dist" not in metadata
    assert "l3io-wordpress-database" in metadata
    imported = subprocess.run(  # noqa: S603
        [
            UV,
            "run",
            "--isolated",
            "--no-project",
            "--with",
            str(wheel),
            "python",
            "-c",
            "import wpdatabase2",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert imported.returncode != 0
    assert "l3io-wordpress-database" in imported.stderr
