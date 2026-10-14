"""Every verdict code is asserted by some test (spec §6).

A code no test asserts can stop being emitted, or start being emitted for the
wrong condition, with the suite still green. The check reads each test file's
syntax tree: ``Code.NAME`` counts only inside an ``assert`` statement.
``test_verdict.py`` enumerates every code to check its severity, so it does
not count.
"""

from __future__ import annotations

import ast
from pathlib import Path

from l3io.wp.database import Code

TESTS = Path(__file__).resolve().parent
EXCLUDED = {"test_verdict.py", Path(__file__).name}


def asserted_codes(files: list[Path]) -> set[str]:
    found: set[str] = set()
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Assert):
                found |= {
                    n.attr
                    for n in ast.walk(node)
                    if isinstance(n, ast.Attribute)
                    and isinstance(n.value, ast.Name)
                    and n.value.id == "Code"
                }
    return found


def _test_files(root: Path) -> list[Path]:
    files = [p for p in sorted(root.rglob("test_*.py")) if p.name not in EXCLUDED]
    assert files, f"no test files under {root} -- this guard would pass vacuously"
    return files


def test_every_code_is_asserted_by_a_test() -> None:
    missing = sorted({code.name for code in Code} - asserted_codes(_test_files(TESTS)))
    assert not missing, f"no test asserts {missing}"


def test_a_code_named_outside_an_assert_does_not_count(tmp_path: Path) -> None:
    """Scope attack: a code in a list or a parametrize table proves nothing."""
    planted = tmp_path / "test_x.py"
    planted.write_text(
        "from l3io.wp.database import Code\nCODES = [Code.UNREACHABLE]\nassert Code.USER_ABSENT\n",
        encoding="utf-8",
    )
    assert asserted_codes([planted]) == {"USER_ABSENT"}
