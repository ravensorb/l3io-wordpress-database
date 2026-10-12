"""The FR-50 release gate, tools/check_name_claim.py, with the index faked.

The gate's one dangerous failure is passing when it should not, so most of these
plant a refusal: a stranger's project, a stranger on the separator variant only,
and an index that does not answer.
"""

from __future__ import annotations

import importlib.util
import urllib.error
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
OURS = "https://github.com/ravensorb/l3io-wordpress-database"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_name_claim", REPO_ROOT / "tools" / "check_name_claim.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load()


def _index(answers: dict[str, tuple[int, dict[str, Any] | None]]) -> Any:
    def fetch(url: str) -> tuple[int, dict[str, Any] | None]:
        for name, answer in answers.items():
            if f"/pypi/{name}/json" in url:
                return answer
        return 404, None

    return fetch


def _project(*urls: str) -> dict[str, Any]:
    return {"info": {"project_urls": {f"u{i}": u for i, u in enumerate(urls)}}}


def test_unclaimed_name_passes() -> None:
    assert gate.check("l3io-wordpress-database", {OURS.lower()}, "pypi", _index({})) == []


def test_name_held_by_this_repository_passes() -> None:
    fetch = _index({"l3io-wordpress-database": (200, _project(OURS + "/"))})
    assert gate.check("l3io-wordpress-database", {OURS.lower()}, "pypi", fetch) == []


def test_name_held_by_someone_else_fails() -> None:
    fetch = _index({"l3io-wordpress-database": (200, _project("https://example.org/x"))})
    [problem] = gate.check("l3io-wordpress-database", {OURS.lower()}, "pypi", fetch)
    assert "someone else" in problem


def test_a_stranger_on_the_separator_variant_fails() -> None:
    fetch = _index({"l3iowordpressdatabase": (200, _project("https://example.org/x"))})
    [problem] = gate.check("l3io-wordpress-database", {OURS.lower()}, "pypi", fetch)
    assert problem.startswith("l3iowordpressdatabase:")


@pytest.mark.parametrize("status", [401, 500, 503])
def test_an_unexpected_status_fails_closed(status: int) -> None:
    fetch = _index({"l3io-wordpress-database": (status, None)})
    [problem] = gate.check("l3io-wordpress-database", {OURS.lower()}, "testpypi", fetch)
    assert "unconfirmed" in problem


def test_an_index_that_does_not_answer_fails_closed() -> None:
    def fetch(url: str) -> tuple[int, dict[str, Any] | None]:
        reason = "no route to host"
        raise urllib.error.URLError(reason)

    problems = gate.check("l3io-wordpress-database", {OURS.lower()}, "pypi", fetch)
    assert len(problems) == 2
    assert all("unconfirmed" in p for p in problems)


def test_main_reads_name_and_urls_from_pyproject() -> None:
    """The real pyproject, so a renamed distribution or repository is what gets checked."""
    seen: list[str] = []

    def fetch(url: str) -> tuple[int, dict[str, Any] | None]:
        seen.append(url)
        return 200, _project(OURS)

    assert gate.main(["--index", "pypi"], fetch=fetch) == 0
    assert seen == [
        "https://pypi.org/pypi/l3io-wordpress-database/json",
        "https://pypi.org/pypi/l3iowordpressdatabase/json",
    ]


# ------------------------------------------------------------------ wiring


def ungated_uploads(workflows: Path) -> list[str]:
    """Every pypa upload step not preceded, in its job, by the gate for its index.

    Scope: steps using ``pypa/gh-action-pypi-publish``, in every workflow. That
    action is the only path to PyPI or TestPyPI here; publish.yml's ``uv publish``
    goes to the Gitea mirror, which the gate's docstring puts out of scope.
    """
    bad: list[str] = []
    for workflow in sorted(workflows.glob("*.y*ml")):
        document = yaml.safe_load(workflow.read_text(encoding="utf-8")) or {}
        for job_id, job in (document.get("jobs") or {}).items():
            gated: set[str] = set()
            for step in (job or {}).get("steps") or []:
                run = str(step.get("run", ""))
                if "tools/check_name_claim.py" in run:
                    gated.update(gate.INDEXES.keys() & set(run.replace("=", " ").split()))
                if not str(step.get("uses", "")).startswith("pypa/gh-action-pypi-publish"):
                    continue
                target = str((step.get("with") or {}).get("repository-url", ""))
                index = "testpypi" if "test.pypi.org" in target else "pypi"
                if index not in gated:
                    bad.append(f"{workflow.name}:{job_id} uploads to {index} ungated")
    return bad


def _uploads(workflows: Path) -> int:
    return sum(
        str(step.get("uses", "")).startswith("pypa/gh-action-pypi-publish")
        for w in workflows.glob("*.y*ml")
        for job in (
            (yaml.safe_load(w.read_text(encoding="utf-8")) or {}).get("jobs") or {}
        ).values()
        for step in (job or {}).get("steps") or []
    )


def test_every_index_upload_runs_the_gate_first() -> None:
    assert _uploads(WORKFLOWS), "no pypa upload step found -- this guard is vacuous"
    assert ungated_uploads(WORKFLOWS) == []


def test_an_upload_in_an_unlisted_workflow_is_caught(tmp_path: Path) -> None:
    """Scope attack: a new workflow, and a gate for the wrong index in the same job."""
    (tmp_path / "later.yaml").write_text(
        "on: push\njobs:\n  up:\n    steps:\n"
        "      - run: python3 tools/check_name_claim.py --index pypi\n"
        "      - uses: pypa/gh-action-pypi-publish@release/v1\n"
        "        with: { repository-url: https://test.pypi.org/legacy/ }\n",
        encoding="utf-8",
    )
    assert ungated_uploads(tmp_path) == ["later.yaml:up uploads to testpypi ungated"]


def test_a_gate_after_the_upload_does_not_count(tmp_path: Path) -> None:
    (tmp_path / "late.yml").write_text(
        "on: push\njobs:\n  up:\n    steps:\n"
        "      - uses: pypa/gh-action-pypi-publish@release/v1\n"
        "      - run: python3 tools/check_name_claim.py --index pypi\n",
        encoding="utf-8",
    )
    assert ungated_uploads(tmp_path) == ["late.yml:up uploads to pypi ungated"]
