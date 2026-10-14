"""Facts declared once in pyproject.toml must agree with every place that restates them.

Each check derives the set it examines from the tree -- every workflow, every source
file -- never from a hand-kept list, and asserts that set is non-empty before
asserting the rule over it. Each has a scope-attack test that plants a violation
somewhere a hand-kept list would not have named.

- FR-48: the supported-Python set. ``requires-python`` and the
  ``Programming Language :: Python :: 3.x`` classifiers are the declaration; every
  workflow matrix with a ``python`` axis restates it.
- The distribution a ``MissingDependencyError`` names must be one its extra really
  installs. The 2026-09-30 rename left the wpconfig extra telling users to install
  ``l3io-wp-config``, a name that no longer exists, and every test still passed.
- A console script run against the built wheel must be one pyproject declares. The
  same rename left ``make verify-wheel`` invoking ``l3io-wp-database``, so the
  target failed on ``main`` while CI, which spelled it correctly, stayed green.
"""

from __future__ import annotations

import ast
import json
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
SRC = REPO_ROOT / "src"

#: Matrix axis names that carry a Python version.
PYTHON_AXES = ("python", "python-version")

_CLASSIFIER = re.compile(r"^Programming Language :: Python :: (3\.\d+)$")
_FROM_JSON = re.compile(r"fromJSON\('(\[[^']*\])'\)")
_WHEEL_SCRIPT = re.compile(r'--with\s+"\$+wheel"\s+([A-Za-z0-9_.-]+)')


def _project() -> dict[str, Any]:
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        project: dict[str, Any] = tomllib.load(fh)["project"]
    return project


# ---------------------------------------------------------------- FR-48


def declared_pythons(project: dict[str, Any]) -> set[str]:
    return {m.group(1) for c in project["classifiers"] if (m := _CLASSIFIER.match(c))}


def _matrix_values(value: Any) -> set[str]:
    """Every version a matrix axis can take, including inside an act-collapse expression.

    ci.yml writes its axes as ``${{ vars.LOCAL_ACT && fromJSON('[...]') || fromJSON('[...]') }}``,
    so the full set is the union of every ``fromJSON`` list in the expression.
    """
    if isinstance(value, list):
        return {str(v) for v in value}
    if isinstance(value, str):
        found = _FROM_JSON.findall(value)
        if found:
            return {str(v) for blob in found for v in json.loads(blob)}
    msg = f"unrecognised matrix value {value!r}; teach this check to read it"
    raise AssertionError(msg)


def python_matrices(workflows: Path) -> dict[str, set[str]]:
    """``{"file.yml:job": versions}`` for every job whose matrix has a Python axis."""
    found: dict[str, set[str]] = {}
    for workflow in sorted(workflows.glob("*.y*ml")):
        document = yaml.safe_load(workflow.read_text(encoding="utf-8")) or {}
        for job_id, job in (document.get("jobs") or {}).items():
            matrix = ((job or {}).get("strategy") or {}).get("matrix") or {}
            if not isinstance(matrix, dict):
                continue
            for axis in PYTHON_AXES:
                if axis in matrix:
                    found[f"{workflow.name}:{job_id}"] = _matrix_values(matrix[axis])
    return found


def matrix_mismatches(workflows: Path, expected: set[str]) -> list[str]:
    return [
        f"{where} runs {sorted(got)}, classifiers declare {sorted(expected)}"
        for where, got in python_matrices(workflows).items()
        if got != expected
    ]


def test_classifiers_agree_with_requires_python() -> None:
    project = _project()
    declared = declared_pythons(project)
    assert declared, "no Python 3.x classifiers -- the checks below would compare against nothing"
    spec = SpecifierSet(project["requires-python"])
    outside = sorted(v for v in declared if Version(v) not in spec)
    assert not outside, f"classifiers {outside} fall outside requires-python {spec}"
    floor = min(declared, key=Version)
    major, minor = floor.split(".")
    below = f"{major}.{int(minor) - 1}"
    assert Version(below) not in spec, (
        f"requires-python {spec} admits {below}, but the lowest classifier is {floor}: "
        "either the floor or the classifiers are wrong"
    )


def test_every_python_matrix_matches_the_classifiers() -> None:
    expected = declared_pythons(_project())
    matrices = python_matrices(WORKFLOWS)
    assert matrices, "no workflow has a Python matrix -- this guard is vacuous"
    assert not matrix_mismatches(WORKFLOWS, expected)


def test_a_matrix_in_an_unlisted_workflow_is_caught(tmp_path: Path) -> None:
    """Scope attack: a new workflow nobody told the check about."""
    (tmp_path / "anything-new.yaml").write_text(
        "on: push\njobs:\n  j:\n    strategy:\n      matrix:\n"
        "        python-version: ['3.11', '3.12']\n",
        encoding="utf-8",
    )
    assert matrix_mismatches(tmp_path, {"3.11", "3.12", "3.13"}) == [
        "anything-new.yaml:j runs ['3.11', '3.12'], classifiers declare ['3.11', '3.12', '3.13']"
    ]


def test_the_act_collapse_expression_is_read_in_full(tmp_path: Path) -> None:
    """Both branches of the LOCAL_ACT expression count, so the GitHub set is checked."""
    (tmp_path / "ci.yml").write_text(
        "on: push\njobs:\n  j:\n    strategy:\n      matrix:\n        python: >-\n"
        "          ${{ vars.LOCAL_ACT && fromJSON('[\"3.11\"]')\n"
        '              || fromJSON(\'["3.11","3.14"]\') }}\n',
        encoding="utf-8",
    )
    assert python_matrices(tmp_path) == {"ci.yml:j": {"3.11", "3.14"}}


# ---------------------------------------------------- MissingDependencyError


def missing_dependency_calls(root: Path) -> list[tuple[str, str, str]]:
    """``(location, extra, distribution)`` for every literal MissingDependencyError call."""
    calls: list[tuple[str, str, str]] = []
    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name != "MissingDependencyError":
                continue
            kwargs = {k.arg: k.value for k in node.keywords}
            extra, dist = kwargs.get("extra"), kwargs.get("distribution")
            where = f"{path.relative_to(root)}:{node.lineno}"
            assert isinstance(extra, ast.Constant) and isinstance(dist, ast.Constant), (
                f"{where}: pass extra= and distribution= as literals so they can be checked"
            )
            calls.append((where, str(extra.value), str(dist.value)))
    return calls


def undeclared_distributions(root: Path, extras: dict[str, list[str]]) -> list[str]:
    bad: list[str] = []
    for where, extra, dist in missing_dependency_calls(root):
        provided = {canonicalize_name(Requirement(r).name) for r in extras.get(extra, [])}
        if canonicalize_name(dist) not in provided:
            bad.append(f"{where}: extra {extra!r} installs {sorted(provided)}, not {dist!r}")
    return bad


def test_every_missing_dependency_names_what_its_extra_installs() -> None:
    extras = _project()["optional-dependencies"]
    assert missing_dependency_calls(SRC), "no MissingDependencyError calls found -- vacuous"
    assert not undeclared_distributions(SRC, extras)


def test_a_retired_distribution_name_is_caught(tmp_path: Path) -> None:
    """Scope attack: a call in a file nobody listed, naming the pre-rename distribution."""
    (tmp_path / "deep").mkdir()
    (tmp_path / "deep" / "x.py").write_text(
        'raise MissingDependencyError(extra="wpconfig", distribution="l3io-wp-config")\n',
        encoding="utf-8",
    )
    assert undeclared_distributions(tmp_path, {"wpconfig": ["l3io-wordpress-config>=0.0.2"]}) == [
        "deep/x.py:1: extra 'wpconfig' installs ['l3io-wordpress-config'], not 'l3io-wp-config'"
    ]


# ------------------------------------------------------------ console scripts


def wheel_script_invocations(files: list[Path]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for path in files:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in _WHEEL_SCRIPT.finditer(line):
                found.append((f"{path.name}:{lineno}", match.group(1)))
    return found


def test_every_script_run_against_the_wheel_is_declared() -> None:
    files = [REPO_ROOT / "Makefile", *sorted(WORKFLOWS.glob("*.y*ml"))]
    declared = set(_project()["scripts"]) | {"python"}
    invocations = wheel_script_invocations(files)
    assert any(name != "python" for _, name in invocations), (
        "no console script is run against the wheel anywhere -- this guard is vacuous"
    )
    bad = [f"{where} runs {name!r}" for where, name in invocations if name not in declared]
    assert not bad, f"not a declared console script {sorted(declared - {'python'})}: {bad}"


@pytest.mark.parametrize("dollars", ["$", "$$"])
def test_a_retired_script_name_is_caught(tmp_path: Path, dollars: str) -> None:
    """Scope attack: Make doubles the dollar sign, a workflow does not; both must match."""
    planted = tmp_path / "Makefile"
    planted.write_text(f'\tuv run --with "{dollars}wheel" l3io-wp-database --version\n')
    assert wheel_script_invocations([planted]) == [("Makefile:1", "l3io-wp-database")]


# ------------------------------------------------------------ upper bounds


def unbounded(requirements: list[str]) -> list[str]:
    """Requirements with nothing capping what a resolver may pick (AD-15)."""
    caps = {"<", "<=", "==", "===", "~="}
    return [
        r for r in requirements if not any(s.operator in caps for s in Requirement(r).specifier)
    ]


def test_every_runtime_requirement_has_an_upper_bound() -> None:
    project = _project()
    declared = [
        *project["dependencies"],
        *(r for extra in project["optional-dependencies"].values() for r in extra),
    ]
    assert declared, "no requirements declared -- this guard is vacuous"
    assert not unbounded(declared)


def test_an_unbounded_requirement_is_caught() -> None:
    assert unbounded(["boto3>=1.34", "pyrage>=1.4,<2", "x==1.0", "y~=2.1"]) == ["boto3>=1.34"]


# ------------------------------------------------------------ extras


#: What each extra makes importable. Hand-kept, so the test below fails when an
#: extra is added without deciding what a base install must not contain.
EXTRA_IMPORTS = {"aws": "boto3", "wpconfig": "l3io.wp.config", "encryption": "pyrage"}
_EXTRA_LEG = re.compile(r"l3io-wordpress-database\[(\w+)\] @")


def extras_verified(script: Path) -> set[str]:
    return set(_EXTRA_LEG.findall(script.read_text(encoding="utf-8")))


def test_every_extra_has_an_install_leg() -> None:
    extras = set(_project()["optional-dependencies"])
    assert extras, "no extras declared -- this guard is vacuous"
    assert set(EXTRA_IMPORTS) == extras
    assert extras_verified(REPO_ROOT / "tools" / "verify_extras.sh") == extras


def test_the_base_install_check_forbids_every_extras_import() -> None:
    for path in (REPO_ROOT / "Makefile", WORKFLOWS / "ci.yml"):
        text = path.read_text(encoding="utf-8")
        missing = [
            m for m in EXTRA_IMPORTS.values() if f"'{m}'" not in text and f'"{m}"' not in text
        ]
        assert not missing, f"{path.name}'s base-install check does not forbid {missing}"


def test_an_extra_without_a_leg_is_caught(tmp_path: Path) -> None:
    script = tmp_path / "verify_extras.sh"
    script.write_text('uv run --with "l3io-wordpress-database[aws] @ $url" python -c 1\n')
    assert extras_verified(script) == {"aws"}
