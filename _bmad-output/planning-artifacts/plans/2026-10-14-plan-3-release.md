# Plan 3 of 3 — Release Readiness and Retirement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring `main` to the state from which Shawn can publish 0.1.0: every spec §11–§14 gate is mechanical and green, the repository describes only the current package, the predecessor's name has a tombstone ready to publish, and the remote housekeeping is done — without publishing anything.

**Architecture:** Mostly declarations, workflows and documents, each pinned by a test in the style of `tests/test_declared_facts.py`: derive the scope from the tree, assert the scope is non-empty, then assert the rule, and prove the check with a planted violation. Two small refactors make the last unasserted verdict codes testable without a server. Remote changes are a separate controller-only task, each confirmed by Shawn immediately before it runs.

**Tech Stack:** Python 3.11–3.14, uv 0.11.6, hatchling + hatch-vcs, pytest + pytest-cov, PyYAML, GitHub Actions (replayed under act), `gh`.

**Spec:** `_bmad-output/planning-artifacts/spec/2026-10-12-l3io-wordpress-database-design.md` (§6, §7.2, §11, §12, §13, §14, §15, §17)

**Plan series:** Plan 1 (merged) — core API. Plan 2 (merged) — export, import, encryption. Plan 3 (this) — release readiness and retirement.

## Global Constraints

- Python `>=3.11`; the supported set is exactly 3.11, 3.12, 3.13 and 3.14, declared by classifiers and run by every CI matrix (spec §11).
- Every runtime and extra requirement carries an upper bound (AD-15, spec §12): `PyMySQL[rsa]>=1.2,<2`, `structlog>=26.1,<27`, `opentelemetry-api>=1.30,<2`; `aws`: `boto3>=1.34,<2`; `wpconfig`: `l3io-wordpress-config>=0.1.0,<0.2`; `encryption`: `pyrage>=1.4,<2`.
- Never add `__init__.py` at `src/l3io/` or `src/l3io/wp/` (AD-27).
- Never publish (PyPI, TestPyPI, the Gitea registry, or the tombstone). Never push. No remote change of any kind outside Task 13, which the controller runs with Shawn confirming each step immediately before it runs.
- Releases are built with `uv build --no-sources`; no VCS dependency may reach published metadata (`tools/check_dist_metadata.py`).
- uv is pinned `==0.11.6`.
- Use the `make` targets; `make check` passes before every commit; stage files by explicit path, never `git add -A` (the repository owner commits concurrently).
- `main` describes only the current package. Predecessor material is read from the `legacy/main` branch and never re-added (spec §14).
- No password in an argument vector, a child's environment, a file, a log record, a span, an exception message, captured stderr or a `repr` (spec §2.4).

## Spec amendments this plan makes (applied in Task 11)

1. §7.2: the account is created with `CREATE USER` after the administrator's catalog shows it absent (not `CREATE USER IF NOT EXISTS`). A user name may not contain `'`.
2. §12: `wpconfig` is `l3io-wordpress-config>=0.1.0,<0.2` — 0.1.0 is the first config release with the define-parser fix, so the old `>=X,<0.1` cannot hold.
3. §12: the per-extra install check takes `l3io-wordpress-config` from its GitHub release wheel until config is on PyPI; the extra's own specifier must still accept it.
4. §12: `publish.yml` starts only on three-component tags (`v*.*.*`, never `v0.0.0`), and release notes start from the previous three-component tag.
5. §13: the coverage floor is 87% line coverage, enforced on every CI run that measures coverage (the integration legs measure 89% on MySQL 8.4). `tests/test_codes_asserted.py` is the every-code check; `tests/test_readme.py` and `tests/test_current_only.py` keep the documentation honest.
6. §14: the tombstone's source is `tombstone/wpdatabase2/`; publishing it is Shawn's step, after 0.1.0 is on PyPI.

## Review Focus

1. **A bare install that pulls `pyrage`.** The base-install check forbids `boto3`, `botocore` and `l3io.wp.config` but not `pyrage`, so the `encryption` extra could leak into core unnoticed. Pinned in Task 4 (`test_the_base_install_check_forbids_every_extras_import`).
2. **A user copying the README.** Today it imports `WpConnection`, `WpCredentials` and `WpDatabase`, none of which exist, and shows flags the CLI rejects. Pinned in Task 8 (`test_every_python_example_imports_only_exported_names`, `test_every_command_line_example_parses`).
3. **`[wpconfig]` resolving a config that misreads `define('DB_PASSWORD', 'ab);cd')` as `'ab`.** Config v0.0.2 does exactly that. Pinned in Task 2 (`test_a_password_containing_paren_semicolon_is_read_whole`) and in Task 4's `wpconfig` install leg.
4. **A hand-pushed floating tag (`v0`, `v0.1`) starting a publish.** `publish.yml` triggers on `v*`. Pinned in Task 6 (`test_no_floating_tag_starts_a_workflow`).
5. **A WordPress user name containing `'`.** `grantee()` does not escape it, so the grant is never found and `ensure` re-grants on every run. Pinned in Task 7 (`test_a_user_name_with_a_quote_is_refused`).

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `src/l3io/wp/database/provision.py`, `transfer.py`; `tests/test_codes_asserted.py`, `test_provision_plan.py`, `test_transfer_engine.py` | every verdict code asserted | 1 |
| `pyproject.toml`, `uv.lock`; `tests/test_declared_facts.py`, `test_wpconfig.py` | upper bounds; config `v0.1.0` | 2 |
| `pyproject.toml`, `.github/workflows/ci.yml`, `publish.yml` | Python 3.14 | 3 |
| `tools/verify_extras.sh`, `Makefile`, `.github/workflows/ci.yml`; `tests/test_declared_facts.py` | per-extra install check | 4 |
| `pyproject.toml`; `tests/test_declared_facts.py` | coverage floor | 5 |
| `.github/workflows/publish.yml`; `tests/test_workflow_gates.py` | tag filter; release-notes lower bound | 6 |
| `src/l3io/wp/database/identifiers.py`, `Makefile`; `tests/test_identifiers.py`, `test_make_targets.py` | quote in user names; interrupted transfer run | 7 |
| `README.md`, `LICENSE`, `docs/adr/*`; deletions; `tests/test_readme.py` | documentation | 8 |
| every file the guard names; `tests/test_current_only.py` | current-only sweep | 9 |
| `tombstone/wpdatabase2/*`; `tests/test_tombstone.py` | `wpdatabase2` 0.0.16 | 10 |
| spec, `docs/handoff/wordpress-database.md` | amendments, handoff, verification | 11 |
| `AGENTS.md` | managed block refresh (interactive) | 12 |
| remote only | housekeeping (controller, confirmed) | 13 |

---

### Task 0: Branch

- [ ] **Step 1:** `git switch -c feat/plan-3-release main` — Expected: on the new branch, clean tree.

---

### Task 1: Every verdict code is asserted by a test

Spec §6: "every code to be emitted by at least one test". Five codes are asserted nowhere today: `SERVER_UNSUPPORTED`, `END_OF_LIFE_SERVER`, `CLIENT_TOOL_MISSING`, `CLIENT_SERVER_SKEW`, `PLATFORM_UNSUPPORTED`.

**Files:**
- Create: `tests/test_codes_asserted.py`
- Modify: `src/l3io/wp/database/provision.py` (`_preflight_resolved`, the server checks around lines 210–227)
- Modify: `src/l3io/wp/database/transfer.py` (`_platform_and_option_findings`, around line 267)
- Test: `tests/test_provision_plan.py`, `tests/test_transfer_engine.py`

**Interfaces:**
- Produces: `provision._server_findings(server: ServerInfo) -> list[Finding]`; `transfer.DEV_FD: Path` (module constant, `Path("/dev/fd")`).

- [ ] **Step 1: Write the guard**

```python
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
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/test_codes_asserted.py -q`
Expected: FAIL — `no test asserts ['CLIENT_SERVER_SKEW', 'CLIENT_TOOL_MISSING', 'END_OF_LIFE_SERVER', 'PLATFORM_UNSUPPORTED', 'SERVER_UNSUPPORTED']`.

- [ ] **Step 3: Write the server-finding tests** (append to `tests/test_provision_plan.py`; add `from l3io.wp.database.server import parse_version` to its imports)

Written without `parametrize` on purpose: the guard counts a code only inside an `assert`.

```python
def test_a_server_below_the_floor_is_unsupported() -> None:
    for version in ("5.7.44", "10.1.48-MariaDB"):
        [finding] = provision._server_findings(parse_version(version))
        assert finding.code is Code.SERVER_UNSUPPORTED
        assert finding.fields["version"] == version


def test_a_retired_series_is_end_of_life() -> None:
    for version in ("8.0.40", "10.2.44-MariaDB"):
        [finding] = provision._server_findings(parse_version(version))
        assert finding.code is Code.END_OF_LIFE_SERVER
        assert finding.fields["version"] == version


def test_a_current_server_has_no_server_findings() -> None:
    for version in ("8.4.6", "9.7.0", "11.4.13-MariaDB"):
        assert provision._server_findings(parse_version(version)) == []
```

- [ ] **Step 4: Write the transfer-finding tests** (append to `tests/test_transfer_engine.py`; add `from l3io.wp.database.server import ServerFamily, parse_version` and make sure `Code` is imported from `l3io.wp.database.verdict`)

```python
def test_no_client_tool_is_a_blocker_naming_those_tried(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_client, "find_tool", lambda purpose, family: None)
    server = parse_version("8.4.6")
    tool, findings = transfer._tool_findings(_client.PURPOSE_DUMP, server)
    assert tool is None
    [finding] = findings
    assert finding.code is Code.CLIENT_TOOL_MISSING
    assert finding.fields["tools"] == ", ".join(
        _client.candidates(_client.PURPOSE_DUMP, server.family)
    )


def test_a_tool_from_the_other_family_or_older_is_skew(monkeypatch: pytest.MonkeyPatch) -> None:
    for family, version in ((ServerFamily.MARIADB, (11, 4, 13)), (ServerFamily.MYSQL, (8, 0, 40))):
        tool = _client.ClientTool(
            "mysqldump", "/usr/bin/mysqldump", family, version, ".".join(map(str, version))
        )
        monkeypatch.setattr(_client, "find_tool", lambda purpose, fam, tool=tool: tool)
        found, findings = transfer._tool_findings(_client.PURPOSE_DUMP, parse_version("8.4.6"))
        assert found is tool
        assert [f.code for f in findings] == [Code.CLIENT_SERVER_SKEW]


def test_a_matching_tool_has_no_findings(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = _client.ClientTool(
        "mysqldump", "/usr/bin/mysqldump", ServerFamily.MYSQL, (8, 4, 6), "8.4.6"
    )
    monkeypatch.setattr(_client, "find_tool", lambda purpose, family: tool)
    assert transfer._tool_findings(_client.PURPOSE_DUMP, parse_version("8.4.6")) == (tool, [])


def test_no_dev_fd_is_a_blocker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(transfer, "DEV_FD", tmp_path / "absent")
    findings = transfer._platform_and_option_findings((), _client.DUMP_OPTIONS)
    assert [f.code for f in findings] == [Code.PLATFORM_UNSUPPORTED]
```

- [ ] **Step 5: Run them to see them fail**

Run: `uv run pytest tests/test_provision_plan.py tests/test_transfer_engine.py -q -k "server or tool or dev_fd"`
Expected: FAIL — `AttributeError: module 'l3io.wp.database.provision' has no attribute '_server_findings'` and `... has no attribute 'DEV_FD'`. The two `_tool_findings` tests may already pass; that is fine.

- [ ] **Step 6: Extract `_server_findings`** in `provision.py` (import `ServerInfo` from `.server` if it is not already imported), and replace the inline `if not server.is_supported: ... elif server.is_end_of_life: ...` block in `_preflight_resolved` with `findings: list[Finding] = _server_findings(server)`:

```python
def _server_findings(server: ServerInfo) -> list[Finding]:
    """A server below the floor is a blocker; one past upstream end of life, a warning."""
    if not server.is_supported:
        return [
            Finding(
                Code.SERVER_UNSUPPORTED,
                f"{server.family} {server.version_text} is below the supported floor",
                {"version": server.version_text},
            )
        ]
    if server.is_end_of_life:
        return [
            Finding(
                Code.END_OF_LIFE_SERVER,
                f"{server.family} {server.version_text} is past upstream end of life",
                {"version": server.version_text},
            )
        ]
    return []
```

- [ ] **Step 7: Add `DEV_FD`** in `transfer.py` near the other module constants, and use it in `_platform_and_option_findings` (`if not DEV_FD.is_dir():`):

```python
#: Where the option-file pipe is named for the child; absent on Windows.
DEV_FD = Path("/dev/fd")
```

- [ ] **Step 8: Run the tests**

Run: `uv run pytest tests/test_codes_asserted.py tests/test_provision_plan.py tests/test_transfer_engine.py -q`
Expected: PASS.

- [ ] **Step 9: Commit**

Run `make check` (expected: pass), then:

```bash
git add tests/test_codes_asserted.py tests/test_provision_plan.py tests/test_transfer_engine.py src/l3io/wp/database/provision.py src/l3io/wp/database/transfer.py
git commit -m "test: every verdict code is asserted by some test"
```

---

### Task 2: Upper bounds, and `l3io-wordpress-config` v0.1.0

**Files:**
- Modify: `pyproject.toml` (`[project] dependencies`, `[project.optional-dependencies]`, the comment block after it, `[tool.uv.sources]`, `[dependency-groups] dev`)
- Modify: `uv.lock` (regenerated)
- Test: `tests/test_declared_facts.py`, `tests/test_wpconfig.py`

- [ ] **Step 1: Write the bounds test** (append to `tests/test_declared_facts.py`)

```python
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
```

- [ ] **Step 2: Write the config test** (append to `tests/test_wpconfig.py`)

```python
def test_a_password_containing_paren_semicolon_is_read_whole(tmp_path: Path) -> None:
    """``l3io-wordpress-config`` before 0.1.0 read this password as ``'ab``."""
    path = write(
        tmp_path,
        "<?php\ndefine('DB_NAME', 'wp_site');\ndefine('DB_USER', 'wp');\n"
        "define('DB_PASSWORD', 'ab);cd');\ndefine('DB_HOST', 'localhost');\n",
    )
    assert WpConfigFile(path).resolve().password == "ab);cd"
```

- [ ] **Step 3: Run both to see them fail**

Run: `uv run pytest tests/test_declared_facts.py tests/test_wpconfig.py -q -k "upper_bound or paren"`
Expected: FAIL — the bounds test lists `PyMySQL[rsa]>=1.2.0`, `structlog>=26.1.0`, `opentelemetry-api>=1.30`, `boto3>=1.34`, `l3io-wordpress-config>=0.0.2`; the config test reports `"'ab" != "ab);cd"`.

- [ ] **Step 4: Bound every requirement** in `pyproject.toml`:

```toml
dependencies = [
  "PyMySQL[rsa]>=1.2,<2",
  "structlog>=26.1,<27",
  "opentelemetry-api>=1.30,<2",
]

[project.optional-dependencies]
aws = ["boto3>=1.34,<2"]
wpconfig = ["l3io-wordpress-config>=0.1.0,<0.2"]
encryption = ["pyrage>=1.4,<2"]
```

In `[dependency-groups] dev`, change `"boto3>=1.34"` to `"boto3>=1.34,<2"` and `"l3io-wordpress-config>=0.0.2"` to `"l3io-wordpress-config>=0.1.0,<0.2"`.

- [ ] **Step 5: Re-pin the source.** Delete the comment block between `encryption = [...]` and `# Mechanical enforcement of the family's uv version` (it begins `# Development and CI arrangement only`). Replace the comment above `l3io-wordpress-config = { git = ... }` in `[tool.uv.sources]` and the line itself with:

```toml
[tool.uv.sources]
# Development and CI only. l3io-wordpress-config is not on a public index, and the
# internal registry needs credentials, so a clean clone resolves it from its
# release tag. A tag is immutable in content but can be deleted, and a deleted tag
# breaks every fresh resolution while `uv sync --locked` keeps passing from the lock.
#
# This must never reach a published release: a VCS dependency in published
# metadata makes the package unresolvable from PyPI. `uv build --no-sources`
# strips it, and tools/check_dist_metadata.py fails a build that carries one.
# Delete this block once l3io-wordpress-config is on PyPI.
l3io-wordpress-config = { git = "https://github.com/ravensorb/l3io-wordpress-config.git", tag = "v0.1.0" }
```

- [ ] **Step 6: Relock and run**

Run: `uv lock && uv lock --check && uv run pytest tests/test_declared_facts.py tests/test_wpconfig.py -q`
Expected: the lock resolves `l3io-wordpress-config 0.1.0`; PASS.

- [ ] **Step 7: Check the release metadata**

Run: `make build`
Expected: `tools/check_dist_metadata.py` passes, and `unzip -p dist/*.whl '*/METADATA' | grep Requires-Dist` shows `l3io-wordpress-config<0.2,>=0.1.0; extra == 'wpconfig'` with no `git+`.

- [ ] **Step 8: Commit**

Run `make check`, then:

```bash
git add pyproject.toml uv.lock tests/test_declared_facts.py tests/test_wpconfig.py
git commit -m "build: bound every requirement; take l3io-wordpress-config 0.1.0 for its parser fix"
```

---

### Task 3: Python 3.14

**Files:**
- Modify: `pyproject.toml` (classifiers)
- Modify: `.github/workflows/ci.yml` (`test` and `verify-install` matrices), `.github/workflows/publish.yml` (`smoke` matrix)

- [ ] **Step 1: Declare it.** Add `"Programming Language :: Python :: 3.14",` after the 3.13 classifier.

- [ ] **Step 2: Run the existing guard to see it fail**

Run: `uv run pytest tests/test_declared_facts.py -q -k matrix`
Expected: FAIL — `ci.yml:test`, `ci.yml:verify-install` and `publish.yml:smoke` run `['3.11', '3.12', '3.13']`, classifiers declare four.

- [ ] **Step 3: Extend the matrices.** In `ci.yml`, both `fromJSON('["3.11","3.12","3.13"]')` become `fromJSON('["3.11","3.12","3.13","3.14"]')` (the act branch stays `["3.11"]`). In `publish.yml`, `python: ['3.11', '3.12', '3.13']` becomes `python: ['3.11', '3.12', '3.13', '3.14']`.

- [ ] **Step 4: Run the guard and the suite on 3.14**

Run: `uv run pytest tests/test_declared_facts.py -q && UV_PROJECT_ENVIRONMENT=/tmp/l3io-venv-314 uv run --python 3.14 --locked --all-extras pytest -q -p no:cacheprovider; rm -rf /tmp/l3io-venv-314`
Expected: PASS both (the 3.14 run skips integration without `DB_HOST`).

- [ ] **Step 5: Commit**

Run `make check`, then:

```bash
git add pyproject.toml .github/workflows/ci.yml .github/workflows/publish.yml
git commit -m "ci: support and test Python 3.14"
```

---

### Task 4: Each extra installs and enables what it names

Spec §12: "CI installs the built wheel, bare and with each extra, into an isolated environment, and imports what each extra enables."

**Files:**
- Create: `tools/verify_extras.sh`
- Modify: `.github/workflows/ci.yml` (`verify-install`: the base-install step's forbidden tuple, plus a new step)
- Modify: `Makefile` (`verify-wheel`)
- Test: `tests/test_declared_facts.py`

**Interfaces:**
- Produces: `bash tools/verify_extras.sh WHEEL [PYTHON]` — exits non-zero if any extra fails.

- [ ] **Step 1: Write the tests** (append to `tests/test_declared_facts.py`)

```python
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
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_declared_facts.py -q -k "extra"`
Expected: FAIL — `tools/verify_extras.sh` does not exist; `pyrage` is not forbidden in `Makefile` or `ci.yml`.

- [ ] **Step 3: Write `tools/verify_extras.sh`** (`chmod +x`)

```bash
#!/usr/bin/env bash
# Install the built wheel once per extra, each into its own isolated environment,
# and use what that extra enables (spec §12). Usage: verify_extras.sh WHEEL [PYTHON]
#
# l3io-wordpress-config is not on PyPI, so the wpconfig leg takes it from its
# GitHub release. The extra's own specifier must still accept that version, or uv
# refuses to resolve -- which is the point of installing through the extra.
set -euo pipefail

wheel=${1:?usage: verify_extras.sh WHEEL [PYTHON]}
python=${2:-}
config_wheel=${WPCONFIG_WHEEL:-https://github.com/ravensorb/l3io-wordpress-config/releases/download/v0.1.0/l3io_wordpress_config-0.1.0-py3-none-any.whl}
url="file://$(realpath "$wheel")"

isolated() {
  uv run --isolated --no-project ${python:+--python "$python"} "$@"
}

isolated --with "l3io-wordpress-database[aws] @ $url" python -c '
import boto3
from l3io.wp.database import AwsSecretsManager
print("aws ok: boto3", boto3.__version__)
'

isolated --with "l3io-wordpress-database[encryption] @ $url" python -c '
from l3io.wp.database import generate_identity
identity, recipient = generate_identity()
assert identity.startswith("AGE-SECRET-KEY-") and recipient.startswith("age1")
print("encryption ok")
'

isolated --with "l3io-wordpress-database[wpconfig] @ $url" \
         --with "l3io-wordpress-config @ $config_wheel" python - <<'PY'
import pathlib
import tempfile

from l3io.wp.database import WpConfigFile

path = pathlib.Path(tempfile.mkdtemp()) / "wp-config.php"
path.write_text(
    "<?php\ndefine('DB_NAME', 'wp_site');\ndefine('DB_USER', 'wp');\n"
    "define('DB_PASSWORD', 'ab);cd');\ndefine('DB_HOST', 'localhost');\n"
)
assert WpConfigFile(path).resolve().password == "ab);cd", "a config without the parser fix"
print("wpconfig ok")
PY
```

- [ ] **Step 4: Wire it in.** In `ci.yml`'s `verify-install` job, change the base-install step's loop to `for forbidden in ("boto3", "botocore", "l3io.wp.config", "pyrage"):`, and append this step after `the console script is installed and runs`:

```yaml
      - name: each extra installs and enables what it names
        run: |
          set -euo pipefail
          wheel=$(find "$DIST_DIR" -maxdepth 1 -name '*.whl')
          bash tools/verify_extras.sh "$wheel" "${{ matrix.python }}"
```

In the `Makefile`'s `verify-wheel` recipe, change `('boto3','botocore','l3io.wp.config')` to `('boto3','botocore','l3io.wp.config','pyrage')`, and add a last line to the recipe: `	bash tools/verify_extras.sh "$$wheel"` (tab-indented, inside the same `set -eu; ...` chain: end the previous line with `; \`).

- [ ] **Step 5: Run it for real**

Run: `make verify-wheel && uv run pytest tests/test_declared_facts.py -q`
Expected: `base install is clean`, `aws ok`, `encryption ok`, `wpconfig ok`; PASS.

- [ ] **Step 6: Commit**

Run `make check`, then:

```bash
git add tools/verify_extras.sh Makefile .github/workflows/ci.yml tests/test_declared_facts.py
git commit -m "ci: install the wheel with each extra and use what it enables"
```

---

### Task 5: Coverage floor

Spec §13: "A coverage floor is enforced in CI." Measured 2026-10-14: 79% without a server, 89% with MySQL 8.4 attached. CI's `test` legs are the only runs that measure coverage (`--cov=l3io.wp.database`), and all of them have a server.

**Files:**
- Modify: `pyproject.toml` (new `[tool.coverage.report]`)
- Test: `tests/test_declared_facts.py`

- [ ] **Step 1: Write the test** (append to `tests/test_declared_facts.py`)

```python
# ------------------------------------------------------------ coverage floor


def test_ci_measures_coverage_against_a_floor() -> None:
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        floor = tomllib.load(fh).get("tool", {}).get("coverage", {}).get("report", {})
    assert isinstance(floor.get("fail_under"), int) and floor["fail_under"] >= 85, floor
    ci = yaml.safe_load((WORKFLOWS / "ci.yml").read_text(encoding="utf-8"))
    runs = " ".join(str(s.get("run", "")) for s in ci["jobs"]["test"]["steps"])
    assert "--cov=l3io.wp.database" in runs, "the test job no longer measures coverage"
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/test_declared_facts.py -q -k coverage`
Expected: FAIL — `{}`.

- [ ] **Step 3: Declare the floor** (append to `pyproject.toml` after `[tool.pytest.ini_options]`)

```toml
# Just under the line coverage the integration legs measure (89% on MySQL 8.4), so
# a deleted test file fails CI instead of passing quietly. pytest-cov applies it to
# every run that measures coverage; `make test` measures none.
[tool.coverage.report]
fail_under = 87
```

- [ ] **Step 4: Prove it holds on both families**

Run each, removing the container even on failure:

```bash
docker run -d --rm --name l3io-cov -e MYSQL_ROOT_PASSWORD=root -e MARIADB_ROOT_PASSWORD=root -p 127.0.0.1:33306:3306 mysql:8.4
for i in $(seq 90); do docker exec l3io-cov mysqladmin ping -h127.0.0.1 -uroot -proot >/dev/null 2>&1 && break; sleep 2; done
DB_HOST=127.0.0.1 DB_PORT=33306 DB_ADMIN_USER=root DB_ADMIN_PASSWORD=root COVERAGE_FILE=/tmp/l3io-cov uv run pytest -q --cov=l3io.wp.database --cov-report=term | grep -E "TOTAL|Required"
docker rm -f l3io-cov; rm -f /tmp/l3io-cov
```

Then the same with `mariadb:11.4` (its ping is `docker exec l3io-cov mariadb-admin ping -h127.0.0.1 -uroot -proot`).
Expected: both report `Required test coverage of 87% reached`. If MariaDB 11.4 measures below 88%, set `fail_under` to one less than its whole-number total, and update the comment's figure.

- [ ] **Step 5: Commit**

Run `make check`, then:

```bash
git add pyproject.toml tests/test_declared_facts.py
git commit -m "ci: enforce a coverage floor of 87%"
```

---

### Task 6: No floating tag starts a publish; release notes start from the previous release

Ported from `l3io-wordpress-config` (`db7625d`, `14512f0`). This repository has no floating tags yet; both changes are correct with or without them, and needed the moment they exist.

**Files:**
- Create: `tests/test_workflow_gates.py`
- Modify: `.github/workflows/publish.yml` (`on.push.tags`; the `release` job)

- [ ] **Step 1: Write the tests**

```python
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
        s for s in steps
        if str(s.get("uses", "")).startswith("LiquidLogicLabs/git-action-release-changelog-builder")
    )
    assert "steps.previous.outputs.tag" in str(builder.get("with", {}).get("from-tag", ""))
    previous = next((s for s in steps if s.get("id") == "previous"), None)
    assert previous is not None, "no step with id 'previous' computes the lower bound"
    assert "--match 'v[0-9]*.[0-9]*.[0-9]*'" in str(previous.get("run", ""))
    assert steps.index(previous) < steps.index(builder)
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_workflow_gates.py -q`
Expected: FAIL — `publish.yml runs on floating tag(s) ['v0', 'v0.1', 'v1', 'v1.2']`; no `previous` step.

- [ ] **Step 3: Narrow the trigger.** In `publish.yml`, `tags: ['v*', '!v0.0.0']` becomes `tags: ['v*.*.*', '!v0.0.0']`. Add one line to the comment above it: `# Three components only, so a floating v<major> or v<major>.<minor> tag never starts a publish.`

- [ ] **Step 4: Bound the notes.** In the `release` job, insert before `build the release notes from the commit log`:

```yaml
      # The previous RELEASE tag: three components only, so a floating tag on
      # the same commit can never be taken for it. Empty on the first release.
      - name: the previous release tag
        id: previous
        run: |
          set -euo pipefail
          prev=$(git describe --tags --abbrev=0 --match 'v[0-9]*.[0-9]*.[0-9]*' "${GITHUB_REF_NAME}^" 2>/dev/null || true)
          echo "tag=${prev}" >> "$GITHUB_OUTPUT"
          echo "previous release tag: ${prev:-none}"
```

and in the builder's `with:` block, before `to-tag:`:

```yaml
          # Explicit, never auto-detected: auto-detection takes the nearest tag,
          # which a floating tag on this commit would be.
          from-tag: ${{ steps.previous.outputs.tag }}
```

- [ ] **Step 5: Run the tests and the dry run**

Run: `uv run pytest tests/test_workflow_gates.py tests/test_act_dryrun_legs.py -q && make ci-dryrun`
Expected: PASS; `all legs dry-run clean; every action ref resolved`.

- [ ] **Step 6: Commit**

Run `make check`, then:

```bash
git add tests/test_workflow_gates.py .github/workflows/publish.yml
git commit -m "ci: only release tags start a publish; notes start from the previous release"
```

---

### Task 7: A quote in a user name; an interrupted transfer run

**Files:**
- Modify: `src/l3io/wp/database/identifiers.py` (`validate_user_name`)
- Modify: `Makefile` (`test-transfer`)
- Create: `tests/test_make_targets.py`
- Test: `tests/test_identifiers.py`

- [ ] **Step 1: Write the identifier test** (append to `tests/test_identifiers.py`)

```python
def test_a_user_name_with_a_quote_is_refused() -> None:
    """``'`` breaks the ``'user'@'host'`` grantee form the grant lookup compares against."""
    with pytest.raises(InvalidIdentifierError, match="forbidden"):
        validate_user_name("o'brien")
```

- [ ] **Step 2: Write the Makefile test**

```python
"""Make recipes whose failure modes leak something."""

from __future__ import annotations

from pathlib import Path

MAKEFILE = Path(__file__).resolve().parent.parent / "Makefile"


def recipe(target: str) -> str:
    lines = MAKEFILE.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{target}:"))
    body = []
    for line in lines[start + 1 :]:
        if not line.startswith("\t"):
            break
        body.append(line)
    assert body, f"{target} has no recipe"
    return "\n".join(body)


def test_an_interrupted_transfer_run_removes_its_server() -> None:
    """Under dash an EXIT trap does not run on Ctrl-C, leaving a server holding the port."""
    body = recipe("test-transfer")
    assert "EXIT" in body
    assert "trap 'exit 130' INT TERM" in body
```

- [ ] **Step 3: Run them to see them fail**

Run: `uv run pytest tests/test_identifiers.py tests/test_make_targets.py -q`
Expected: FAIL — `DID NOT RAISE`; `trap 'exit 130' INT TERM` not in the recipe.

- [ ] **Step 4: Refuse the quote**

```python
def validate_user_name(name: str) -> str:
    """Return ``name`` if it is usable as a user identifier, else raise."""
    _check("user name", name, MAX_USER_NAME)
    if "'" in name:
        raise InvalidIdentifierError("user name", name, "contains forbidden characters: \"'\"")
    return name
```

- [ ] **Step 5: Trap the interrupt.** In `test-transfer`, after the line `trap 'docker rm -f "'"$$name"'" >/dev/null 2>&1' EXIT; \`, add the line `	trap 'exit 130' INT TERM; \` (tab-indented).

- [ ] **Step 6: Run the tests, and prove the trap by hand**

Run: `uv run pytest tests/test_identifiers.py tests/test_make_targets.py -q`
Expected: PASS.
Then run `make test-transfer ENGINE=mysql:8.4`, press Ctrl-C once the second container starts, and run `docker ps --filter name=l3io-transfer -q`. Expected: no output.

- [ ] **Step 7: Commit**

Run `make check`, then:

```bash
git add src/l3io/wp/database/identifiers.py tests/test_identifiers.py Makefile tests/test_make_targets.py
git commit -m "fix: refuse a quote in a user name; remove the transfer server on Ctrl-C"
```

---

### Task 8: Documentation describes only this package

Spec §14. Every predecessor file stays readable on `legacy/main` (local now; pushed in Task 13).

**Files:**
- Delete: `docs/migration.md`, `docs/rewrite-notes.md`, `_bmad-output/planning-artifacts/prds/prd-py-wordpress-database-2026-09-15/` (the whole folder)
- Rewrite: `README.md`, `LICENSE`
- Create: `docs/adr/README.md`, `docs/adr/0001-operations-owned-here.md`, `0002-credentials-through-a-pipe.md`, `0003-age-encryption.md`, `0004-check-first-verdict.md`, `0005-destructive-calls-name-the-target-twice.md`
- Create: `tests/test_readme.py`

- [ ] **Step 1: Write the README guard**

```python
"""The README's examples use only what exists.

The README is the first thing a user runs. Its library examples import only
names the package exports, and every command line it shows parses.
"""

from __future__ import annotations

import ast
import re
import shlex
from pathlib import Path

import pytest

import l3io.wp.database as database
from l3io.wp.database.cli import build_parser

README = Path(__file__).resolve().parent.parent / "README.md"
_BLOCK = re.compile(r"^```(\w+)\n(.*?)^```", re.MULTILINE | re.DOTALL)


def blocks(text: str, language: str) -> list[str]:
    return [body for lang, body in _BLOCK.findall(text) if lang == language]


def imported_names(source: str) -> set[str]:
    return {
        alias.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module == "l3io.wp.database"
        for alias in node.names
    }


def commands(source: str) -> list[list[str]]:
    joined = source.replace("\\\n", " ")
    return [
        shlex.split(line)[1:]
        for line in joined.splitlines()
        if line.strip().startswith("l3io-wordpress-database ")
    ]


def test_every_python_example_imports_only_exported_names() -> None:
    sources = blocks(README.read_text(encoding="utf-8"), "python")
    assert sources, "README has no Python example -- this guard is vacuous"
    names = set().union(*(imported_names(s) for s in sources))
    assert names, "no README example imports from l3io.wp.database"
    assert not sorted(names - set(database.__all__))


def test_every_command_line_example_parses() -> None:
    found = [c for s in blocks(README.read_text(encoding="utf-8"), "shell") for c in commands(s)]
    assert found, "README shows no command line -- this guard is vacuous"
    parser = build_parser()
    for argv in found:
        try:
            parser.parse_args(argv)
        except SystemExit:
            pytest.fail(f"README command does not parse: {shlex.join(argv)}")


def test_an_unexported_name_is_caught() -> None:
    assert imported_names("from l3io.wp.database import WpDatabase, Database\n") == {
        "WpDatabase",
        "Database",
    }
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/test_readme.py -q`
Expected: FAIL — `['WpConnection', 'WpCredentials', 'WpDatabase', 'WpConfigSource']` are not exported; `--inspect` does not parse.

- [ ] **Step 3: Rewrite `README.md`** with exactly this content:

````markdown
# l3io-wordpress-database

The operations a WordPress site performs against its MySQL or MariaDB database:
inspecting it, provisioning it, changing its accounts, destroying it, and exporting
and importing it. Every operation acts with credentials the caller supplies, and
every operation that changes or moves something can be checked before it runs.

It imports as `l3io.wp.database`, in the `l3io.wp` namespace shared with
`l3io-wordpress-config` and `l3io-wordpress-backup`.

> **Status:** 0.x — documented and typed, with no stability promise until 1.0.0.
> Not yet on PyPI; releases are on
> [GitHub](https://github.com/ravensorb/l3io-wordpress-database/releases).

## Installing

```shell
pip install l3io-wordpress-database                # core: PyMySQL, structlog, opentelemetry-api
pip install 'l3io-wordpress-database[aws]'         # credentials from AWS Secrets Manager
pip install 'l3io-wordpress-database[wpconfig]'    # credentials and location from wp-config.php
pip install 'l3io-wordpress-database[encryption]'  # age-encrypted dumps
```

An optional dependency is an optional import: a base install never imports
`boto3`, the config reader or `pyrage`, and asking for a feature whose extra is
absent raises `MissingDependencyError` naming the extra.

## Two accounts

WordPress's own account — the one in `wp-config.php` — is the account that is
created and granted. A separate administrative account does the creating, and is
never defaulted to the WordPress account. Whether a database exists is answered
by the administrator: a server authenticates before it resolves the database, so a
failed login by the WordPress account says nothing about the database.

## Check, then run

```python
from l3io.wp.database import Connection, Database, Environment, Explicit

db = Database(Connection("127.0.0.1", "wp_site"))
admin = Environment("DB_ADMIN_USER", "DB_ADMIN_PASSWORD")
wordpress = Explicit("wpuser", "wp-pass")

verdict = db.check_ensure(admin, wordpress)
for finding in verdict.findings:
    print(finding.severity, finding.code, finding.message)

if verdict.ok:
    result = db.ensure(admin, wordpress)
    print(result.created_database, result.created_user, result.granted, result.changed)
```

`ensure` runs the same check itself and raises `RefusedError`, carrying the
`Verdict`, on any blocker. It creates only what is missing, and a second run
against a converged server changes nothing. Grants are scoped to the one database,
with the `_` and `%` wildcards in its name escaped.

Destructive operations — `revoke`, `drop_user`, `drop_database` — take
`confirm=`, which must repeat the target's name.

## From wp-config.php

```python
from l3io.wp.database import Database, Environment, WpConfigFile

site = WpConfigFile("/var/www/html/wp-config.php")
db = Database(site.connection())
survey = db.survey(
    Environment("DB_ADMIN_USER", "DB_ADMIN_PASSWORD"),
    wordpress_user=site.resolve().username,
    table_prefix=site.table_prefix,
)
print(survey.database_exists, survey.table_count, survey.is_wordpress, survey.schema_version)
```

`inspect` asks the WordPress account itself what it can do, and never raises
for an ordinary failure:

| State | Meaning |
|---|---|
| `ready` | connected, authenticated, and the database is usable |
| `database_absent` | authenticated, but the database does not exist |
| `access_denied` | authenticated, but may not use this database |
| `authentication_failed` | the server rejected the account |
| `unreachable` | the server could not be reached |
| `credentials_unobtainable` | the credentials could not be obtained; nothing was attempted |

## Export and import

```python
from l3io.wp.database import Connection, Database, Environment, WpConfigFile, generate_identity

site = WpConfigFile("/var/www/html/wp-config.php")
identity, recipient = generate_identity()
Database(site.connection()).dump(site, "/backups/wp_site.sql.age", recipients=[recipient])

admin = Environment("DB_ADMIN_USER", "DB_ADMIN_PASSWORD")
staging = Database(Connection("127.0.0.1", "wp_site_staging"))
staging.ensure(admin, site)
staging.load(site, "/backups/wp_site.sql.age", identities=[identity])
```

Dumps are made by the server's own client tools (`mysqldump` or `mariadb-dump`),
and loads by `mysql` or `mariadb`. The password reaches them only through an
anonymous pipe: never an argument, an environment variable or a file. A dump to
a path is written under a temporary name and renamed only on success. `iter_dump`
yields the dump as chunks, and raises at the end if the tool failed, so a
truncated dump is never mistaken for a whole one.

Loading into a database that holds tables requires `replace=` naming it. A damaged
source is discovered mid-load, after the statements before the damage have run,
so load into a staging database and switch to it once the load succeeds.

Encryption is standard [age](https://age-encryption.org): any dump can be
decrypted with the stock `age` command line.

## Command line

```shell
l3io-wordpress-database survey --wp-config /var/www/html/wp-config.php \
    --admin-user root --admin-password-env DB_ADMIN_PASSWORD
l3io-wordpress-database check ensure --wp-config /var/www/html/wp-config.php \
    --admin-user root --admin-password-env DB_ADMIN_PASSWORD
l3io-wordpress-database ensure --wp-config /var/www/html/wp-config.php \
    --admin-user root --admin-password-env DB_ADMIN_PASSWORD
l3io-wordpress-database dump --wp-config /var/www/html/wp-config.php \
    --output wp_site.sql.age --recipient age1examplerecipient
l3io-wordpress-database load --db-host 127.0.0.1 --db-name wp_site_staging \
    --db-user wpuser --db-password-env DB_PASSWORD \
    --input wp_site.sql.age --identity key.txt
l3io-wordpress-database drop-database --db-host 127.0.0.1 --db-name wp_site_staging \
    --admin-user root --admin-password-env DB_ADMIN_PASSWORD --confirm wp_site_staging
```

No password is accepted as an argument value, because an argument vector is
visible to every user on the machine: a password comes from `--wp-config`, from
the environment variable named by a `--*-password-env` option, from AWS Secrets
Manager, or from a prompt. Results are printed as JSON on stdout; with
`dump --output -` the dump is on stdout and the result on stderr.

| Exit code | Meaning |
|---|---|
| `0` | success |
| `1` | the operation started and failed |
| `2` | usage |
| `3` | refused: the check found a blocker, and nothing ran |
| `4` | credentials could not be obtained |
| `5` | the server could not be reached |
| `7` | not ready: `inspect` found the account cannot use the database |

## Supported

- Python 3.11, 3.12, 3.13 and 3.14.
- MySQL 8.0 and later, MariaDB 10.2 and later. CI runs MySQL 8.0, 8.4 and 9.7 and
  MariaDB 10.2 and 11.4.
- Export and import need `/dev/fd` (Linux or macOS) and the client tools on `PATH`.
  Everything else is pure Python.

The package logs through `structlog` and never configures logging, and opens one
OpenTelemetry span per operation through `opentelemetry-api`, inert until the host
configures an SDK.

## Design records

This package's decisions are in [docs/adr](docs/adr/README.md). The rules the
`l3io.wp` family shares (cited as AD-n) are in `l3io-wordpress-backup`'s
architecture spine.

## Development

```shell
make sync                                # locked environment, all extras
make check                               # lint, format, types, tests, contracts
make test-db DB_HOST=127.0.0.1           # integration tests against a server
make test-transfer ENGINE=mysql:8.4      # export/import with that image's own client tools
make verify-wheel                        # install the built wheel, bare and with each extra
make ci                                  # replay the CI pipeline under act
```

## Licence

MIT.
````

- [ ] **Step 4: Rewrite `LICENSE`** with exactly:

```text
MIT License

Copyright (c) 2026 Shawn Anderson

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 5: Write the ADRs.** Each file uses this shape, with the content given below.

`docs/adr/README.md`:

```markdown
# Architecture decision records

This package's own decisions. The rules the `l3io.wp` family shares (AD-n) are in
`l3io-wordpress-backup`'s architecture spine and are not restated here.

| ADR | Decision |
|---|---|
| [0001](0001-operations-owned-here.md) | Every operation on a site's database, including export and import, is owned here |
| [0002](0002-credentials-through-a-pipe.md) | Credentials reach client tools through an anonymous-pipe option file |
| [0003](0003-age-encryption.md) | `age`, through `pyrage`, is the encryption format |
| [0004](0004-check-first-verdict.md) | Every operation that changes or moves something has a check returning a `Verdict` |
| [0005](0005-destructive-calls-name-the-target-twice.md) | Destructive calls name their target twice |
```

`docs/adr/0001-operations-owned-here.md`:

```markdown
# ADR-0001: Every operation on a site's database is owned here

- **Status:** Accepted
- **Date:** 2026-10-14
- **Deciders:** Shawn Anderson

## Context

`l3io-wordpress-backup`, test suites, provisioning scripts and operators all act on
WordPress databases: checking existence and emptiness, provisioning, changing
accounts, destroying, exporting and importing. Each caller that issues its own SQL
or runs `mysqldump` itself carries its own copy of the server-family differences
and its own way of handling a database password.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Each caller does its own database work | No dependency between packages | Several implementations of secret handling and portability |
| B. This package owns inspection and provisioning; backup owns export and import | Backup controls its archive path | Two packages pass passwords to client tools |
| C. This package owns every operation, export and import included | One implementation of each | This API becomes backup's contract |

## Decision

**C.** Every operation on a site's database is a call into this package. Backup
issues no SQL against a site's database and never handles a database password.
Export and import run the server's own client tools, chosen per server family; the
package never parses SQL.

## Consequences

- One place owns portability across MySQL 8.0–9.x and MariaDB 10.2+, and one place
  owns secret handling.
- Backup's dry run is a call to a `check_*` function.
- Export and import need the client tools on `PATH` and `/dev/fd`, so they do not
  run on Windows.
- 1.0.0 waits until backup has integrated against this API.
```

`docs/adr/0002-credentials-through-a-pipe.md`:

```markdown
# ADR-0002: Credentials reach client tools through an anonymous-pipe option file

- **Status:** Accepted
- **Date:** 2026-10-14
- **Deciders:** Shawn Anderson

## Context

`mysqldump`, `mariadb-dump`, `mysql` and `mariadb` need the password. Every user on
the machine can read a process's argument vector, `/proc/<pid>/environ` exposes
`MYSQL_PWD`, an option file on disk outlives the process, and MySQL clients read
`~/.mylogin.cnf` even when told to use another option file.

## Options considered

| Option | Risk |
|---|---|
| `--password=` in the arguments | readable by every local user |
| `MYSQL_PWD` | readable through `/proc`; deprecated by MySQL |
| a `0600` temporary option file | on disk, and left behind by a crash |
| `--defaults-extra-file` | still reads the user's own option files |
| an option file written to a pipe | none of the above |

## Decision

The `[client]` options — user, password, host, port and `protocol=TCP` — are
written to `os.pipe()`. The read end is passed with `pass_fds` and named as
`--defaults-file=/dev/fd/N`, the first argument. The child's environment is
`PATH`, `LANG`, `LC_ALL` and `MYSQL_TEST_LOGIN_FILE` (a nonexistent path) and
nothing else; MySQL 8.4 and later also get `--no-login-paths`. Values are quoted
and escaped, and a value whose escaped form exceeds 1024 UTF-8 bytes, or that is not
UTF-8, is refused, because MariaDB's option reader splits long lines.

## Consequences

- No password in an argument vector, an environment or a file; a hostile
  `~/.my.cnf` or `~/.mylogin.cnf` changes nothing.
- `protocol=TCP` makes `localhost` mean the same server to the tool as to PyMySQL.
- Needs `/dev/fd`. MySQL 8.1–8.3 clients lack `--no-login-paths`; those releases
  are past end of life and not supported.
```

`docs/adr/0003-age-encryption.md`:

```markdown
# ADR-0003: `age`, through `pyrage`, is the encryption format

- **Status:** Accepted
- **Date:** 2026-10-14
- **Deciders:** Shawn Anderson

## Context

Dumps leave the server and sit in backups. The family needs one encryption format
that streams, whose output an operator can decrypt without this package, and that
needs no key-server or keyring state.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| GPG through `python-gnupg` | widely known | needs the `gpg` binary and keyring state |
| Fernet (`cryptography`) | one dependency | not streaming; a format only Python reads |
| `age` through `pyrage` | streaming, standard format, SSH keys as recipients | `pyrage` ships no type information |

## Decision

`age` through `pyrage>=1.4,<2`, behind the `encryption` extra and imported only
when used. `recipients` takes `age` or SSH public keys; `identities` takes `age`
identities, which may themselves be passphrase-protected. A wrong identity raises
`DecryptionError`; a truncated or damaged stream raises `CorruptDumpError`, because
the remedy differs.

## Consequences

- Any dump decrypts with the stock `age` command line; backup's archives use the
  same format.
- Encryption streams with bounded memory (a 512 MiB dump encrypts with an 11 MiB
  peak).
- Damage is found mid-load, so callers load into a staging database first.
```

`docs/adr/0004-check-first-verdict.md`:

```markdown
# ADR-0004: Every operation that changes or moves something has a check

- **Status:** Accepted
- **Date:** 2026-10-14
- **Deciders:** Shawn Anderson

## Context

Callers need to know, before anything runs, whether an operation would be refused
and why, and to branch on the reason without parsing a message. A boolean loses the
reason; an exception alone cannot be asked for in advance.

## Decision

Each operation `X` that changes or moves something has `check_X(...) -> Verdict`,
which changes nothing. A `Verdict` holds `Finding`s; each has a `Code` with exactly
one severity, blocker or warning. `X` runs the same check and raises `RefusedError`,
carrying the `Verdict`, on any blocker, so the check is never skipped and never
differs from the run. Warnings travel on every result and are logged once.

## Consequences

- A dry run is a call to `check_X`.
- The code catalogue is an API: every code is documented, and a test fails if no
  test asserts it.
- A refusal that is not a finding — an unusable argument — is an exception raised
  before anything starts.
```

`docs/adr/0005-destructive-calls-name-the-target-twice.md`:

```markdown
# ADR-0005: Destructive calls name their target twice

- **Status:** Accepted
- **Date:** 2026-10-14
- **Deciders:** Shawn Anderson

## Context

`drop_database`, `drop_user`, `revoke`, and a load over existing tables destroy
data. A variable holding the wrong name destroys the wrong thing, and nothing
inside the call can tell.

## Decision

`drop_database`, `drop_user` and `revoke` require `confirm=` equal to their
target; `load` into a database holding tables requires `replace=` equal to the
connection's database. A mismatch is the `CONFIRMATION_MISMATCH` blocker. The
command line requires `--confirm NAME` and `--replace NAME`. A destructive target
that holds a WordPress site also raises the `LIVE_WORDPRESS_SITE` warning.

## Consequences

- A wrong variable is refused instead of acted on.
- Calls are more verbose, on purpose.
```

- [ ] **Step 6: Delete the predecessor documents**

```bash
git rm docs/migration.md docs/rewrite-notes.md
git rm -r _bmad-output/planning-artifacts/prds/prd-py-wordpress-database-2026-09-15
```

- [ ] **Step 7: Run the guard and the format check**

Run: `uv run pytest tests/test_readme.py -q && make format`
Expected: PASS. If `make format` reports `README.md`, run `uv run ruff format README.md`, review the diff, and re-run.

- [ ] **Step 8: Commit**

Run `make check`, then:

```bash
git add README.md LICENSE docs/adr tests/test_readme.py
git commit -m "docs: README, licence and decision records describe only this package"
```

(`git rm` already staged the deletions.)

---

### Task 9: Nothing in the tree narrates the predecessor

Spec §14: docstrings, comments, tests and workflow comments that narrate the predecessor or the rewrite are rewritten. "A rule that history justified keeps its check, and its reason is restated as a present-tense risk."

**Files:**
- Create: `tests/test_current_only.py`
- Modify: every file the guard names (measured 2026-10-14: `pyproject.toml`, `tools/check_dist_metadata.py`, `tools/check_name_claim.py`, `tests/test_name_claim.py`, `tests/test_declared_facts.py`, `tests/test_architecture.py`, `src/l3io/wp/database/identifiers.py`, `versions.py`, `state.py`, `.github/workflows/ci.yml`, `publish.yml`, `security-audit.yml`, `AGENTS.md`)

- [ ] **Step 1: Write the guard**

```python
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
#: Planning records and the session handoff may name history; the tombstone exists
#: to name the retired package; this file names the patterns.
ALLOWED = (
    "_bmad/",
    "_bmad-output/",
    ".claude/",
    ".agents/",
    "docs/handoff/",
    "tombstone/",
    "uv.lock",
    "tests/test_current_only.py",
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
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/test_current_only.py -q`
Expected: FAIL, listing about 30 lines across the files named above.

- [ ] **Step 3: Rewrite each hit as a present-tense statement.** Keep every check and every rule; change only the narration. Use these exact rewrites for the recurring cases:
  - "the defect that left the predecessor (package) unresolvable (from PyPI) for six years" → "a VCS dependency in published metadata makes the package unresolvable from PyPI".
  - "installing the working tree would have passed throughout the six years the predecessor package could not be installed" → "installing the working tree passes even when the published wheel cannot be installed".
  - `FR-50` → "the name-claim release gate"; `FR-45` → "the dependency audit"; `FR-48` → "the supported-Python set"; `FR-8/FR-9` → "the 9.x generation, which removed `mysql_native_password`"; `NFR-4` → "the supported floor".
  - `identifiers.py`, `versions.py`, `state.py` module docstrings: state the risk the code prevents (for example, `identifiers.py`: "A database-level GRANT matches its database name as a LIKE pattern, so `_` is a single-character wildcard: granting on `wp_site` also grants on `wpXsite`. ..."), dropping "the original package".
  - `pyproject.toml` hatch-vcs comment: drop the sentence about bounding release notes "to the rewrite"; keep why `v0.0.0` exists and why only three-component tags count. The ruff `BLE001` comment: "a bare `except Exception` silently turns distinct failures into one benign-looking result".
  - `AGENTS.md` lines 48–50 (inside the managed block, which Task 12 refreshes): "a VCS dependency in published metadata makes the package unresolvable from PyPI."

- [ ] **Step 4: Run the guard**

Run: `uv run pytest tests/test_current_only.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

Run `make check`, then stage every modified file by path (`git status --short` lists them) plus `tests/test_current_only.py`:

```bash
git add tests/test_current_only.py pyproject.toml tools/check_dist_metadata.py tools/check_name_claim.py tests/test_name_claim.py tests/test_declared_facts.py tests/test_architecture.py src/l3io/wp/database/identifiers.py src/l3io/wp/database/versions.py src/l3io/wp/database/state.py .github/workflows/ci.yml .github/workflows/publish.yml .github/workflows/security-audit.yml AGENTS.md
git commit -m "docs: state each rule's reason as a present-tense risk"
```

---

### Task 10: The `wpdatabase2` tombstone

Spec §12: "a single `wpdatabase2` 0.0.16 tombstone, with no dependencies, whose README and import error point to `l3io-wordpress-database`." The predecessor imports as `wpdatabase2` (PyPI 0.0.15 wheel). Building is part of this task; publishing it is Shawn's, after 0.1.0 is on PyPI.

**Files:**
- Create: `tombstone/wpdatabase2/pyproject.toml`, `tombstone/wpdatabase2/README.md`, `tombstone/wpdatabase2/src/wpdatabase2/__init__.py`
- Create: `tests/test_tombstone.py`

- [ ] **Step 1: Write the test**

```python
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
        [UV, "run", "--isolated", "--no-project", "--with", str(wheel), "python", "-c",
         "import wpdatabase2"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert imported.returncode != 0
    assert "l3io-wordpress-database" in imported.stderr
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/test_tombstone.py -q`
Expected: FAIL — `uv build` cannot find `tombstone/wpdatabase2`.

- [ ] **Step 3: Write the tombstone**

`tombstone/wpdatabase2/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "wpdatabase2"
version = "0.0.16"
description = "Retired. Install l3io-wordpress-database instead."
readme = "README.md"
requires-python = ">=3.8"
license = "MIT"
authors = [{ name = "Shawn Anderson" }]
classifiers = [
  "Development Status :: 7 - Inactive",
  "Programming Language :: Python :: 3",
]
dependencies = []

[project.urls]
Homepage = "https://github.com/ravensorb/l3io-wordpress-database"

[tool.hatch.build.targets.wheel]
packages = ["src/wpdatabase2"]
```

`tombstone/wpdatabase2/README.md`:

```markdown
# wpdatabase2 is retired

This name is no longer maintained, and this release installs nothing usable.

Its successor is
[l3io-wordpress-database](https://github.com/ravensorb/l3io-wordpress-database):

    pip install l3io-wordpress-database

It imports as `l3io.wp.database`. Its API is new; nothing of this package's API is
carried over.
```

`tombstone/wpdatabase2/src/wpdatabase2/__init__.py`:

```python
"""wpdatabase2 is retired; its successor is l3io-wordpress-database."""

_MESSAGE = (
    "wpdatabase2 is retired and does nothing. Install l3io-wordpress-database and "
    "import l3io.wp.database instead: https://github.com/ravensorb/l3io-wordpress-database"
)
raise ImportError(_MESSAGE)
```

- [ ] **Step 4: Run the test**

Run: `uv run pytest tests/test_tombstone.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

Run `make check` (it lints `tombstone/` too), then:

```bash
git add tombstone/wpdatabase2/pyproject.toml tombstone/wpdatabase2/README.md tombstone/wpdatabase2/src/wpdatabase2/__init__.py tests/test_tombstone.py
git commit -m "feat: wpdatabase2 0.0.16 tombstone pointing at l3io-wordpress-database"
```

---

### Task 11: Spec amendments, the handoff, and full verification

**Files:**
- Modify: `_bmad-output/planning-artifacts/spec/2026-10-12-l3io-wordpress-database-design.md`
- Rewrite: `docs/handoff/wordpress-database.md`

- [ ] **Step 1: Apply the six amendments** listed under "Spec amendments this plan makes", in the spec's own voice: present tense, plain statements of what the package does, no change history.

- [ ] **Step 2: Rewrite the handoff as current state only.** Keep the resume line. Sections, in order:
  - **What this session owns** — this repository only; the siblings and their sessions.
  - **Current state** — `main`'s commit, versions (last tag `v0.0.2`; next release 0.1.0), CI status, the five-engine matrix on Python 3.11–3.14, the coverage floor, `legacy/main` as the home of every predecessor file.
  - **Releasing 0.1.0 (Shawn's, in this order — AD-15)**: (1) `l3io-wordpress-config` reaches PyPI; (2) here, delete `[tool.uv.sources]` and relock; (3) register the PyPI and TestPyPI trusted publishers under `l3io-wordpress-database` for `publish.yml`; (4) `make release minor` (tags `v0.1.0`; the mirror and GitHub release follow); (5) `gh workflow run publish.yml -f target=testpypi`, then install from TestPyPI on every supported Python; (6) `gh workflow run publish.yml -f target=pypi`; (7) `uv build tombstone/wpdatabase2 --out-dir /tmp/wpdatabase2-dist` and `uv publish /tmp/wpdatabase2-dist/*` with a PyPI token scoped to `wpdatabase2`.
  - **Open decisions (Shawn's)** — a second built-in credential source (recommendation: a dependency-free environment-variable source); whether this repository gets floating version tags (the filter and notes guard are already in place); a `CLAUDE.md` agent block (doctor check 24); public visibility of the `liquidlogiclabs` Gitea org.
  - **Requests to the family** — spec §15's list, verbatim, each marked "not yet delivered", plus: "`l3io-wordpress-backup`: narrow `publish.yml`'s tag filter to `v*.*.*` and pass `from-tag` to the notes builder, as here and in config."
  - **Open deferred minors** — the plan 1 and plan 2 lists currently in this file, minus what plan 3 fixed (the quote in a user name; the Makefile Ctrl-C trap; the §7.2 `CREATE USER` wording; the §9 flag names), in the same terse style.
  - **Cautions** — never publish; never enumerate HTTP methods against a registry; prove every check by planting a failure; act's services are on `127.0.0.1`.

- [ ] **Step 3: Run the full verification**, recording each result:
  - `make check`
  - `make verify-wheel`
  - `make test-transfer ENGINE=<e>` for `mysql:8.0`, `mysql:8.4`, `mysql:9.7`, `mariadb:10.2`, `mariadb:11.4`, one at a time (they share port 33399)
  - MySQL 8.4 integration, pinging over TCP so the image's temporary setup server cannot answer:

    ```bash
    docker run -d --rm --name l3io-it -e MYSQL_ROOT_PASSWORD=root -p 127.0.0.1:33306:3306 mysql:8.4
    for i in $(seq 90); do docker exec l3io-it mysqladmin ping -h127.0.0.1 -uroot -proot >/dev/null 2>&1 && break; sleep 2; done
    make test-db DB_HOST=127.0.0.1 DB_PORT=33306 DB_ADMIN_USER=root DB_ADMIN_PASSWORD=root
    docker rm -f l3io-it
    ```

  - `make ci` (needs Infisical; if it is not authenticated, record the error and do not substitute placeholder secrets)
  - `make ci-dryrun`
  - `uv run python ../l3io-wordpress-backup/scripts/check-cicd-alignment.py` — expected 0 findings
  - `find . -path ./.git -prune -o -path ./.venv -prune -o -user root -print | wc -l` — expected 0

- [ ] **Step 4: Commit**

```bash
git add _bmad-output/planning-artifacts/spec/2026-10-12-l3io-wordpress-database-design.md docs/handoff/wordpress-database.md
git commit -m "spec, handoff: record plan 3's amendments and the release path"
```

---

### Task 12: Refresh the `AGENTS.md` block (controller, with Shawn)

`bmad-project-context` is conversational and Shawn approves every write, so this task is not delegated.

- [ ] **Step 1:** Run `/bmad-project-context` with intent `refresh`. New evidence since its provenance (`6c8c423`): `tombstone/`, `docs/adr/`, `tools/verify_extras.sh`, `make test-transfer`, the coverage floor, the current-only and README guards, Python 3.14, the `v0.1.0` pin.
- [ ] **Step 2:** On Shawn's approval of the block, `make check`, then `git add AGENTS.md && git commit -m "docs(agents): refresh the managed block"`.

---

### Task 13: Remote housekeeping (controller, after the branch is merged)

Spec §14: "each confirmed again immediately before it runs." Ask Shawn before each step, show the exact command, and run it only on a yes. Stop at the first failure and report it; do not work around a refusal.

- [ ] **Step 1:** Push the preserved history: `git push origin legacy/main`.
- [ ] **Step 2:** Push `main`: `git push origin main`, then watch CI to completion (`gh run watch <id> --exit-status`) and confirm every job, including the four-Python, five-engine matrix.
- [ ] **Step 3:** Rename the old branch: `gh api -X POST repos/ravensorb/l3io-wordpress-database/branches/dev-1.0.1/rename -f new_name=legacy/dev-1.0.1`.
- [ ] **Step 4:** Delete tag `v1.0`: `git push origin :refs/tags/v1.0 && git tag -d v1.0`.
- [ ] **Step 5:** Delete the GitHub release `v0.0.1`, keeping its tag: `gh release delete v0.0.1 --repo ravensorb/l3io-wordpress-database --yes` (no `--cleanup-tag`).
- [ ] **Step 6:** Delete the Gitea package `l3io-wp-database` 0.0.1 in org `liquidlogiclabs`, through the Gitea MCP `package_write` delete operation. If that tool is unavailable or unauthenticated, give Shawn the package's web page to delete it there. Never probe the registry with other HTTP methods.
- [ ] **Step 7:** Record each result in `docs/handoff/wordpress-database.md`, commit, and ask before pushing that commit.

Publishing — TestPyPI, PyPI, the Gitea mirror for 0.1.0, and the tombstone — is not part of this plan. It is the release path in the handoff, and it is Shawn's.
