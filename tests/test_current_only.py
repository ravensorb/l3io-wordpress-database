"""The repository describes only the current package (spec §14).

History that justified a rule keeps its check, and the rule's reason is stated as
a present-tense risk. This guard fails on words that narrate a predecessor or cite
the retired requirements document's identifiers.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GIT = shutil.which("git") or "git"
HISTORY = re.compile(
    r"wpdatabase2|wpbackup2|predecessor|six[- ]years?|py-wordpress-database"
    r"|\bN?FR-\d+\b|\bPRD\b|\bG5\b|\b(?:the|this) rewrite\b|Cariad|original package",
    re.IGNORECASE,
)
#: Planning records and the session handoff may name history; the tombstone and its
#: test exist to name the retired package; this file names the patterns.
ALLOWED = (
    "_bmad/",
    "_bmad-output/",
    ".claude/",
    ".agents/",
    "docs/handoff/",
    "tombstone/",
    "uv.lock",
    "tests/test_current_only.py",
    "tests/test_tombstone.py",
)


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(  # noqa: S603 - fixed arguments
        [GIT, "ls-files"], cwd=root, capture_output=True, text=True, check=True
    ).stdout
    return [f for f in out.splitlines() if f]


def history_lines(root: Path, files: list[str]) -> list[str]:
    hits: list[str] = []
    for name in files:
        if name.startswith(ALLOWED):
            continue
        text = (root / name).read_bytes().decode("utf-8", "ignore")
        for lineno, line in enumerate(text.splitlines(), 1):
            if HISTORY.search(line):
                hits.append(f"{name}:{lineno}: {line.strip()[:100]}")
    return hits


def test_nothing_outside_the_records_narrates_history() -> None:
    files = tracked_files(REPO_ROOT)
    assert len(files) > 50, "git ls-files found almost nothing -- this guard is vacuous"
    assert not history_lines(REPO_ROOT, files)


def test_a_planted_narration_is_caught(tmp_path: Path) -> None:
    (tmp_path / "x.py").write_text("# the predecessor did this\n", encoding="utf-8")
    (tmp_path / "docs" / "handoff").mkdir(parents=True)
    (tmp_path / "docs" / "handoff" / "h.md").write_text("wpdatabase2\n", encoding="utf-8")
    assert history_lines(tmp_path, ["x.py", "docs/handoff/h.md"]) == [
        "x.py:1: # the predecessor did this"
    ]
