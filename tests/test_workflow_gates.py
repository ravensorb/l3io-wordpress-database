"""Workflow conditions a release depends on.

``publish.yml`` must start only on a three-component release tag: a floating
``v0`` or ``v0.1`` pushed by hand must never start a publish. Its release notes
must start from the previous three-component tag, because a changelog builder
left to detect its lower bound takes the nearest tag, which a floating tag on
the same commit would be -- and the notes would read "no changes".
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"
FLOATING = ["v0", "v0.1", "v1", "v1.2"]
RELEASES = ["v0.0.2", "v0.1.0", "v1.2.3"]


def _workflows() -> list[Path]:
    found = sorted([*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")])
    assert found, f"no workflows under {WORKFLOWS} -- an empty scope skips, not fails"
    return found


def _load(path: Path) -> dict[Any, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def tag_triggers(workflow: dict[Any, Any]) -> list[str]:
    # PyYAML (YAML 1.1) parses the key `on` as the boolean True.
    on = workflow.get("on", workflow.get(True)) or {}
    return list(((on.get("push") or {}) if isinstance(on, dict) else {}).get("tags", []))


def starts_a_run(tag: str, patterns: list[str]) -> bool:
    """GitHub's tag filter: the last matching pattern wins, `!` negates."""
    hit = False
    for pattern in patterns:
        if fnmatchcase(tag, pattern.removeprefix("!")):
            hit = not pattern.startswith("!")
    return hit


@pytest.mark.parametrize("path", _workflows(), ids=lambda p: p.name)
def test_no_floating_tag_starts_a_workflow(path: Path) -> None:
    patterns = tag_triggers(_load(path))
    started = [t for t in FLOATING if starts_a_run(t, patterns)]
    assert not started, f"{path.name} runs on floating tag(s) {started}: {patterns}"


def test_a_release_tag_still_starts_publish() -> None:
    patterns = tag_triggers(_load(WORKFLOWS / "publish.yml"))
    assert patterns, "publish.yml has no tag trigger -- the check above is vacuous"
    assert all(starts_a_run(t, patterns) for t in RELEASES), patterns
    assert not starts_a_run("v0.0.0", patterns), "v0.0.0 is the baseline, never a release"


def test_the_tag_filter_check_reads_negation_and_order() -> None:
    assert starts_a_run("v0.0.2", ["v*", "!v0.0.0"])
    assert not starts_a_run("v0.0.0", ["v*", "!v0.0.0"])
    assert starts_a_run("v0", ["v*"]), "a bare v* filter does start a run on a floating tag"
    assert not starts_a_run("v0", ["v*.*.*"])


def test_release_notes_never_start_from_a_floating_tag() -> None:
    job = (_load(WORKFLOWS / "publish.yml").get("jobs") or {}).get("release") or {}
    steps: list[dict[str, Any]] = job.get("steps", [])
    assert steps, "publish.yml has no release job -- this check is vacuous"
    builder = next(
        s
        for s in steps
        if str(s.get("uses", "")).startswith("LiquidLogicLabs/git-action-release-changelog-builder")
    )
    assert "steps.previous.outputs.tag" in str(builder.get("with", {}).get("from-tag", ""))
    previous = next((s for s in steps if s.get("id") == "previous"), None)
    assert previous is not None, "no step with id 'previous' computes the lower bound"
    assert "--match 'v[0-9]*.[0-9]*.[0-9]*'" in str(previous.get("run", ""))
    assert steps.index(previous) < steps.index(builder)


def _release_steps() -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for job in (_load(WORKFLOWS / "release.yml").get("jobs") or {}).values():
        steps += job.get("steps", [])
    return steps


def _index(steps: list[dict[str, Any]], action: str) -> int:
    found = [i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith(action)]
    assert found, f"release.yml has no step using {action}"
    return found[-1]


def test_floating_tags_move_after_the_release_tag_and_before_the_dispatch() -> None:
    steps = _release_steps()
    created = _index(steps, "LiquidLogicLabs/git-action-tag-create-update")
    floated = _index(steps, "LiquidLogicLabs/git-action-tag-floating-version")
    dispatched = _index(steps, "LiquidLogicLabs/git-action-trigger-workflow")
    assert created < floated < dispatched


def test_the_latest_release_lookup_ignores_floating_tags() -> None:
    steps = _release_steps()
    lookup = steps[_index(steps, "LiquidLogicLabs/git-action-tag-info")]
    assert lookup.get("with", {}).get("tag-format") == "v*.*.*"


def test_github_release_waits_on_publish_pypi_without_failing_when_skipped() -> None:
    job = (_load(WORKFLOWS / "publish.yml").get("jobs") or {}).get("release") or {}
    needs = job.get("needs") or []
    assert "publish-pypi" in needs
    assert "smoke" in needs
    condition = str(job.get("if", ""))
    assert "always()" in condition
    assert "needs.publish-pypi.result != 'failure'" in condition


def test_an_index_upload_runs_only_on_a_release_tag() -> None:
    """A dispatch from a branch would upload a .dev build, and PyPI burns the filename."""
    jobs: dict[str, Any] = _load(WORKFLOWS / "publish.yml").get("jobs") or {}
    uploads = [
        name
        for name, job in jobs.items()
        if any("pypa/gh-action-pypi-publish" in str(s.get("uses", "")) for s in job["steps"])
    ]
    assert uploads, "publish.yml uploads to no index -- this check is vacuous"
    ungated = [n for n in uploads if "startsWith(github.ref, 'refs/tags/v')" not in jobs[n]["if"]]
    assert not ungated, f"{ungated} can upload from a branch ref"
