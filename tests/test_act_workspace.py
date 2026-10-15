"""Nothing a job that ``make ci`` replays may write into the working tree.

act binds the developer's checkout as the workspace and runs as root, so a file a
job writes there lands in the host tree, root-owned, and persists between runs.
Observed here: a root-owned ``.coverage`` and ``coverage.xml``, and wheels that
accumulated in ``dist/``. The same holds for ``UV_PROJECT_ENVIRONMENT``, which
every job already points at ``/tmp``.

Scope: the workflows ``make ci`` runs for real, read from the ``-W`` arguments in
the Makefile's ``ACT_FLAGS`` rather than listed here. Within them, every
``uv build`` must name an ``--out-dir`` under ``/tmp``, and every job that runs
pytest with ``--cov`` must set ``COVERAGE_FILE`` under ``/tmp`` and write any XML
report there, and the workflow must set ``PYTHONDONTWRITEBYTECODE``, because the
first replay with the other two fixed still left 13 root-owned ``.pyc`` files in
``src/`` and ``tests/``. The tools' caches are the same hazard: ruff writes a new
root-owned file into ``.ruff_cache`` for any file it has not seen, and on a fresh
clone ``.ruff_cache``, ``.mypy_cache`` and ``.pytest_cache`` would all be created
by root. So the workflow points ruff's and mypy's caches under ``/tmp`` and turns
pytest's off. Other writes (a stray ``open()`` in a step) are not covered.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

_ACT_FLAGS = re.compile(r"^ACT_FLAGS\s*\?=\s*(.*)$", re.MULTILINE)
#: Compared against, never created -- hence the one S108 exemption.
_SCRATCH = "/tmp/"  # noqa: S108
_VAR = re.compile(r"^\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?$")
#: Tool caches that default to the working tree, each pointed at /tmp by this variable.
_CACHE_DIRS = ("RUFF_CACHE_DIR", "MYPY_CACHE_DIR")
#: A workflow env that satisfies every workflow-level rule, for the planted tests.
_CLEAN_ENV = (
    "env: { PYTHONDONTWRITEBYTECODE: '1', RUFF_CACHE_DIR: /tmp/r, MYPY_CACHE_DIR: /tmp/m,"
    " PYTEST_ADDOPTS: -p no:cacheprovider }\n"
)


def replayed_workflows(makefile: Path) -> list[Path]:
    match = _ACT_FLAGS.search(makefile.read_text(encoding="utf-8"))
    assert match, "Makefile has no ACT_FLAGS -- cannot tell what `make ci` replays"
    words = shlex.split(match.group(1))
    paths = [words[i + 1] for i, w in enumerate(words) if w == "-W" and i + 1 < len(words)]
    return [makefile.parent / p for p in paths]


def _resolve(value: str, env: dict[str, Any]) -> str:
    match = _VAR.match(value)
    return str(env.get(match.group(1), value)) if match else value


def workspace_writes(workflow: Path) -> list[str]:
    document = yaml.safe_load(workflow.read_text(encoding="utf-8")) or {}
    bad: list[str] = []
    workflow_env: dict[str, Any] = document.get("env") or {}
    if str(workflow_env.get("PYTHONDONTWRITEBYTECODE", "")) != "1":
        bad.append(f"{workflow.name}: no workflow-level PYTHONDONTWRITEBYTECODE: '1'")
    for var in _CACHE_DIRS:
        if not str(workflow_env.get(var, "")).startswith(_SCRATCH):
            bad.append(f"{workflow.name}: no workflow-level {var} under /tmp")
    if "no:cacheprovider" not in str(workflow_env.get("PYTEST_ADDOPTS", "")):
        bad.append(f"{workflow.name}: pytest's cache is not disabled in PYTEST_ADDOPTS")
    for job_id, job in (document.get("jobs") or {}).items():
        job_env: dict[str, Any] = (job or {}).get("env") or {}
        for index, step in enumerate((job or {}).get("steps") or []):
            env = {**job_env, **(step.get("env") or {})}
            run = str(step.get("run", ""))
            where = f"{workflow.name}:{job_id}[step {index}]"
            for line in run.splitlines():
                if "uv build" not in line:
                    continue
                words = shlex.split(line)
                out = words[words.index("--out-dir") + 1] if "--out-dir" in words else None
                if out is None or not _resolve(out, env).startswith(_SCRATCH):
                    bad.append(f"{where}: uv build writes to {out or 'dist/'}, not /tmp")
            if "--cov" in run:
                if not str(env.get("COVERAGE_FILE", "")).startswith(_SCRATCH):
                    bad.append(f"{where}: --cov without COVERAGE_FILE under /tmp")
                for report in re.findall(r"--cov-report=xml(\S*)", run):
                    if not report.startswith(":" + _SCRATCH):
                        bad.append(f"{where}: XML coverage report lands in the working tree")
    return bad


def test_make_ci_jobs_write_nothing_into_the_working_tree() -> None:
    workflows = replayed_workflows(REPO_ROOT / "Makefile")
    assert workflows, "ACT_FLAGS names no workflow -- this guard is vacuous"
    assert all(w.is_file() for w in workflows), f"ACT_FLAGS names a missing file: {workflows}"
    assert [b for w in workflows for b in workspace_writes(w)] == []


def test_a_build_into_the_tree_is_caught(tmp_path: Path) -> None:
    planted = tmp_path / "wf.yml"
    planted.write_text(
        "on: push\n" + _CLEAN_ENV + "jobs:\n  b:\n    env: { DIST_DIR: dist-verify }\n    steps:\n"
        "      - run: uv build --no-sources\n"
        '      - run: uv build --out-dir "$DIST_DIR"\n',
        encoding="utf-8",
    )
    assert workspace_writes(planted) == [
        "wf.yml:b[step 0]: uv build writes to dist/, not /tmp",
        "wf.yml:b[step 1]: uv build writes to $DIST_DIR, not /tmp",
    ]


def test_coverage_into_the_tree_is_caught(tmp_path: Path) -> None:
    planted = tmp_path / "wf.yml"
    planted.write_text(
        "on: push\n" + _CLEAN_ENV + "jobs:\n  t:\n    steps:\n"
        "      - run: uv run pytest --cov=x --cov-report=xml\n",
        encoding="utf-8",
    )
    assert workspace_writes(planted) == [
        "wf.yml:t[step 0]: --cov without COVERAGE_FILE under /tmp",
        "wf.yml:t[step 0]: XML coverage report lands in the working tree",
    ]


def test_scope_follows_the_makefile(tmp_path: Path) -> None:
    """Scope attack: a second -W added to ACT_FLAGS is examined without editing this file."""
    makefile = tmp_path / "Makefile"
    makefile.write_text("ACT_FLAGS ?= --var-file v -W a.yml -W .github/workflows/b.yml\n")
    assert replayed_workflows(makefile) == [
        tmp_path / "a.yml",
        tmp_path / ".github/workflows/b.yml",
    ]


def test_bytecode_written_into_the_tree_is_caught(tmp_path: Path) -> None:
    planted = tmp_path / "wf.yml"
    planted.write_text("on: push\njobs: {}\n", encoding="utf-8")
    assert workspace_writes(planted)[0] == "wf.yml: no workflow-level PYTHONDONTWRITEBYTECODE: '1'"


def test_tool_caches_in_the_tree_are_caught(tmp_path: Path) -> None:
    planted = tmp_path / "wf.yml"
    planted.write_text(
        "on: push\nenv: { PYTHONDONTWRITEBYTECODE: '1', RUFF_CACHE_DIR: .ruff_cache }\njobs: {}\n",
        encoding="utf-8",
    )
    assert workspace_writes(planted) == [
        "wf.yml: no workflow-level RUFF_CACHE_DIR under /tmp",
        "wf.yml: no workflow-level MYPY_CACHE_DIR under /tmp",
        "wf.yml: pytest's cache is not disabled in PYTEST_ADDOPTS",
    ]
