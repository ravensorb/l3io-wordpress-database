"""Contract tests for the invariants that cannot be caught by review.

AD-27 in particular has a failure mode that is invisible from inside this
repository: shipping an ``__init__.py`` at ``l3io/`` or ``l3io/wp/`` turns the
namespace into a regular package and makes the sibling distributions
unimportable, while every test here still passes. These tests are the only
mechanical guard.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
#: Resolved once so the subprocess calls below use a full path (ruff S607).
UV = shutil.which("uv") or "uv"

PUBLIC_MODULES = [
    "l3io.wp.database",
    "l3io.wp.database.connection",
    "l3io.wp.database.credentials",
    "l3io.wp.database.errors",
    "l3io.wp.database.identifiers",
    "l3io.wp.database.state",
]


def test_namespace_ships_no_init_in_source_tree() -> None:
    """AD-27: the only __init__.py above the area package would break siblings."""
    forbidden = [SRC / "l3io" / "__init__.py", SRC / "l3io" / "wp" / "__init__.py"]
    present = [p for p in forbidden if p.exists()]
    assert not present, (
        f"PEP 420 namespace violated by {present}. These files make l3io a regular "
        "package, shadowing the namespace and making l3io-wordpress-config and "
        "l3io-wordpress-backup unimportable once installed alongside this one."
    )


def test_only_expected_init_files_exist() -> None:
    """Derive the set from the tree rather than hand-listing it."""
    found = {p.relative_to(SRC).as_posix() for p in SRC.rglob("__init__.py")}
    assert found == {"l3io/wp/database/__init__.py"}, found


@pytest.mark.parametrize("module", PUBLIC_MODULES)
def test_public_module_imports(module: str) -> None:
    """AD-8: a base install must import every public module."""
    __import__(module)


def test_importing_the_package_does_not_import_boto3() -> None:
    """AD-8: boto3 is imported inside the method that uses it, not at module scope.

    Run in a subprocess so a boto3 already imported by the test session cannot
    mask the regression.
    """
    code = (
        "import sys; import l3io.wp.database as d; "
        "assert 'boto3' not in sys.modules, sorted(m for m in sys.modules if 'boto' in m); "
        "print('ok')"
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok" in result.stdout


def test_public_surface_is_declared() -> None:
    import l3io.wp.database as pkg

    assert pkg.__all__ == sorted(pkg.__all__), "__all__ should be sorted"
    for name in pkg.__all__:
        assert hasattr(pkg, name), f"__all__ names {name}, which is absent"


def test_py_typed_is_present() -> None:
    assert (SRC / "l3io" / "wp" / "database" / "py.typed").exists()


@pytest.mark.slow
def test_built_wheel_has_no_namespace_init(tmp_path: Path) -> None:
    """The wheel is what users install; the working tree is not.

    Installing the working tree would have passed throughout the package's
    entire six-year outage, which is the blind spot this closes.

    Built into an empty directory, and exactly one wheel asserted. This test
    used to build into the repository's dist/ and inspect ``sorted(...)[-1]``,
    which sorts versions as strings: with dev6, dev9, dev11 and dev14 present it
    inspected dev9, not the wheel it had just built, and passed with
    ``src/l3io/__init__.py`` planted.
    """
    root = SRC.parent
    subprocess.run(  # noqa: S603
        [UV, "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=root,
        check=True,
        capture_output=True,
    )
    wheels = list(tmp_path.glob("*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel, found {wheels}"
    names = zipfile.ZipFile(wheels[0]).namelist()
    assert "l3io/__init__.py" not in names
    assert "l3io/wp/__init__.py" not in names
    assert "l3io/wp/database/__init__.py" in names
    assert "l3io/wp/database/py.typed" in names


@pytest.mark.slow
def test_namespace_coexists_with_a_sibling_distribution(tmp_path: Path) -> None:
    """AD-27's failure mode is only observable with two distributions installed.

    A single-package test cannot catch it: adding l3io/__init__.py makes this
    package a regular one, shadowing the namespace so siblings become
    unimportable -- while every other test here still passes. So build a stub
    sibling that claims the same namespace, install both into one isolated
    interpreter, and assert both import and neither prefix is a regular package.
    """
    stub = tmp_path / "stub"
    (stub / "src" / "l3io" / "wp" / "stubarea").mkdir(parents=True)
    (stub / "src" / "l3io" / "wp" / "stubarea" / "__init__.py").write_text(
        "MARKER = 'stub-sibling'\n"
    )
    (stub / "pyproject.toml").write_text(
        '[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n\n'
        '[project]\nname = "l3io-wp-stubarea"\nversion = "0.0.1"\n'
        'requires-python = ">=3.11"\n\n'
        '[tool.hatch.build.targets.wheel]\npackages = ["src/l3io"]\n'
    )

    root = SRC.parent
    venv = tmp_path / "venv"
    subprocess.run(  # noqa: S603
        [UV, "venv", str(venv)],
        check=True,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603
        [UV, "pip", "install", "--python", str(venv), str(root), str(stub)],
        check=True,
        capture_output=True,
    )

    probe = (
        "import l3io, l3io.wp, l3io.wp.database, l3io.wp.stubarea as s;\n"
        "assert getattr(l3io, '__file__', None) is None, 'l3io is a regular package';\n"
        "assert getattr(l3io.wp, '__file__', None) is None, 'l3io.wp is a regular package';\n"
        "assert s.MARKER == 'stub-sibling';\n"
        "print('coexist-ok')"
    )
    python = venv / "bin" / "python"
    result = subprocess.run(  # noqa: S603
        [str(python), "-c", probe], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "coexist-ok" in result.stdout
