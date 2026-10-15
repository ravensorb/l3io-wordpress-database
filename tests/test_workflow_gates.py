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
