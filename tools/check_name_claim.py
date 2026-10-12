"""Release gate (FR-50): refuse to publish under a name somebody else holds.

Run before every upload to PyPI or TestPyPI. Both burn a name, so a conflict
found after upload is unrecoverable. The name and repository URL are read from
``pyproject.toml``, never passed in, so the gate cannot check a stale copy of
either.

For the distribution name, and for its separator-stripped form (PyPI rejects a
name too similar to an existing one, and stripping ``-``, ``_`` and ``.`` is
the dominant case), the index's JSON API must answer one of:

- 404: unclaimed. Passes; this is the first upload.
- 200, with a project URL equal to this repository's: ours. Passes.
- 200, with no such URL: someone else's. Fails.
- anything else, or no answer: the claim cannot be confirmed. Fails, because a
  gate that passes when it cannot see is the failure it exists to prevent.

Scope, stated so it is not mistaken for more. It does not cover the Gitea mirror.
That index is namespaced to our own organisation, so nobody else can hold a
name there; a version collision there is a different question, and
publish.yml's mirror job answers it. It does not attempt PyPI's full confusable
normalisation (for example ``l``/``1`` or ``o``/``0``); only the separator
variant is checked.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

INDEXES = {
    "pypi": "https://pypi.org/pypi/{name}/json",
    "testpypi": "https://test.pypi.org/pypi/{name}/json",
}

#: ``fetch(url) -> (status, parsed body or None)``. Injected so tests need no network.
Fetch = Callable[[str], tuple[int, dict[str, Any] | None]]


def canonical(name: str) -> str:
    """PEP 503 normalisation, the form every index compares names in."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _normalise_url(url: str) -> str:
    return url.strip().lower().removesuffix("/").removesuffix(".git")


def http_fetch(url: str) -> tuple[int, dict[str, Any] | None]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            body: dict[str, Any] = json.load(response)
            return response.status, body
    except urllib.error.HTTPError as exc:
        return exc.code, None


def project_facts(pyproject: Path) -> tuple[str, set[str]]:
    with pyproject.open("rb") as fh:
        project: dict[str, Any] = tomllib.load(fh)["project"]
    urls = {_normalise_url(u) for u in (project.get("urls") or {}).values()}
    if not urls:
        msg = "pyproject.toml declares no [project.urls]; ownership cannot be recognised"
        raise SystemExit(msg)
    return project["name"], urls


def check(name: str, our_urls: set[str], index: str, fetch: Fetch) -> list[str]:
    """Return one problem per name the index will not let us publish under."""
    problems: list[str] = []
    variants = dict.fromkeys([canonical(name), re.sub(r"[-_.]+", "", name).lower()])
    for variant in variants:
        url = INDEXES[index].format(name=variant)
        try:
            status, body = fetch(url)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            problems.append(f"{variant}: {index} did not answer ({exc}); claim unconfirmed")
            continue
        if status == 404:
            print(f"ok  {index}: {variant} is unclaimed")
            continue
        if status != 200 or body is None:
            problems.append(f"{variant}: {index} answered HTTP {status}; claim unconfirmed")
            continue
        info = body.get("info") or {}
        theirs = {
            _normalise_url(u)
            for u in [*(info.get("project_urls") or {}).values(), info.get("home_page") or ""]
            if u
        }
        if theirs & our_urls:
            print(f"ok  {index}: {variant} is held by this repository")
        else:
            problems.append(
                f"{variant}: held on {index} by someone else ({sorted(theirs) or 'no URLs'})"
            )
    return problems


def main(argv: list[str] | None = None, fetch: Fetch = http_fetch) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--index", choices=sorted(INDEXES), required=True)
    parser.add_argument("--pyproject", type=Path, default=ROOT / "pyproject.toml")
    args = parser.parse_args(argv)
    name, urls = project_facts(args.pyproject)
    problems = check(name, urls, args.index, fetch)
    for problem in problems:
        print(f"FAIL {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
