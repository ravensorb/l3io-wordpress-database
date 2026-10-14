# Plan 2 of 3 — Export, Import and Encryption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `dump`, `iter_dump`, `load` and their checks — the server's own client tools run with the password delivered only through an anonymous-pipe option file — plus optional `age` encryption, CLI subcommands, and a CI job that tests every engine with that engine's own client tools.

**Architecture:** `_client.py` owns everything about the client programs: finding them, parsing their versions, building argument vectors from an allow-list, writing the option file into a pipe, and the minimal child environment. `encryption.py` wraps `pyrage` behind the `encryption` extra. `transfer.py` composes them: a preflight that reuses plan 1's admin preflight and returns a `Verdict`, a dump engine (`DumpStream`, an iterator that raises at the end on failure) and a load engine that peeks the source's first bytes to detect encryption, the source family and MariaDB's sandbox line — never parsing SQL. Path and stream forms are thin wrappers over the engines.

**Tech Stack:** Python 3.11+, PyMySQL 1.2, `subprocess` + threads, `pyrage` 1.4 (age), structlog, opentelemetry-api; tests: pytest, fake client scripts for engine unit tests, real servers via `make test-transfer ENGINE=<image>`.

**Spec:** `_bmad-output/planning-artifacts/spec/2026-10-12-l3io-wordpress-database-design.md` (§6, §7.3, §8, §9, §10, §13, §16)

**Plan series:** Plan 1 (merged) — core API. Plan 2 (this) — export, import, encryption. Plan 3 — release readiness and retirement.

## Global Constraints

- Python `>=3.11`; `mypy --strict`; never add `__init__.py` at `src/l3io/` or `src/l3io/wp/` (AD-27).
- No password in an argument vector, a child's environment, a file on disk, a log record, a span, an exception message, captured stderr or a `repr` (spec §2.4).
- Credentials reach a client tool only through `--defaults-file=/dev/fd/N`, placed first; never `--defaults-extra-file`, never `MYSQL_PWD` (spec §7.3).
- Only package-owned exception types cross the public boundary; wrap with `raise ... from` (AD-14).
- No hand-written SQL parser (global rule 1): the load path may only compare a dump's first lines against fixed strings.
- `pyrage>=1.4,<2` behind the `encryption` extra, imported inside the function that uses it (AD-8); also in the dev group, because `uv run` prunes extras.
- Every public operation runs inside `_observe.operation(...)` and hands its `Verdict` over under `VERDICT_KEY` so warnings are logged once.
- Use the `make` targets; `make check` must pass before every commit; stage files by explicit path, never `git add -A` (the repository owner commits concurrently).

## Probe results this plan is built on (run 2026-10-13)

- **V1** MariaDB 11.4 dumps begin `/*M!999999\- enable the sandbox mode */`. MySQL clients accept it as a comment; MariaDB 10.2's client rejects it (`Unknown command '\-'`). Cross-family loads fail on **collations**: MariaDB 11.4 → MySQL 8.4 `Unknown collation utf8mb4_uca1400_ai_ci`; MySQL 8.4 → MariaDB 10.2 `Unknown collation utf8mb4_0900_ai_ci`; MySQL 8.4 → MariaDB 11.4 works.
- **V2** `~/.mylogin.cnf` overrides `--defaults-file` (the login became user `nobody`). `MYSQL_TEST_LOGIN_FILE=/nonexistent` suppresses it on 8.0; `--no-login-paths` does on 8.4 and 9.7.
- **V3** The suite runs inside each server image (MySQL 8.0/8.4, MariaDB 10.2/11.4) after installing `git` and `uv` 0.11.6 with `UV_PYTHON=3.11`; the image's own client tools are on `PATH`.
- **V4** `pyrage` 1.4: wrong identity → `DecryptError('No matching keys found')`; truncated or corrupted body → `OSError('decryption error')`; corrupted header or not age → `DecryptError` with other text. Streaming: 512 MiB encrypted with an 11 MiB peak RSS.
- **V5** Option-file values wrapped in `"…"` with `\` and `"` backslash-escaped work on all five engines for `#`, `;`, `'`, `"`, `\`, leading/trailing spaces, `ab);cd`, `=`, `[`.
- **V7** `--single-transaction --quick --hex-blob --default-character-set=utf8mb4 --no-tablespaces` (+ `--set-gtid-purged=OFF` on MySQL tools) is accepted by every client; dumps contain no `CREATE DATABASE`/`USE` and load into a differently named database with equal checksums (MySQL strips same-schema qualifiers from views). MariaDB stores a trigger's original statement text, so a trigger created with a schema-qualified name is dumped qualified.
- **V8** A test process can read a child's `/proc/<pid>/cmdline` and `/proc/<pid>/environ`; a pipe passed with `pass_fds` is readable as `/dev/fd/N`.
- Tool names and `--version` text: MySQL `mysqldump  Ver 8.4.11 for Linux`; MariaDB 10.2 `mysqldump  Ver 10.19 Distrib 10.2.44-MariaDB`; MariaDB 11.4 `mariadb-dump from 11.4.13-MariaDB, client 10.19`.

## Spec amendments this plan makes (applied in Task 11)

1. Dump needs `SELECT`, `SHOW VIEW`, `TRIGGER` (not `LOCK TABLES`: `--single-transaction` takes no locks). Load needs `CREATE`, `INSERT`, `ALTER`, `DROP`, `INDEX`, `REFERENCES`, `CREATE VIEW`.
2. Codes: `CLIENT_TOO_OLD` is replaced by the `CLIENT_SERVER_SKEW` warning; new `STORED_OBJECTS_PRESENT` (warning, dump: views/triggers carry `DEFINER` clauses and MariaDB keeps their original text), `CROSS_FAMILY_DUMP` (warning, load: collations may not exist on the target), `IDENTITY_REQUIRED` (blocker, load: encrypted source, no identity). `INCOMPATIBLE_DUMP_SOURCE` means precisely: the source begins with MariaDB's sandbox line and the client cannot read it; `allow_unsandboxed=True` strips that one line.
3. New error `CorruptDumpError` for a damaged or truncated encrypted stream, distinct from `DecryptionError` (wrong identity).
4. The option file also sets `protocol=TCP`, so `localhost` means the same server to the client tool as to PyMySQL. Client tools get only `PATH`, `LANG`, `LC_ALL` and `MYSQL_TEST_LOGIN_FILE`.
5. Damage in a source is discovered mid-stream, after earlier statements have run: load into a staging database (as backup does).
6. `check_load` evaluates the source's header only when `source` is a path; `load` always does.
7. `TransferResult.bytes` is the plaintext byte count delivered to (load) or produced by (dump, after encryption) the transfer.
8. Transfer tests run via `make test-transfer ENGINE=<image>` inside the server's own image; CI job `transfer` runs it per engine.

## Review Focus

1. **A consumer that stops iterating a dump early** — the child must be killed and reaped; nothing hangs. Pinned in Task 5 (`test_closing_early_kills_the_tool`).
2. **A client tool that writes more stderr than a pipe buffer holds** — no deadlock; the error carries capped, redacted stderr. Pinned in Task 5 (`test_large_stderr_does_not_deadlock`).
3. **A multi-gigabyte dump** — memory stays bounded; chunks never exceed the chunk size. Pinned in Task 5 (`test_dump_streams_in_bounded_chunks`).
4. **An empty load source** — loads nothing, succeeds, reports 0 bytes. Pinned in Task 6 (`test_empty_source_loads_nothing`).
5. **A password with option-file metacharacters** — reaches the server intact. Pinned in Task 3 (`test_option_values_are_quoted_and_escaped`) and Task 9 (`test_awkward_password_dumps`).

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `Makefile`, `tools/transfer-tests.sh`, `.github/workflows/ci.yml`, `pyproject.toml` | `make test-transfer`, CI job, `transfer` marker, `encryption` extra | 1 |
| `src/l3io/wp/database/verdict.py`, `errors.py` | transfer codes; `TransferError`, `DecryptionError`, `CorruptDumpError` | 2 |
| `src/l3io/wp/database/_client.py` | tool discovery, version parsing, option-file pipe, argv, child env | 3 |
| `src/l3io/wp/database/encryption.py` | age encrypt/decrypt, identities, `generate_identity` | 4 |
| `src/l3io/wp/database/provision.py` | split `_preflight` into resolve + `_preflight_resolved` | 5 |
| `src/l3io/wp/database/transfer.py` | preflight, `DumpStream`, `iter_dump`, `dump`, `load`, checks, `TransferResult` | 5–7 |
| `tests/test_transfer_engine.py` | engine unit tests with fake client scripts | 5–6 |
| `tests/test_transfer_integration.py`, `tests/fixtures/hostile.mylogin.cnf` | real-server transfer tests (marker `transfer`) | 8–9 |
| `src/l3io/wp/database/cli.py`, `facade.py`, `__init__.py` | CLI subcommands, facade methods, exports | 10 |
| `tests/test_secrets.py` | subprocess scope guard replaces "no subprocess" | 10 |
| spec | amendments; final verification | 11 |

---

### Task 0: Branch

- [ ] **Step 1:** `git switch -c feat/plan-2-transfer main` — Expected: on the new branch.

---

### Task 1: Transfer test harness, CI job, extra and marker

**Files:**
- Create: `tools/transfer-tests.sh`
- Modify: `Makefile`, `.github/workflows/ci.yml`, `pyproject.toml`, `uv.lock`
- Test: `tests/test_transfer_environment.py`

**Interfaces:**
- Produces: `make test-transfer ENGINE=<image>`: starts `<image>` as a server on `127.0.0.1:$(TRANSFER_PORT)` (default 33399), runs `tools/transfer-tests.sh` in a second container of the same image with the repo mounted read-only, env `DB_HOST`, `DB_PORT`, `DB_ADMIN_USER=root`, `DB_ADMIN_PASSWORD=root`, `L3IO_ENGINE=<image>`, `L3IO_TRANSFER_CONTAINER=1`; runs `pytest -m transfer`. pytest marker `transfer`. Extra `encryption = ["pyrage>=1.4,<2"]`; dev dependency `pyrage==1.4.0`.

- [ ] **Step 1: Write the environment test** (it is the only `transfer` test until Task 8)

```python
"""The transfer container provides the server's own client tools.

Runs only inside `make test-transfer`, which sets L3IO_TRANSFER_CONTAINER.
"""

from __future__ import annotations

import os
import shutil

import pytest

pytestmark = [
    pytest.mark.transfer,
    pytest.mark.skipif(
        not os.environ.get("L3IO_TRANSFER_CONTAINER"), reason="runs inside make test-transfer"
    ),
]


def test_the_images_client_tools_are_on_path() -> None:
    engine = os.environ["L3IO_ENGINE"]
    names = ("mariadb-dump", "mysqldump") if engine.startswith("mariadb") else ("mysqldump",)
    assert any(shutil.which(n) for n in names), f"no dump tool on PATH in {engine}"
```

- [ ] **Step 2: Register the marker and the extra** — in `pyproject.toml`:
  - `markers` becomes `["slow: builds a wheel or talks to a real database server", "transfer: export/import tests run by make test-transfer inside a server image"]`.
  - `[project.optional-dependencies]` adds `encryption = ["pyrage>=1.4,<2"]`.
  - `[dependency-groups] dev` adds, after the `opentelemetry-sdk` line:
    ```toml
      # The encryption extra, also here because `uv run` prunes extras.
      "pyrage==1.4.0",
    ```
  Run: `uv lock && uv sync --locked --all-extras --dev` — Expected: success.

- [ ] **Step 3: Write `tools/transfer-tests.sh`**

```bash
#!/usr/bin/env bash
# Runs inside a container built from a database SERVER image, so the client
# tools under test are the ones that ship with that server (probe V3). The
# repository is mounted read-only at /repo; everything written goes to /tmp.
set -euo pipefail

if command -v microdnf >/dev/null; then
  microdnf install -y git >/dev/null          # Oracle Linux (mysql:*); no -q flag
else
  apt-get update -qq >/dev/null
  apt-get install -y -qq curl ca-certificates git >/dev/null   # Debian/Ubuntu (mariadb:*)
fi
curl -LsSf https://astral.sh/uv/0.11.6/install.sh | env UV_UNMANAGED_INSTALL=/tmp/uvbin sh >/dev/null

export PATH=/tmp/uvbin:$PATH UV_PROJECT_ENVIRONMENT=/tmp/venv UV_CACHE_DIR=/tmp/uvcache
export UV_PYTHON=3.11 PYTHONDONTWRITEBYTECODE=1
git config --global --add safe.directory /repo
cd /repo
uv sync --locked --all-extras --dev -q

for _ in $(seq 1 90); do
  if uv run --no-sync python -c "import os, pymysql; pymysql.connect(host=os.environ['DB_HOST'], port=int(os.environ['DB_PORT']), user='root', password='root').close()" 2>/dev/null; then
    break
  fi
  sleep 2
done
exec uv run --no-sync pytest -q -p no:cacheprovider -m transfer
```

Run: `chmod +x tools/transfer-tests.sh`.

- [ ] **Step 4: Add the Makefile target** — add `test-transfer` to `.PHONY`, and after `test-db`:

```make
TRANSFER_PORT ?= 33399

test-transfer: ## Export/import tests against ENGINE (a server image) using its own client tools
	@test -n "$(ENGINE)" || { echo "set ENGINE, e.g. make test-transfer ENGINE=mysql:8.4"; exit 1; }
	@set -eu; name="l3io-transfer-$$$$"; \
	docker run -d --rm --name "$$name" -e MYSQL_ROOT_PASSWORD=root -e MARIADB_ROOT_PASSWORD=root \
	  -p 127.0.0.1:$(TRANSFER_PORT):3306 "$(ENGINE)" >/dev/null; \
	trap 'docker rm -f "'"$$name"'" >/dev/null 2>&1' EXIT; \
	docker run --rm --network host -v "$(CURDIR)":/repo:ro \
	  -e L3IO_ENGINE="$(ENGINE)" -e L3IO_TRANSFER_CONTAINER=1 \
	  -e DB_HOST=127.0.0.1 -e DB_PORT=$(TRANSFER_PORT) -e DB_ADMIN_USER=root -e DB_ADMIN_PASSWORD=root \
	  --entrypoint bash "$(ENGINE)" /repo/tools/transfer-tests.sh
```

- [ ] **Step 5: Add the CI job** — in `.github/workflows/ci.yml`, after the `test` job:

```yaml
  transfer:
    # Export and import against each engine, using the client tools that ship
    # in that engine's own image (probe V3). The tests run in a second
    # container of the server image, started by `make test-transfer`, so the
    # same command runs here, under act, and on a developer's machine.
    name: transfer · ${{ matrix.engine }}
    runs-on: ubuntu-latest
    needs: [static]
    strategy:
      fail-fast: false
      matrix:
        engine: >-
          ${{ vars.LOCAL_ACT && fromJSON('["mysql:8.4"]')
              || fromJSON('["mysql:8.0","mysql:8.4","mysql:9.7","mariadb:10.2","mariadb:11.4"]') }}
    steps:
      - uses: actions/checkout@v7
        with: { fetch-depth: 0 }  # hatch-vcs needs tags; shallow yields 0.1.devN
      - name: export and import with the engine's own client tools
        run: make test-transfer ENGINE='${{ matrix.engine }}'
```

Add `transfer` to the `build` job's `needs:` list.

- [ ] **Step 6: Verify**

Run: `make check` — Expected: pass (the environment test is skipped outside the container; `test_act_workspace`, `test_declared_facts`, `test_workflow_actions` accept the new job).
Run: `make test-transfer ENGINE=mysql:8.4` and `make test-transfer ENGINE=mariadb:10.2` — Expected: `1 passed` each.

- [ ] **Step 7: Commit**

```bash
git add tools/transfer-tests.sh Makefile .github/workflows/ci.yml pyproject.toml uv.lock tests/test_transfer_environment.py
git commit -m "ci: make test-transfer runs transfer tests inside each server image (V3)"
```

---

### Task 2: Transfer codes and errors

**Files:**
- Modify: `src/l3io/wp/database/verdict.py`, `src/l3io/wp/database/errors.py`
- Test: `tests/test_verdict.py`, `tests/test_errors.py`

**Interfaces:**
- Produces codes (severity): `CLIENT_TOOL_MISSING` (B), `CLIENT_SERVER_SKEW` (W), `PLATFORM_UNSUPPORTED` (B), `OPTION_NOT_ALLOWED` (B), `DATABASE_NOT_EMPTY` (B), `INCOMPATIBLE_DUMP_SOURCE` (B), `CROSS_FAMILY_DUMP` (W), `STORED_OBJECTS_PRESENT` (W), `IDENTITY_REQUIRED` (B).
- Produces errors: `TransferError(message: str, verdict: Verdict, exit_code: int | None, stderr: str)` with those attributes; `DecryptionError(DatabaseError)`; `CorruptDumpError(DatabaseError)`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_verdict.py`:

```python
@pytest.mark.parametrize(
    ("code", "severity"),
    [
        (Code.CLIENT_TOOL_MISSING, Severity.BLOCKER),
        (Code.CLIENT_SERVER_SKEW, Severity.WARNING),
        (Code.PLATFORM_UNSUPPORTED, Severity.BLOCKER),
        (Code.OPTION_NOT_ALLOWED, Severity.BLOCKER),
        (Code.DATABASE_NOT_EMPTY, Severity.BLOCKER),
        (Code.INCOMPATIBLE_DUMP_SOURCE, Severity.BLOCKER),
        (Code.CROSS_FAMILY_DUMP, Severity.WARNING),
        (Code.STORED_OBJECTS_PRESENT, Severity.WARNING),
        (Code.IDENTITY_REQUIRED, Severity.BLOCKER),
    ],
)
def test_transfer_code_severities(code: Code, severity: Severity) -> None:
    assert code.severity is severity
```

Append to `tests/test_errors.py`:

```python
def test_transfer_error_carries_verdict_exit_code_and_stderr() -> None:
    verdict = Verdict("dump")
    exc = errors.TransferError("dump failed", verdict, 2, "access denied")
    assert (exc.verdict, exc.exit_code, exc.stderr) == (verdict, 2, "access denied")
    assert "dump failed" in str(exc)


def test_decryption_and_corruption_are_distinct() -> None:
    assert not issubclass(errors.DecryptionError, errors.CorruptDumpError)
    assert not issubclass(errors.CorruptDumpError, errors.DecryptionError)
```

- [ ] **Step 2: Run** `uv run pytest -q tests/test_verdict.py tests/test_errors.py` — Expected: FAIL (`AttributeError: CLIENT_TOOL_MISSING`, `TransferError`).

- [ ] **Step 3: Implement** — in `verdict.py` add to `Code` (after `PASSWORD_UNVERIFIED`):

```python
    CLIENT_TOOL_MISSING = "client_tool_missing"
    CLIENT_SERVER_SKEW = "client_server_skew"
    PLATFORM_UNSUPPORTED = "platform_unsupported"
    OPTION_NOT_ALLOWED = "option_not_allowed"
    DATABASE_NOT_EMPTY = "database_not_empty"
    INCOMPATIBLE_DUMP_SOURCE = "incompatible_dump_source"
    CROSS_FAMILY_DUMP = "cross_family_dump"
    STORED_OBJECTS_PRESENT = "stored_objects_present"
    IDENTITY_REQUIRED = "identity_required"
```

to `_SEVERITY`:

```python
        Code.CLIENT_TOOL_MISSING: _B,
        Code.CLIENT_SERVER_SKEW: _W,
        Code.PLATFORM_UNSUPPORTED: _B,
        Code.OPTION_NOT_ALLOWED: _B,
        Code.DATABASE_NOT_EMPTY: _B,
        Code.INCOMPATIBLE_DUMP_SOURCE: _B,
        Code.CROSS_FAMILY_DUMP: _W,
        Code.STORED_OBJECTS_PRESENT: _W,
        Code.IDENTITY_REQUIRED: _B,
```

and to `_DESCRIPTION`:

```python
        Code.CLIENT_TOOL_MISSING: "no suitable dump or client program is on PATH; fields.tools names those tried",
        Code.CLIENT_SERVER_SKEW: (
            "the client program's family, or its major.minor version, is older than or differs "
            "from the server's"
        ),
        Code.PLATFORM_UNSUPPORTED: "export and import need /dev/fd, which this platform lacks",
        Code.OPTION_NOT_ALLOWED: "a caller-supplied client option is not on the allow-list; fields.option names it",
        Code.DATABASE_NOT_EMPTY: "the load target holds tables and replace= was not given",
        Code.INCOMPATIBLE_DUMP_SOURCE: (
            "the dump begins with MariaDB's sandbox line and this client cannot read it; "
            "allow_unsandboxed=True strips that line"
        ),
        Code.CROSS_FAMILY_DUMP: (
            "the dump comes from the other server family; collations it uses may not exist here"
        ),
        Code.STORED_OBJECTS_PRESENT: (
            "the database has views or triggers: they carry DEFINER clauses that loading needs "
            "privilege for, and MariaDB keeps their original text, which may name this schema"
        ),
        Code.IDENTITY_REQUIRED: "the source is age-encrypted and no identity was supplied",
```

In `errors.py` add (with `Verdict` already imported under `TYPE_CHECKING`):

```python
class TransferError(DatabaseError):
    """A dump or load started and failed. ``stderr`` is capped and redacted."""

    def __init__(
        self, message: str, verdict: Verdict, exit_code: int | None, stderr: str
    ) -> None:
        self.verdict = verdict
        self.exit_code = exit_code
        self.stderr = stderr
        super().__init__(message)


class DecryptionError(DatabaseError):
    """None of the supplied identities can decrypt the source."""


class CorruptDumpError(DatabaseError):
    """An encrypted source is truncated, damaged, or not an age file."""
```

- [ ] **Step 4: Run** `uv run pytest -q tests/test_verdict.py tests/test_errors.py && make check` — Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/l3io/wp/database/verdict.py src/l3io/wp/database/errors.py tests/test_verdict.py tests/test_errors.py
git commit -m "feat: transfer finding codes and TransferError/DecryptionError/CorruptDumpError"
```

---

### Task 3: `_client.py` — finding tools and running them without exposing a password

**Files:**
- Create: `src/l3io/wp/database/_client.py`
- Test: `tests/test_client.py`

**Interfaces:**
- Consumes: `Connection`, `ResolvedCredentials`, `ServerFamily`, `InvalidArgumentsError`.
- Produces:
  - `PURPOSE_DUMP = "dump"`, `PURPOSE_LOAD = "load"`, `DUMP_OPTIONS`, `LOAD_OPTIONS` (frozensets of option names).
  - `ClientTool(name, path, family, version, version_text)` with `.understands_sandbox_line -> bool` and `.label -> str` (`"<name> <version_text>"`).
  - `parse_client_version(name: str, path: str, text: str) -> ClientTool` (ValueError if unrecognised).
  - `find_tool(purpose: str, family: ServerFamily) -> ClientTool | None`; `candidates(purpose, family) -> tuple[str, ...]`.
  - `child_env() -> dict[str, str]`.
  - `option_file_text(credentials, connection) -> str`; `option_pipe(credentials, connection)` context manager yielding a readable fd.
  - `disallowed_options(options, allowed) -> list[str]`.
  - `dump_args(tool, database, options) -> list[str]`; `load_args(database, options) -> list[str]`; `argv(tool, fd, args) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

```python
"""Client tools: versions, option files, argument vectors, environment."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from l3io.wp.database import _client
from l3io.wp.database._client import ClientTool, parse_client_version
from l3io.wp.database.connection import Connection
from l3io.wp.database.credentials import ResolvedCredentials
from l3io.wp.database.errors import InvalidArgumentsError
from l3io.wp.database.server import ServerFamily

CONN = Connection(host="db.example", database="wp_site", port=3307)
SECRET = "p#a;s\"s\\w'o rd)"


@pytest.mark.parametrize(
    ("text", "family", "version"),
    [
        ("mysqldump  Ver 8.4.11 for Linux on x86_64 (MySQL Community Server - GPL)", ServerFamily.MYSQL, (8, 4, 11)),
        ("mysql  Ver 8.0.46-0ubuntu0.24.04.4 for Linux on x86_64 ((Ubuntu))", ServerFamily.MYSQL, (8, 0, 46)),
        ("mysqldump  Ver 10.19 Distrib 10.2.44-MariaDB, for debian-linux-gnu (x86_64)", ServerFamily.MARIADB, (10, 2, 44)),
        ("mysql  Ver 15.1 Distrib 10.2.44-MariaDB, for debian-linux-gnu (x86_64)", ServerFamily.MARIADB, (10, 2, 44)),
        ("mariadb-dump from 11.4.13-MariaDB, client 10.19 for debian-linux-gnu (x86_64)", ServerFamily.MARIADB, (11, 4, 13)),
    ],
)
def test_parse_client_version(text: str, family: ServerFamily, version: tuple[int, int, int]) -> None:
    tool = parse_client_version("tool", "/usr/bin/tool", text)
    assert (tool.family, tool.version) == (family, version)


def test_unrecognised_version_is_rejected() -> None:
    with pytest.raises(ValueError, match="version"):
        parse_client_version("tool", "/x", "something else")


@pytest.mark.parametrize(
    ("family", "version", "expected"),
    [
        (ServerFamily.MYSQL, (8, 0, 46), True),
        (ServerFamily.MARIADB, (10, 2, 44), False),
        (ServerFamily.MARIADB, (10, 6, 17), False),
        (ServerFamily.MARIADB, (10, 6, 18), True),
        (ServerFamily.MARIADB, (11, 4, 13), True),
        (ServerFamily.MARIADB, (11, 8, 0), True),
        (ServerFamily.MARIADB, (11, 3, 9), False),
    ],
)
def test_sandbox_line_support(family: ServerFamily, version: tuple[int, int, int], expected: bool) -> None:
    tool = ClientTool("t", "/t", family, version, "t")
    assert tool.understands_sandbox_line is expected


def test_option_values_are_quoted_and_escaped() -> None:
    text = _client.option_file_text(ResolvedCredentials("wp user", SECRET), CONN)
    assert text.splitlines() == [
        "[client]",
        'user="wp user"',
        'password="p#a;s\\"s\\\\w\'o rd)"',
        'host="db.example"',
        "port=3307",
        "protocol=TCP",
    ]


def test_a_nul_in_a_value_is_rejected() -> None:
    with pytest.raises(InvalidArgumentsError):
        _client.option_file_text(ResolvedCredentials("u", "a\x00b"), CONN)


def test_option_pipe_is_readable_once_and_closed_after() -> None:
    with _client.option_pipe(ResolvedCredentials("u", SECRET), CONN) as fd:
        data = os.read(fd, 65536).decode()
    assert "protocol=TCP" in data
    with pytest.raises(OSError):
        os.fstat(fd)


def test_child_env_holds_no_secret_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("MYSQL_PWD", "MYSQL_HOST", "HOME", "MYSQL_TCP_PORT"):
        monkeypatch.setenv(name, "inherited")
    env = _client.child_env()
    assert set(env) == {"PATH", "LANG", "LC_ALL", "MYSQL_TEST_LOGIN_FILE"}
    assert not Path(env["MYSQL_TEST_LOGIN_FILE"]).exists()


def test_argv_puts_the_defaults_file_first() -> None:
    mysql84 = ClientTool("mysqldump", "/usr/bin/mysqldump", ServerFamily.MYSQL, (8, 4, 11), "v")
    mysql80 = ClientTool("mysqldump", "/usr/bin/mysqldump", ServerFamily.MYSQL, (8, 0, 46), "v")
    maria = ClientTool("mariadb-dump", "/usr/bin/mariadb-dump", ServerFamily.MARIADB, (11, 4, 13), "v")
    assert _client.argv(mysql84, 7, ["x"]) == [
        "/usr/bin/mysqldump", "--defaults-file=/dev/fd/7", "--no-login-paths", "x",
    ]
    assert "--no-login-paths" not in _client.argv(mysql80, 7, [])
    assert "--no-login-paths" not in _client.argv(maria, 7, [])


def test_dump_args() -> None:
    mysql = ClientTool("mysqldump", "/m", ServerFamily.MYSQL, (8, 4, 11), "v")
    maria = ClientTool("mariadb-dump", "/m", ServerFamily.MARIADB, (11, 4, 13), "v")
    base = ["--single-transaction", "--quick", "--hex-blob", "--default-character-set=utf8mb4", "--no-tablespaces"]
    assert _client.dump_args(mysql, "wp_site", ["--routines"]) == [*base, "--set-gtid-purged=OFF", "--routines", "wp_site"]
    assert _client.dump_args(maria, "wp_site", []) == [*base, "wp_site"]


def test_load_args() -> None:
    assert _client.load_args("wp_stage", []) == ["--default-character-set=utf8mb4", "--database=wp_stage"]


@pytest.mark.parametrize(
    ("options", "allowed", "bad"),
    [
        (["--routines", "--ignore-table=wp.t"], _client.DUMP_OPTIONS, []),
        (["--defaults-extra-file=/x", "--host=evil", "--result-file=/tmp/x"], _client.DUMP_OPTIONS,
         ["--defaults-extra-file=/x", "--host=evil", "--result-file=/tmp/x"]),
        (["--binary-mode"], _client.LOAD_OPTIONS, []),
        (["--force"], _client.LOAD_OPTIONS, ["--force"]),
    ],
)
def test_option_allow_list(options: list[str], allowed: frozenset[str], bad: list[str]) -> None:
    assert _client.disallowed_options(options, allowed) == bad


def test_find_tool_prefers_the_servers_family(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name, text in [("mariadb-dump", "mariadb-dump from 11.4.13-MariaDB, client 10.19"),
                       ("mysqldump", "mysqldump  Ver 8.4.11 for Linux")]:
        script = tmp_path / name
        script.write_text(f"#!/bin/sh\necho '{text}'\n")
        script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    found = _client.find_tool(_client.PURPOSE_DUMP, ServerFamily.MARIADB)
    assert found is not None and found.name == "mariadb-dump"
    found = _client.find_tool(_client.PURPOSE_DUMP, ServerFamily.MYSQL)
    assert found is not None and found.name == "mysqldump"


def test_find_tool_returns_none_when_absent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    assert _client.find_tool(_client.PURPOSE_LOAD, ServerFamily.MYSQL) is None
```

- [ ] **Step 2: Run** `uv run pytest -q tests/test_client.py` — Expected: FAIL (`ModuleNotFoundError: l3io.wp.database._client`).

- [ ] **Step 3: Implement** `src/l3io/wp/database/_client.py`:

```python
"""The MySQL and MariaDB client programs: finding them, and running them without
exposing a password. Internal.

A password never appears in an argument vector, a child's environment, or a file
on disk (spec §2.4). The client reads its options from an anonymous pipe named
``--defaults-file=/dev/fd/N`` and placed first, which also stops it reading
``~/.my.cnf``. MySQL clients still read ``~/.mylogin.cnf`` after that, so login
paths are suppressed: ``MYSQL_TEST_LOGIN_FILE`` points at nothing for every
client, and MySQL 8.4+ also gets ``--no-login-paths`` (probe V2; MariaDB has no
login-path file). The child environment holds nothing else that could redirect
or authenticate it.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass

from .connection import Connection
from .credentials import ResolvedCredentials
from .errors import InvalidArgumentsError
from .server import ServerFamily

PURPOSE_DUMP = "dump"
PURPOSE_LOAD = "load"

_CANDIDATES: dict[str, dict[ServerFamily, tuple[str, ...]]] = {
    PURPOSE_DUMP: {
        ServerFamily.MARIADB: ("mariadb-dump", "mysqldump"),
        ServerFamily.MYSQL: ("mysqldump",),
    },
    PURPOSE_LOAD: {
        ServerFamily.MARIADB: ("mariadb", "mysql"),
        ServerFamily.MYSQL: ("mysql",),
    },
}

_MARIADB_VERSION = re.compile(r"(?:Distrib|from) (\d+)\.(\d+)\.(\d+)-MariaDB")
_MYSQL_VERSION = re.compile(r"\bVer (\d+)\.(\d+)\.(\d+)")

#: First MariaDB client release, per series, that reads the sandbox line MariaDB
#: dumps begin with (MDEV-33727). MySQL clients read it as a comment (probe V1).
#: A series absent here and older than the newest listed is treated as unable.
_SANDBOX_SINCE: dict[tuple[int, int], int] = {
    (10, 5): 25,
    (10, 6): 18,
    (10, 11): 8,
    (11, 0): 6,
    (11, 1): 5,
    (11, 2): 4,
    (11, 4): 2,
}

_NO_LOGIN_FILE = "/nonexistent/l3io-wordpress-database/no-login-file"

#: Options a caller may add. Anything touching credentials, option files, the
#: host or an output file is refused by omission.
DUMP_OPTIONS = frozenset(
    {
        "--routines",
        "--events",
        "--skip-triggers",
        "--ignore-table",
        "--no-data",
        "--skip-extended-insert",
        "--where",
        "--max-allowed-packet",
    }
)
LOAD_OPTIONS = frozenset({"--binary-mode", "--max-allowed-packet"})


@dataclass(frozen=True, slots=True)
class ClientTool:
    """One client program, and what it is."""

    name: str
    path: str
    family: ServerFamily
    version: tuple[int, int, int]
    version_text: str

    @property
    def label(self) -> str:
        return f"{self.name} {self.version_text}"

    @property
    def understands_sandbox_line(self) -> bool:
        if self.family is ServerFamily.MYSQL:
            return True
        series = self.version[:2]
        if series > max(_SANDBOX_SINCE):
            return True
        since = _SANDBOX_SINCE.get(series)
        return since is not None and self.version[2] >= since


def parse_client_version(name: str, path: str, text: str) -> ClientTool:
    """Interpret a client program's ``--version`` output."""
    match = _MARIADB_VERSION.search(text)
    family = ServerFamily.MARIADB
    if match is None:
        match = _MYSQL_VERSION.search(text)
        family = ServerFamily.MYSQL
    if match is None:
        msg = f"unrecognised client version {text.strip()!r}"
        raise ValueError(msg)
    major, minor, patch = (int(g) for g in match.groups())
    return ClientTool(name, path, family, (major, minor, patch), text.strip())


def child_env() -> dict[str, str]:
    """The entire environment a client program gets.

    No ``HOME``, ``MYSQL_PWD``, ``MYSQL_HOST`` or ``MYSQL_TCP_PORT``: nothing
    inherited can authenticate or redirect it.
    """
    return {
        "PATH": os.environ.get("PATH", os.defpath),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "MYSQL_TEST_LOGIN_FILE": _NO_LOGIN_FILE,
    }


def candidates(purpose: str, family: ServerFamily) -> tuple[str, ...]:
    """Program names to try for this server: its own family's first."""
    other = ServerFamily.MYSQL if family is ServerFamily.MARIADB else ServerFamily.MARIADB
    names = (*_CANDIDATES[purpose][family], *_CANDIDATES[purpose][other])
    return tuple(dict.fromkeys(names))


def find_tool(purpose: str, family: ServerFamily) -> ClientTool | None:
    """The best client program on ``PATH`` for this server, or ``None``."""
    for name in candidates(purpose, family):
        path = shutil.which(name)
        if path is None:
            continue
        try:
            done = subprocess.run(  # noqa: S603 - an absolute path found on PATH, fixed argument
                [path, "--version"],
                capture_output=True,
                text=True,
                timeout=15,
                env=child_env(),
                check=False,
            )
            return parse_client_version(name, path, done.stdout or done.stderr)
        except (OSError, subprocess.SubprocessError, ValueError):
            continue
    return None


def _quote(value: str) -> str:
    """An option-file value: quoted, with backslash, quote and newline escaped (V5)."""
    if "\x00" in value:
        msg = "a connection value cannot contain a NUL character"
        raise InvalidArgumentsError(msg)
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def option_file_text(credentials: ResolvedCredentials, connection: Connection) -> str:
    """The ``[client]`` options a program reads from the pipe."""
    return (
        "[client]\n"
        f"user={_quote(credentials.username)}\n"
        f"password={_quote(credentials.password)}\n"
        f"host={_quote(connection.host)}\n"
        f"port={connection.port}\n"
        "protocol=TCP\n"
    )


@contextmanager
def option_pipe(credentials: ResolvedCredentials, connection: Connection) -> Iterator[int]:
    """A pipe holding the option file; yields its read end, closed on exit.

    Pass the fd with ``pass_fds`` and name it ``/dev/fd/N``. Nothing touches disk.
    """
    data = option_file_text(credentials, connection).encode()
    read_fd, write_fd = os.pipe()
    try:
        while data:
            data = data[os.write(write_fd, data) :]
    finally:
        os.close(write_fd)
    try:
        yield read_fd
    finally:
        os.close(read_fd)


def disallowed_options(options: Sequence[str], allowed: frozenset[str]) -> list[str]:
    """Caller options whose name is not on the allow-list."""
    return [o for o in options if o.split("=", 1)[0] not in allowed]


def _login_path_args(tool: ClientTool) -> list[str]:
    if tool.family is ServerFamily.MYSQL and tool.version >= (8, 4, 0):
        return ["--no-login-paths"]
    return []


def argv(tool: ClientTool, fd: int, args: Sequence[str]) -> list[str]:
    """The full argument vector: the option file first, then login-path suppression."""
    return [tool.path, f"--defaults-file=/dev/fd/{fd}", *_login_path_args(tool), *args]


def dump_args(tool: ClientTool, database: str, options: Sequence[str]) -> list[str]:
    """Consistent, streaming, binary-safe, without CREATE DATABASE/USE (V7)."""
    args = [
        "--single-transaction",
        "--quick",
        "--hex-blob",
        "--default-character-set=utf8mb4",
        "--no-tablespaces",
    ]
    if tool.family is ServerFamily.MYSQL:
        args.append("--set-gtid-purged=OFF")
    return [*args, *options, database]


def load_args(database: str, options: Sequence[str]) -> list[str]:
    return ["--default-character-set=utf8mb4", f"--database={database}", *options]
```

- [ ] **Step 4: Run** `uv run pytest -q tests/test_client.py && make check` — Expected: pass. (`test_secrets.py::test_no_module_spawns_a_subprocess` now fails: it forbids `subprocess`. Replace it in this task by marking it `@pytest.mark.skip(reason="replaced by the subprocess scope guard in plan 2 task 10")` and remove it in Task 10.)

- [ ] **Step 5: Commit**

```bash
git add src/l3io/wp/database/_client.py tests/test_client.py tests/test_secrets.py
git commit -m "feat: client tool discovery, pipe-backed option file and minimal child env (V2, V5, V7)"
```

---

### Task 4: `encryption.py` — age via pyrage

**Files:**
- Create: `src/l3io/wp/database/encryption.py`
- Test: `tests/test_encryption.py`

**Interfaces:**
- Produces: `AGE_HEADER = b"age-encryption.org/v1"`; `generate_identity() -> tuple[str, str]` (`(identity, recipient)`); `read_identity(path: str | Path, passphrase: str | None = None) -> str`; `encrypt(reader: IO[bytes], writer: IO[bytes], recipients: Sequence[str]) -> None`; `decrypt(reader, writer, identities: Sequence[str]) -> None` raising `DecryptionError` (wrong identity) or `CorruptDumpError` (damage), re-raising `BrokenPipeError` unchanged. All raise `MissingDependencyError(extra="encryption", distribution="pyrage")` without the extra.

- [ ] **Step 1: Write the failing tests**

```python
"""age encryption through pyrage (extra: encryption)."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

pytest.importorskip("pyrage")

from l3io.wp.database import encryption
from l3io.wp.database.errors import (
    CorruptDumpError,
    DecryptionError,
    InvalidArgumentsError,
    MissingDependencyError,
)

PLAIN = b"INSERT INTO t VALUES (1);\n" * 5000


def _encrypt(recipient: str) -> bytes:
    out = io.BytesIO()
    encryption.encrypt(io.BytesIO(PLAIN), out, [recipient])
    return out.getvalue()


def test_round_trip() -> None:
    identity, recipient = encryption.generate_identity()
    data = _encrypt(recipient)
    assert data.startswith(encryption.AGE_HEADER)
    out = io.BytesIO()
    encryption.decrypt(io.BytesIO(data), out, [identity])
    assert out.getvalue() == PLAIN


def test_wrong_identity_is_a_decryption_error() -> None:
    _, recipient = encryption.generate_identity()
    other, _ = encryption.generate_identity()
    with pytest.raises(DecryptionError):
        encryption.decrypt(io.BytesIO(_encrypt(recipient)), io.BytesIO(), [other])


@pytest.mark.parametrize("damage", ["truncate", "flip_body", "not_age"])
def test_damage_is_a_corrupt_dump_error(damage: str) -> None:
    identity, recipient = encryption.generate_identity()
    data = bytearray(_encrypt(recipient))
    if damage == "truncate":
        data = data[:-50]
    elif damage == "flip_body":
        data[len(data) // 2] ^= 0xFF
    else:
        data = bytearray(b"hello, not age at all")
    with pytest.raises(CorruptDumpError):
        encryption.decrypt(io.BytesIO(bytes(data)), io.BytesIO(), [identity])


def test_a_bad_recipient_does_not_echo_much(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(InvalidArgumentsError):
        encryption.encrypt(io.BytesIO(b"x"), io.BytesIO(), ["not-a-key-at-all-xxxxxxxxxxxxxxxx"])


def test_a_bad_identity_is_not_echoed() -> None:
    secret = "AGE-SECRET-KEY-NOT-REALLY-VALID-1234567890"
    with pytest.raises(InvalidArgumentsError) as info:
        encryption.decrypt(io.BytesIO(b"x"), io.BytesIO(), [secret])
    assert secret not in str(info.value)


def test_no_recipients_is_rejected() -> None:
    with pytest.raises(InvalidArgumentsError):
        encryption.encrypt(io.BytesIO(b"x"), io.BytesIO(), [])


def test_read_identity_plain_and_passphrase_protected(tmp_path: Path) -> None:
    import pyrage

    identity, _ = encryption.generate_identity()
    plain = tmp_path / "id.txt"
    plain.write_text(f"# created: today\n{identity}\n")
    assert encryption.read_identity(plain) == identity
    wrapped = tmp_path / "id.age"
    wrapped.write_bytes(pyrage.passphrase.encrypt(plain.read_bytes(), "pw"))
    assert encryption.read_identity(wrapped, "pw") == identity
    with pytest.raises(DecryptionError):
        encryption.read_identity(wrapped, "wrong")


def test_missing_extra_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "pyrage", None)
    with pytest.raises(MissingDependencyError) as info:
        encryption.generate_identity()
    assert info.value.extra == "encryption"
```

- [ ] **Step 2: Run** `uv run pytest -q tests/test_encryption.py` — Expected: FAIL (`ModuleNotFoundError: l3io.wp.database.encryption`).

- [ ] **Step 3: Implement** `src/l3io/wp/database/encryption.py`:

```python
"""Optional age encryption of dumps, through ``pyrage`` (extra ``encryption``).

The format is standard age, so any dump this package encrypts can be decrypted
by the stock ``age`` command line. Errors are mapped to package types: a wrong
identity is :class:`DecryptionError`; a damaged, truncated or non-age stream is
:class:`CorruptDumpError` (probe V4). Secret identities never appear in messages.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import IO, Any

from .errors import CorruptDumpError, DecryptionError, InvalidArgumentsError, MissingDependencyError

AGE_HEADER = b"age-encryption.org/v1"
_SECRET_PREFIX = "AGE-SECRET-KEY-"


def _pyrage() -> Any:
    try:
        import pyrage
    except ImportError as exc:
        raise MissingDependencyError(extra="encryption", distribution="pyrage") from exc
    return pyrage


def generate_identity() -> tuple[str, str]:
    """A new age identity and its public recipient: ``(identity, recipient)``."""
    pyrage = _pyrage()
    identity = pyrage.x25519.Identity.generate()
    return str(identity), str(identity.to_public())


def read_identity(path: str | Path, passphrase: str | None = None) -> str:
    """The age identity in a file, optionally passphrase-protected (age's own format)."""
    pyrage = _pyrage()
    data = Path(path).read_bytes()
    if passphrase is not None:
        try:
            data = pyrage.passphrase.decrypt(data, passphrase)
        except pyrage.DecryptError as exc:
            msg = f"could not unlock the identity file {str(path)!r} with that passphrase"
            raise DecryptionError(msg) from exc
    for line in data.decode("utf-8", errors="replace").splitlines():
        if line.strip().startswith(_SECRET_PREFIX):
            return line.strip()
    msg = f"{str(path)!r} holds no age identity"
    raise InvalidArgumentsError(msg)


def _recipients(pyrage: Any, recipients: Sequence[str]) -> list[Any]:
    if not recipients:
        msg = "encryption needs at least one recipient"
        raise InvalidArgumentsError(msg)
    parsed: list[Any] = []
    for recipient in recipients:
        try:
            if recipient.startswith(("ssh-", "ecdsa-")):
                parsed.append(pyrage.ssh.Recipient.from_str(recipient))
            else:
                parsed.append(pyrage.x25519.Recipient.from_str(recipient))
        except Exception as exc:  # noqa: BLE001 - pyrage errors are not a public type (AD-14)
            msg = f"not an age or SSH public key: {recipient[:12]}..."
            raise InvalidArgumentsError(msg) from exc
    return parsed


def _identities(pyrage: Any, identities: Sequence[str]) -> list[Any]:
    if not identities:
        msg = "decryption needs at least one identity"
        raise InvalidArgumentsError(msg)
    parsed: list[Any] = []
    for index, identity in enumerate(identities):
        text = identity.strip()
        try:
            if text.startswith(_SECRET_PREFIX):
                parsed.append(pyrage.x25519.Identity.from_str(text))
            else:
                parsed.append(pyrage.ssh.Identity.from_buffer(text.encode()))
        except Exception as exc:  # noqa: BLE001 - pyrage errors are not a public type (AD-14)
            msg = f"identity #{index + 1} is not a usable age or SSH private key"
            raise InvalidArgumentsError(msg) from exc
    return parsed


def encrypt(reader: IO[bytes], writer: IO[bytes], recipients: Sequence[str]) -> None:
    """Stream ``reader`` into ``writer`` as age, for every recipient."""
    pyrage = _pyrage()
    pyrage.encrypt_io(reader, writer, _recipients(pyrage, recipients))


def decrypt(reader: IO[bytes], writer: IO[bytes], identities: Sequence[str]) -> None:
    """Stream an age ``reader`` into ``writer`` as plaintext."""
    pyrage = _pyrage()
    keys = _identities(pyrage, identities)
    try:
        pyrage.decrypt_io(reader, writer, keys)
    except BrokenPipeError:
        raise  # the consumer stopped reading; not a property of the stream
    except pyrage.DecryptError as exc:
        if "No matching keys" in str(exc):
            msg = "none of the supplied identities can decrypt this dump"
            raise DecryptionError(msg) from exc
        msg = "the encrypted dump is damaged or not an age file"
        raise CorruptDumpError(msg) from exc
    except OSError as exc:
        msg = "the encrypted dump is truncated or damaged"
        raise CorruptDumpError(msg) from exc
```

- [ ] **Step 4: Run** `uv run pytest -q tests/test_encryption.py tests/test_declared_facts.py && make check` — Expected: pass (`test_declared_facts` confirms `MissingDependencyError(extra="encryption", distribution="pyrage")` names what the extra installs).

- [ ] **Step 5: Commit**

```bash
git add src/l3io/wp/database/encryption.py tests/test_encryption.py
git commit -m "feat: age encryption via pyrage behind the encryption extra (V4)"
```

---

### Task 5: Dump engine, preflight, `iter_dump`, `dump`, `check_dump`

**Files:**
- Modify: `src/l3io/wp/database/provision.py` (split `_preflight`)
- Create: `src/l3io/wp/database/transfer.py`
- Test: `tests/test_transfer_engine.py`

**Interfaces:**
- Consumes: Tasks 2–4; plan 1's `_resolve_or_finding`, `_as_package_error`, `_confirmation`, `operation`, `VERDICT_KEY`, `detect_server`, `ServerInfo`, `parse_version`.
- Produces:
  - `provision._preflight_resolved(connection, resolved, operation_name, required, global_required=()) -> tuple[Verdict, Any | None]`; `_preflight` becomes resolve + `_preflight_resolved` (behaviour unchanged).
  - `transfer.TransferResult(bytes: int, duration_ms: float, tool: str, server: ServerInfo, verdict: Verdict)`.
  - `transfer.DumpStream` — iterator of `bytes`; `.result: TransferResult` after exhaustion; `.pid: int`; `close()`; context manager.
  - `transfer.check_dump(connection, credentials, *, options=()) -> Verdict`.
  - `transfer.iter_dump(connection, credentials, *, recipients=None, options=()) -> DumpStream`.
  - `transfer.dump(connection, credentials, to, *, recipients=None, options=()) -> TransferResult` (`to`: writable binary stream, or a path written atomically at mode 0600).
  - Internals used by tests: `transfer._start(tool, args, credentials, connection, *, for_load) -> subprocess.Popen[bytes]`, `transfer.CHUNK` (65536), `transfer.STDERR_CAP` (65536).

- [ ] **Step 1: Split `_preflight`** — in `provision.py`, rename the body after credential resolution into `_preflight_resolved` and make `_preflight` delegate:

```python
def _preflight(
    connection: Connection,
    admin: CredentialSource,
    operation_name: str,
    required: tuple[str, ...],
    global_required: tuple[str, ...] = (),
) -> tuple[Verdict, Any | None]:
    """Resolve the account, then :func:`_preflight_resolved`."""
    resolved = _resolve_or_finding(admin)
    if isinstance(resolved, Finding):
        return Verdict(operation_name, (resolved,)), None
    return _preflight_resolved(connection, resolved, operation_name, required, global_required)


def _preflight_resolved(
    connection: Connection,
    resolved: ResolvedCredentials,
    operation_name: str,
    required: tuple[str, ...],
    global_required: tuple[str, ...] = (),
) -> tuple[Verdict, Any | None]:
    """Connect as this account and check server and privileges.

    Returns the verdict and, only when it holds no blocker, the open session.
    """
    verdict = Verdict(operation_name)
    # ... the existing body from `try: session = open_connection(...)` onward, unchanged
```

Run: `make check` — Expected: pass (pure refactor).

- [ ] **Step 2: Write the failing engine tests** — `tests/test_transfer_engine.py`:

```python
"""The transfer engine against fake client programs, so no server is needed.

Each fake is a shell script on PATH answering ``--version`` like a real tool.
The engine is exercised through its internals (_start, DumpStream, _pump_load)
because the public operations need a live server for their preflight.
"""

from __future__ import annotations

import io
import os
import resource
import signal
import time
from pathlib import Path

import pytest

from l3io.wp.database import _client, transfer
from l3io.wp.database.connection import Connection
from l3io.wp.database.credentials import ResolvedCredentials
from l3io.wp.database.errors import TransferError
from l3io.wp.database.server import parse_version
from l3io.wp.database.verdict import Verdict

CONN = Connection(host="127.0.0.1", database="wp_site", port=3306)
SECRET = "engine-secret-password"
CREDS = ResolvedCredentials("wpuser", SECRET)
SERVER = parse_version("8.4.11")


def fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, body: str) -> _client.ClientTool:
    script = tmp_path / name
    script.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--version" ]; then echo "' + name + '  Ver 8.4.11 for Linux"; exit 0; fi\n'
        + body
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    tool = _client.find_tool(_client.PURPOSE_DUMP if "dump" in name else _client.PURPOSE_LOAD, SERVER.family)
    assert tool is not None
    return tool


def stream(tool: _client.ClientTool, recipients: list[str] | None = None) -> transfer.DumpStream:
    process = transfer._start(tool, ["wp_site"], CREDS, CONN, for_load=False)
    return transfer.DumpStream(
        process, tool=tool, server=SERVER, verdict=Verdict("dump"),
        recipients=recipients, password=SECRET,
    )


def test_dump_yields_the_tools_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tool = fake(tmp_path, monkeypatch, "mysqldump", 'echo "-- MySQL dump"; echo "SELECT 1;"\n')
    s = stream(tool)
    assert b"".join(s) == b"-- MySQL dump\nSELECT 1;\n"
    assert s.result.bytes == len(b"-- MySQL dump\nSELECT 1;\n")
    assert s.result.verdict == Verdict("dump")


def test_the_option_file_is_readable_and_never_echoed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Report only the size of what the defaults file holds, so the test can
    # prove the fd is readable without the password ever being printed.
    tool = fake(tmp_path, monkeypatch, "mysqldump", 'wc -c < "${1#--defaults-file=}"\n')
    out = b"".join(stream(tool))
    assert int(out.strip()) > 0
    assert SECRET.encode() not in out


def test_a_failing_tool_raises_at_the_end_not_silently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tool = fake(
        tmp_path, monkeypatch, "mysqldump",
        f'echo "partial"; echo "mysqldump: Got error: 1044 for {SECRET}" >&2; exit 2\n',
    )
    s = stream(tool)
    with pytest.raises(TransferError) as info:
        list(s)
    assert info.value.exit_code == 2
    assert "1044" in info.value.stderr
    assert SECRET not in info.value.stderr
    assert SECRET not in str(info.value)


def test_closing_early_kills_the_tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tool = fake(tmp_path, monkeypatch, "mysqldump", "while true; do echo 'INSERT INTO t VALUES (1);'; done\n")
    s = stream(tool)
    next(s)
    pid = s.pid
    s.close()
    time.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_large_stderr_does_not_deadlock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tool = fake(
        tmp_path, monkeypatch, "mysqldump",
        "i=0; while [ $i -lt 20000 ]; do echo 'warning: something noisy happened here' >&2; i=$((i+1)); done; exit 3\n",
    )
    s = stream(tool)
    with pytest.raises(TransferError) as info:
        list(s)
    assert info.value.exit_code == 3
    assert len(info.value.stderr) <= transfer.STDERR_CAP + 100


def test_dump_streams_in_bounded_chunks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tool = fake(tmp_path, monkeypatch, "mysqldump", "head -c 50000000 /dev/zero\n")
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    total = 0
    for chunk in stream(tool):
        assert len(chunk) <= transfer.CHUNK
        total += len(chunk)
    assert total == 50_000_000
    grown_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before
    assert grown_kib < 30_000


def test_a_killed_tool_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tool = fake(tmp_path, monkeypatch, "mysqldump", "while true; do echo 'x'; done\n")
    s = stream(tool)
    next(s)
    os.kill(s.pid, signal.SIGKILL)
    with pytest.raises(TransferError):
        list(s)


def test_dump_to_a_path_is_atomic_and_private(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    good = fake(tmp_path, monkeypatch, "mysqldump", 'echo "SELECT 1;"\n')
    target = tmp_path / "out" / "site.sql"
    target.parent.mkdir()
    transfer._write_atomically(stream(good), target)
    assert target.read_bytes() == b"SELECT 1;\n"
    assert (target.stat().st_mode & 0o777) == 0o600


def test_a_failed_dump_leaves_no_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bad = fake(tmp_path, monkeypatch, "mysqldump", 'echo "partial"; exit 2\n')
    target = tmp_path / "site.sql"
    with pytest.raises(TransferError):
        transfer._write_atomically(stream(bad), target)
    assert list(tmp_path.glob("*site.sql*")) == []


def test_encrypted_dump_round_trips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("pyrage")
    from l3io.wp.database import encryption

    identity, recipient = encryption.generate_identity()
    tool = fake(tmp_path, monkeypatch, "mysqldump", 'echo "SELECT 42;"\n')
    data = b"".join(stream(tool, recipients=[recipient]))
    assert data.startswith(encryption.AGE_HEADER)
    out = io.BytesIO()
    encryption.decrypt(io.BytesIO(data), out, [identity])
    assert out.getvalue() == b"SELECT 42;\n"
```

- [ ] **Step 3: Run** `uv run pytest -q tests/test_transfer_engine.py` — Expected: FAIL (`ModuleNotFoundError: l3io.wp.database.transfer`).

- [ ] **Step 4: Implement** `src/l3io/wp/database/transfer.py` (dump half; Task 6 appends the load half):

```python
"""Export and import, through the server's own client programs (spec §7.3).

One engine per direction. :class:`DumpStream` is the dump engine: an iterator of
chunks that raises :class:`TransferError` at the end, instead of stopping, when
the program failed, so a truncated dump is never mistaken for a whole one.
``dump`` writes it to a stream or, atomically, to a path. ``load`` (below) peeks
the source's first bytes to detect age encryption, the dump's family and
MariaDB's sandbox line; it never parses SQL (global rule 1).
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
import uuid
from collections.abc import Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

import pymysql

from . import _client
from ._client import ClientTool
from ._observe import VERDICT_KEY, operation
from .connection import Connection
from .credentials import CredentialSource, ResolvedCredentials
from .errors import DatabaseUnreachableError, RefusedError, TransferError
from .provision import _as_package_error, _confirmation, _preflight_resolved, _resolve_or_finding
from .server import ServerInfo, detect_server
from .verdict import Code, Finding, Verdict

CHUNK = 64 * 1024
STDERR_CAP = 64 * 1024

DUMP_PRIVILEGES = ("SELECT", "SHOW VIEW", "TRIGGER")
LOAD_PRIVILEGES = ("CREATE", "INSERT", "ALTER", "DROP", "INDEX", "REFERENCES", "CREATE VIEW")


@dataclass(frozen=True, slots=True)
class TransferResult:
    """What a dump or load moved, and what its check found."""

    bytes: int
    duration_ms: float
    tool: str
    server: ServerInfo
    verdict: Verdict


class _Stderr:
    """Drains a program's stderr so it can never block, keeping the first STDERR_CAP bytes."""

    def __init__(self, pipe: IO[bytes]) -> None:
        self._pipe = pipe
        self._kept = bytearray()
        self._thread = threading.Thread(target=self._drain, daemon=True)
        self._thread.start()

    def _drain(self) -> None:
        for block in iter(lambda: self._pipe.read(CHUNK), b""):
            room = STDERR_CAP - len(self._kept)
            if room > 0:
                self._kept += block[:room]

    def text(self, password: str) -> str:
        self._thread.join(timeout=10)
        text = self._kept.decode("utf-8", errors="replace")
        return text.replace(password, "***") if password else text


def _start(
    tool: ClientTool,
    args: Sequence[str],
    credentials: ResolvedCredentials,
    connection: Connection,
    *,
    for_load: bool,
) -> subprocess.Popen[bytes]:
    """Run a client program with its options in a pipe and a minimal environment."""
    with _client.option_pipe(credentials, connection) as fd:
        return subprocess.Popen(  # noqa: S603 - argv built from a found tool and an allow-list
            _client.argv(tool, fd, args),
            stdin=subprocess.PIPE if for_load else subprocess.DEVNULL,
            stdout=subprocess.DEVNULL if for_load else subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_client.child_env(),
            pass_fds=(fd,),
            close_fds=True,
        )


class DumpStream:
    """A dump as an iterator of byte chunks.

    If the program fails or is killed, iteration raises :class:`TransferError`
    at the end instead of stopping. :meth:`close` (or leaving a ``with`` block)
    before the end stops the program. ``result`` is set once iteration finishes.
    """

    def __init__(
        self,
        process: subprocess.Popen[bytes],
        *,
        tool: ClientTool,
        server: ServerInfo,
        verdict: Verdict,
        recipients: Sequence[str] | None,
        password: str,
        on_finish: Any = None,
    ) -> None:
        self._process = process
        self._tool = tool
        self._server = server
        self._verdict = verdict
        self._password = password
        self._on_finish = on_finish
        self._started = time.monotonic()
        self._bytes = 0
        self._done = False
        self._error: BaseException | None = None
        self.result: TransferResult | None = None
        if process.stdout is None or process.stderr is None:
            msg = "a dump process needs piped stdout and stderr"
            raise ValueError(msg)
        self._stderr = _Stderr(process.stderr)
        self._reader: IO[bytes] = process.stdout
        self._encrypt_thread: threading.Thread | None = None
        if recipients:
            self._start_encryption(process.stdout, recipients)

    @property
    def pid(self) -> int:
        """The program's process id, for diagnostics."""
        return self._process.pid

    def _start_encryption(self, plaintext: IO[bytes], recipients: Sequence[str]) -> None:
        from . import encryption

        read_fd, write_fd = os.pipe()
        self._reader = os.fdopen(read_fd, "rb")
        writer = os.fdopen(write_fd, "wb")

        def run() -> None:
            try:
                encryption.encrypt(plaintext, writer, recipients)
            except BaseException as exc:  # noqa: BLE001 - re-raised on the consumer's thread
                self._error = exc
            finally:
                writer.close()

        self._encrypt_thread = threading.Thread(target=run, daemon=True)
        self._encrypt_thread.start()

    def __iter__(self) -> DumpStream:
        return self

    def __next__(self) -> bytes:
        if self._done:
            raise StopIteration
        chunk = self._reader.read(CHUNK)
        if chunk:
            self._bytes += len(chunk)
            return chunk
        self._finish()
        raise StopIteration

    def _finish(self) -> None:
        self._done = True
        if self._encrypt_thread is not None:
            self._encrypt_thread.join()
        code = self._process.wait()
        stderr = self._stderr.text(self._password)
        self._reader.close()
        if code != 0 or self._error is not None:
            first = stderr.strip().splitlines()[0] if stderr.strip() else "no error output"
            msg = f"dump failed: {self._tool.name} exited {code}: {first}"
            error = TransferError(msg, self._verdict, code, stderr)
            self._notify(error)
            raise error from self._error
        self.result = TransferResult(
            self._bytes,
            round((time.monotonic() - self._started) * 1000, 1),
            self._tool.label,
            self._server,
            self._verdict,
        )
        self._notify(None)

    def _notify(self, error: BaseException | None) -> None:
        if self._on_finish is not None:
            callback, self._on_finish = self._on_finish, None
            callback(error, self._bytes)

    def close(self) -> None:
        """Stop the program if it is still running."""
        if self._done:
            return
        self._done = True
        self._process.kill()
        self._process.wait()
        self._reader.close()
        if self._encrypt_thread is not None:
            self._encrypt_thread.join(timeout=10)
        self._notify(TransferError("dump closed before it finished", self._verdict, None, ""))

    def __enter__(self) -> DumpStream:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


@dataclass(frozen=True, slots=True)
class _Plan:
    verdict: Verdict
    credentials: ResolvedCredentials | None
    tool: ClientTool | None
    server: ServerInfo | None


def _platform_and_option_findings(
    options: Sequence[str], allowed: frozenset[str]
) -> list[Finding]:
    findings: list[Finding] = []
    if not os.path.isdir("/dev/fd"):
        findings.append(
            Finding(Code.PLATFORM_UNSUPPORTED, "export and import need /dev/fd (Linux or macOS)")
        )
    findings += [
        Finding(
            Code.OPTION_NOT_ALLOWED,
            f"{option.split('=', 1)[0]} is not an allowed option",
            {"option": option.split("=", 1)[0]},
        )
        for option in _client.disallowed_options(options, allowed)
    ]
    return findings


def _tool_findings(purpose: str, server: ServerInfo) -> tuple[ClientTool | None, list[Finding]]:
    tool = _client.find_tool(purpose, server.family)
    if tool is None:
        names = ", ".join(_client.candidates(purpose, server.family))
        return None, [
            Finding(Code.CLIENT_TOOL_MISSING, f"none of {names} is on PATH", {"tools": names})
        ]
    if tool.family is not server.family or tool.version[:2] < server.version[:2]:
        return tool, [
            Finding(
                Code.CLIENT_SERVER_SKEW,
                f"{tool.label} is older than, or a different family from, "
                f"{server.family} {server.version_text}",
                {"tool": tool.label, "server": server.version_text},
            )
        ]
    return tool, []


def _dump_plan(
    connection: Connection, credentials: CredentialSource, options: Sequence[str]
) -> _Plan:
    findings = _platform_and_option_findings(options, _client.DUMP_OPTIONS)
    resolved = _resolve_or_finding(credentials)
    if isinstance(resolved, Finding):
        return _Plan(Verdict("dump", (*findings, resolved)), None, None, None)
    verdict, session = _preflight_resolved(connection, resolved, "dump", DUMP_PRIVILEGES)
    verdict = verdict.with_findings(*findings)
    if session is None:
        return _Plan(verdict, resolved, None, None)
    database = connection.database
    try:
        with session, session.cursor() as cur:
            server = detect_server(cur)
            cur.execute(
                "SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s",
                (database,),
            )
            exists = int(cur.fetchone()[0]) > 0
            stored = 0
            if exists:
                cur.execute(
                    "SELECT (SELECT COUNT(*) FROM information_schema.VIEWS WHERE TABLE_SCHEMA = %s)"
                    " + (SELECT COUNT(*) FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = %s)",
                    (database, database),
                )
                stored = int(cur.fetchone()[0])
    except pymysql.err.MySQLError as exc:
        raise _as_package_error(exc, DatabaseUnreachableError) from exc
    if not exists:
        verdict = verdict.with_findings(
            Finding(Code.DATABASE_ABSENT, f"{database!r} does not exist")
        )
    elif stored:
        verdict = verdict.with_findings(
            Finding(
                Code.STORED_OBJECTS_PRESENT,
                f"{database!r} has {stored} view(s) or trigger(s); loading them elsewhere needs "
                "privilege for their DEFINER, and MariaDB keeps their original text",
                {"count": stored},
            )
        )
    tool, tool_findings = _tool_findings(_client.PURPOSE_DUMP, server)
    return _Plan(verdict.with_findings(*tool_findings), resolved, tool, server)


def check_dump(
    connection: Connection, credentials: CredentialSource, *, options: Sequence[str] = ()
) -> Verdict:
    """What :func:`dump` would find, without running the dump."""
    with operation("check_dump", connection) as fields:
        verdict = _dump_plan(connection, credentials, options).verdict
        fields[VERDICT_KEY] = verdict
        return verdict


def iter_dump(
    connection: Connection,
    credentials: CredentialSource,
    *,
    recipients: Sequence[str] | None = None,
    options: Sequence[str] = (),
) -> DumpStream:
    """The dump as a :class:`DumpStream` of byte chunks (age-encrypted if ``recipients``)."""
    stack = ExitStack()
    fields = stack.enter_context(operation("dump", connection))
    try:
        plan = _dump_plan(connection, credentials, options)
        fields[VERDICT_KEY] = plan.verdict
        if (
            not plan.verdict.ok
            or plan.tool is None
            or plan.server is None
            or plan.credentials is None
        ):
            raise RefusedError(plan.verdict)
        process = _start(
            plan.tool,
            _client.dump_args(plan.tool, connection.database, options),
            plan.credentials,
            connection,
            for_load=False,
        )
    except BaseException as exc:
        stack.__exit__(type(exc), exc, exc.__traceback__)  # logs and ends the span
        raise

    def finish(error: BaseException | None, count: int) -> None:
        fields["bytes"] = count
        if error is None:
            stack.close()
        else:
            stack.__exit__(type(error), error, error.__traceback__)

    return DumpStream(
        process,
        tool=plan.tool,
        server=plan.server,
        verdict=plan.verdict,
        recipients=recipients,
        password=plan.credentials.password,
        on_finish=finish,
    )


def _write_atomically(stream: DumpStream, target: Path) -> None:
    """Write a stream to ``target`` via a private temporary file renamed on success."""
    partial = target.with_name(f".{target.name}.{uuid.uuid4().hex}.partial")
    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            for chunk in stream:
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        os.replace(partial, target)
    except BaseException:
        stream.close()
        partial.unlink(missing_ok=True)
        raise


def dump(
    connection: Connection,
    credentials: CredentialSource,
    to: IO[bytes] | str | os.PathLike[str],
    *,
    recipients: Sequence[str] | None = None,
    options: Sequence[str] = (),
) -> TransferResult:
    """Dump to a writable binary stream, or atomically to a path (mode 0600)."""
    stream = iter_dump(connection, credentials, recipients=recipients, options=options)
    if isinstance(to, (str, os.PathLike)):
        _write_atomically(stream, Path(to))
    else:
        with stream:
            for chunk in stream:
                to.write(chunk)
    if stream.result is None:  # pragma: no cover - iteration always sets it or raises
        msg = "dump finished without a result"
        raise TransferError(msg, Verdict("dump"), None, "")
    return stream.result
```

Note: `_confirmation` is imported here for Task 6.

- [ ] **Step 5: Run** `uv run pytest -q tests/test_transfer_engine.py && make check` — Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add src/l3io/wp/database/provision.py src/l3io/wp/database/transfer.py tests/test_transfer_engine.py
git commit -m "feat: dump engine, check_dump, iter_dump and dump (spec §7.3)"
```

---

### Task 6: Load engine, `load`, `check_load`

**Files:**
- Modify: `src/l3io/wp/database/transfer.py`
- Test: `tests/test_transfer_engine.py`

**Interfaces:**
- Produces:
  - `transfer.SANDBOX_LINE = b"/*M!999999\\- enable the sandbox mode */"`.
  - `transfer.check_load(connection, credentials, *, source=None, replace=None, identities=None, options=(), allow_unsandboxed=False) -> Verdict` (reads the header only when `source` is a path).
  - `transfer.load(connection, credentials, source, *, replace=None, identities=None, options=(), allow_unsandboxed=False) -> TransferResult` (`source`: path, readable binary stream, or iterable of `bytes`).
  - Internals for tests: `transfer._Header(encrypted: bool, family: ServerFamily | None, sandboxed: bool, needs_identity: bool = False)`, `transfer._header(plain_head: bytes | None, *, encrypted: bool) -> _Header`, `transfer._pump_load(process, head, reader, *, decrypt=None, password) -> int`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_transfer_engine.py`:

```python
from l3io.wp.database.server import ServerFamily


@pytest.mark.parametrize(
    ("head", "family", "sandboxed"),
    [
        (b"-- MySQL dump 10.13  Distrib 8.4.11, for Linux (x86_64)\n--\n", ServerFamily.MYSQL, False),
        (b"-- MySQL dump 10.19  Distrib 10.2.44-MariaDB, for debian\n", ServerFamily.MARIADB, False),
        (b"/*M!999999\\- enable the sandbox mode */ \n-- MariaDB dump 10.19-11.4.13-MariaDB\n",
         ServerFamily.MARIADB, True),
        (b"CREATE TABLE t (x INT);\n", None, False),
        (b"", None, False),
    ],
)
def test_header_detection(head: bytes, family: ServerFamily | None, sandboxed: bool) -> None:
    header = transfer._header(head, encrypted=False)
    assert (header.family, header.sandboxed) == (family, sandboxed)


def loader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> subprocess.Popen[bytes]:
    tool = fake(tmp_path, monkeypatch, "mysql", body)
    return transfer._start(tool, ["--database=wp_site"], CREDS, CONN, for_load=True)


def test_load_feeds_everything_to_the_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    received = tmp_path / "received"
    process = loader(tmp_path, monkeypatch, f"cat > {received}\n")
    count = transfer._pump_load(process, b"SELECT 1;\n", io.BytesIO(b"SELECT 2;\n"), password=SECRET)
    assert count == 20
    assert received.read_bytes() == b"SELECT 1;\nSELECT 2;\n"


def test_empty_source_loads_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    process = loader(tmp_path, monkeypatch, "cat > /dev/null\n")
    assert transfer._pump_load(process, b"", io.BytesIO(b""), password=SECRET) == 0


def test_a_failing_client_raises_transfer_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    process = loader(tmp_path, monkeypatch, 'cat > /dev/null; echo "ERROR 1273 at line 26: Unknown collation" >&2; exit 1\n')
    with pytest.raises(TransferError) as info:
        transfer._pump_load(process, b"SELECT 1;\n", io.BytesIO(b""), password=SECRET)
    assert info.value.exit_code == 1
    assert "Unknown collation" in info.value.stderr


def test_a_client_that_dies_early_does_not_hang(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    process = loader(tmp_path, monkeypatch, "exit 4\n")
    big = io.BytesIO(b"x" * 10_000_000)
    with pytest.raises(TransferError) as info:
        transfer._pump_load(process, b"", big, password=SECRET)
    assert info.value.exit_code == 4


def test_iterable_and_stream_sources_are_read_alike() -> None:
    reader = transfer._as_reader([b"ab", b"", b"cd"])
    assert reader.read(3) + reader.read(10) == b"abcd"
```

Add `import subprocess` to the test module's imports.

- [ ] **Step 2: Run** `uv run pytest -q tests/test_transfer_engine.py` — Expected: FAIL (`AttributeError: _header`).

- [ ] **Step 3: Implement** — append to `transfer.py` (and add `import io` and `from collections.abc import Iterable, Iterator` and `from .server import ServerFamily` to the imports; add `from .errors import CorruptDumpError, DecryptionError` to the errors import):

```python
SANDBOX_LINE = b"/*M!999999\\- enable the sandbox mode */"


@dataclass(frozen=True, slots=True)
class _Header:
    """What the first lines of a source say, compared against fixed strings only."""

    encrypted: bool
    family: ServerFamily | None
    sandboxed: bool
    #: Encrypted, and no identity was supplied, so the plaintext is unknown.
    needs_identity: bool = False


def _header(plain_head: bytes | None, *, encrypted: bool) -> _Header:
    if not plain_head:
        return _Header(encrypted, None, False)
    lines = plain_head.split(b"\n", 3)[:3]
    sandboxed = lines[0].startswith(SANDBOX_LINE)
    family: ServerFamily | None = None
    for line in lines:
        if line.startswith(b"-- MariaDB dump") or (
            line.startswith(b"-- MySQL dump") and b"MariaDB" in line
        ):
            family = ServerFamily.MARIADB
            break
        if line.startswith(b"-- MySQL dump"):
            family = ServerFamily.MYSQL
            break
    return _Header(encrypted, family, sandboxed)


class _IterReader(io.RawIOBase):
    def __init__(self, chunks: Iterable[bytes]) -> None:
        self._chunks: Iterator[bytes] = iter(chunks)
        self._pending = b""

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        while not self._pending:
            try:
                self._pending = next(self._chunks)
            except StopIteration:
                return 0
        size = min(len(buffer), len(self._pending))
        buffer[:size] = self._pending[:size]
        self._pending = self._pending[size:]
        return size


def _as_reader(chunks: Iterable[bytes]) -> IO[bytes]:
    return io.BufferedReader(_IterReader(chunks))


def _prefixed(head: bytes, rest: IO[bytes]) -> IO[bytes]:
    def chunks() -> Iterator[bytes]:
        yield head
        yield from iter(lambda: rest.read(CHUNK), b"")

    return _as_reader(chunks())


class _Decrypting:
    """Decrypts ``source`` into a pipe on a thread; ``reader`` is the plaintext end."""

    def __init__(self, source: IO[bytes], identities: Sequence[str]) -> None:
        from . import encryption

        read_fd, write_fd = os.pipe()
        self.reader: IO[bytes] = os.fdopen(read_fd, "rb")
        self.error: BaseException | None = None
        writer = os.fdopen(write_fd, "wb")

        def run() -> None:
            try:
                encryption.decrypt(source, writer, identities)
            except BrokenPipeError:
                pass  # the consumer stopped reading
            except BaseException as exc:  # noqa: BLE001 - re-raised on the consumer's thread
                self.error = exc
            finally:
                writer.close()

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def join(self) -> None:
        self._thread.join()

    def close(self) -> None:
        self.reader.close()
        self._thread.join(timeout=10)


def _pump_load(
    process: subprocess.Popen[bytes],
    head: bytes,
    reader: IO[bytes],
    *,
    decrypt: _Decrypting | None = None,
    password: str,
) -> int:
    """Feed ``head`` then ``reader`` to the program's stdin; return the bytes delivered."""
    if process.stdin is None or process.stderr is None:
        msg = "a load process needs piped stdin and stderr"
        raise ValueError(msg)
    stderr = _Stderr(process.stderr)
    delivered = 0
    try:
        for block in (head, *iter(lambda: reader.read(CHUNK), b"")):
            if not block:
                continue
            process.stdin.write(block)
            delivered += len(block)
    except BrokenPipeError:
        pass  # the program exited; its exit code says why
    if decrypt is not None:
        decrypt.join()
        if decrypt.error is not None:
            process.kill()  # never let a partial final statement run
            process.wait()
            raise decrypt.error
    try:
        process.stdin.close()
    except BrokenPipeError:
        pass
    code = process.wait()
    text = stderr.text(password)
    if code != 0:
        first = text.strip().splitlines()[0] if text.strip() else "no error output"
        msg = f"load failed: exited {code}: {first}"
        raise TransferError(msg, Verdict("load"), code, text)
    return delivered


def _open_source(
    source: IO[bytes] | Iterable[bytes] | str | os.PathLike[str], cleanup: ExitStack
) -> IO[bytes]:
    if isinstance(source, (str, os.PathLike)):
        return cleanup.enter_context(open(source, "rb"))  # noqa: PTH123, SIM115 - closed by cleanup
    if hasattr(source, "read"):
        return source  # type: ignore[return-value]
    return _as_reader(source)  # type: ignore[arg-type]


def _prepare(
    reader: IO[bytes], identities: Sequence[str] | None, cleanup: ExitStack
) -> tuple[_Header, bytes, IO[bytes], _Decrypting | None]:
    """Peek the source: (header, plaintext head, plaintext reader, decryptor)."""
    from . import encryption

    head = reader.read(CHUNK)
    if not head.startswith(encryption.AGE_HEADER):
        return _header(head, encrypted=False), head, reader, None
    if not identities:
        return _Header(True, None, False, needs_identity=True), b"", reader, None
    decrypting = _Decrypting(_prefixed(head, reader), identities)
    cleanup.callback(decrypting.close)
    plain_head = decrypting.reader.read(CHUNK)
    if not plain_head:
        decrypting.join()
        if decrypting.error is not None:
            raise decrypting.error  # wrong identity or damage, before anything is loaded
    return _header(plain_head, encrypted=True), plain_head, decrypting.reader, decrypting


def _load_plan(
    connection: Connection,
    credentials: CredentialSource,
    options: Sequence[str],
    *,
    replace: str | None,
    header: _Header | None,
    allow_unsandboxed: bool,
) -> _Plan:
    findings = _platform_and_option_findings(options, _client.LOAD_OPTIONS)
    if header is not None and header.needs_identity:
        findings.append(
            Finding(Code.IDENTITY_REQUIRED, "the source is age-encrypted; supply identities=")
        )
    resolved = _resolve_or_finding(credentials)
    if isinstance(resolved, Finding):
        return _Plan(Verdict("load", (*findings, resolved)), None, None, None)
    verdict, session = _preflight_resolved(connection, resolved, "load", LOAD_PRIVILEGES)
    verdict = verdict.with_findings(*findings)
    if session is None:
        return _Plan(verdict, resolved, None, None)
    database = connection.database
    try:
        with session, session.cursor() as cur:
            server = detect_server(cur)
            cur.execute(
                "SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s",
                (database,),
            )
            exists = int(cur.fetchone()[0]) > 0
            tables = 0
            if exists:
                cur.execute(
                    "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s",
                    (database,),
                )
                tables = int(cur.fetchone()[0])
    except pymysql.err.MySQLError as exc:
        raise _as_package_error(exc, DatabaseUnreachableError) from exc
    extra: list[Finding] = []
    if not exists:
        extra.append(Finding(Code.DATABASE_ABSENT, f"{database!r} does not exist"))
    elif replace is not None:
        extra += _confirmation(database, replace)
    elif tables:
        extra.append(
            Finding(
                Code.DATABASE_NOT_EMPTY,
                f"{database!r} holds {tables} table(s); pass replace={database!r} to load over them",
                {"tables": tables},
            )
        )
    tool, tool_findings = _tool_findings(_client.PURPOSE_LOAD, server)
    extra += tool_findings
    if header is not None and tool is not None:
        if header.family is not None and header.family is not server.family:
            extra.append(
                Finding(
                    Code.CROSS_FAMILY_DUMP,
                    f"the dump comes from {header.family}; its collations may not exist on "
                    f"{server.family} {server.version_text}",
                )
            )
        if header.sandboxed and not tool.understands_sandbox_line and not allow_unsandboxed:
            extra.append(
                Finding(
                    Code.INCOMPATIBLE_DUMP_SOURCE,
                    f"the dump begins with MariaDB's sandbox line, which {tool.label} cannot "
                    "read; pass allow_unsandboxed=True to strip that one line",
                )
            )
    return _Plan(verdict.with_findings(*extra), resolved, tool, server)
```

Then append the public functions:

```python
def check_load(
    connection: Connection,
    credentials: CredentialSource,
    *,
    source: str | os.PathLike[str] | None = None,
    replace: str | None = None,
    identities: Sequence[str] | None = None,
    options: Sequence[str] = (),
    allow_unsandboxed: bool = False,
) -> Verdict:
    """What :func:`load` would find. The source header is read only for a path."""
    with operation("check_load", connection) as fields, ExitStack() as cleanup:
        header = None
        if source is not None:
            header, *_ = _prepare(_open_source(source, cleanup), identities, cleanup)
        verdict = _load_plan(
            connection, credentials, options,
            replace=replace, header=header, allow_unsandboxed=allow_unsandboxed,
        ).verdict
        fields[VERDICT_KEY] = verdict
        return verdict


def load(
    connection: Connection,
    credentials: CredentialSource,
    source: IO[bytes] | Iterable[bytes] | str | os.PathLike[str],
    *,
    replace: str | None = None,
    identities: Sequence[str] | None = None,
    options: Sequence[str] = (),
    allow_unsandboxed: bool = False,
) -> TransferResult:
    """Load a dump into this database.

    Damage in a source is found mid-stream, after earlier statements ran, so load
    into a staging database and switch to it only after the load is checked.
    """
    started = time.monotonic()
    with operation("load", connection) as fields, ExitStack() as cleanup:
        header, head, reader, decrypting = _prepare(_open_source(source, cleanup), identities, cleanup)
        plan = _load_plan(
            connection, credentials, options,
            replace=replace, header=header, allow_unsandboxed=allow_unsandboxed,
        )
        fields[VERDICT_KEY] = plan.verdict
        if (
            not plan.verdict.ok
            or plan.tool is None
            or plan.server is None
            or plan.credentials is None
        ):
            raise RefusedError(plan.verdict)
        if header.sandboxed and not plan.tool.understands_sandbox_line:
            head = head.split(b"\n", 1)[1] if b"\n" in head else b""
        process = _start(
            plan.tool,
            _client.load_args(connection.database, options),
            plan.credentials,
            connection,
            for_load=True,
        )
        try:
            delivered = _pump_load(
                process, head, reader, decrypt=decrypting, password=plan.credentials.password
            )
        except TransferError as exc:
            raise TransferError(str(exc), plan.verdict, exc.exit_code, exc.stderr) from exc
        fields["bytes"] = delivered
        return TransferResult(
            delivered,
            round((time.monotonic() - started) * 1000, 1),
            plan.tool.label,
            plan.server,
            plan.verdict,
        )
```

- [ ] **Step 4: Run** `uv run pytest -q tests/test_transfer_engine.py && make check` — Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/l3io/wp/database/transfer.py tests/test_transfer_engine.py
git commit -m "feat: load engine, check_load and load with header-only source detection (V1)"
```

---

### Task 7: Hostile login file fixture

**Files:**
- Create: `tests/fixtures/hostile.mylogin.cnf` (binary; `[client] user=nobody host=127.0.0.1`, no password)

- [ ] **Step 1: Generate it with `mysql_config_editor`** (Ubuntu's MySQL client ships it; server images do not):

```bash
mkdir -p tests/fixtures
docker run --rm -v "$PWD/tests/fixtures":/out ubuntu:24.04 bash -c '
  apt-get update -qq >/dev/null && apt-get install -y -qq mysql-client >/dev/null &&
  mysql_config_editor set --login-path=client --user=nobody --host=127.0.0.1 &&
  cp ~/.mylogin.cnf /out/hostile.mylogin.cnf && chmod 644 /out/hostile.mylogin.cnf'
ls -l tests/fixtures/hostile.mylogin.cnf
```
Expected: a ~116-byte file. It holds a user name and host only — no secret.

- [ ] **Step 2: Commit**

```bash
git add tests/fixtures/hostile.mylogin.cnf
git commit -m "test: hostile ~/.mylogin.cnf fixture (user nobody, no password) for V2 tests"
```

---

### Task 8: Real-server transfer tests — round trips and guards

**Files:**
- Create: `tests/test_transfer_integration.py`

**Interfaces:**
- Consumes: the public transfer functions; plan 1's `ensure`, `Connection`, `Explicit`.

- [ ] **Step 1: Write the tests**

```python
"""Export and import against a real server with that server's own client tools.

Runs only inside `make test-transfer ENGINE=<image>` (L3IO_TRANSFER_CONTAINER).
"""

from __future__ import annotations

import io
import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pymysql
import pytest

from l3io.wp.database import Connection, Explicit, ensure
from l3io.wp.database.errors import RefusedError
from l3io.wp.database.transfer import check_dump, check_load, dump, iter_dump, load
from l3io.wp.database.verdict import Code

pytestmark = [
    pytest.mark.transfer,
    pytest.mark.skipif(
        not os.environ.get("L3IO_TRANSFER_CONTAINER"), reason="runs inside make test-transfer"
    ),
]

HOST = os.environ.get("DB_HOST", "127.0.0.1")
PORT = int(os.environ.get("DB_PORT", "3306"))
ENGINE = os.environ.get("L3IO_ENGINE", "")
ROOT = Explicit("root", os.environ.get("DB_ADMIN_PASSWORD", "root"))


def sql(*statements: str, database: str | None = None) -> list[tuple[object, ...]]:
    conn = pymysql.connect(host=HOST, port=PORT, user="root", password="root",
                           database=database, charset="utf8mb4")
    rows: list[tuple[object, ...]] = []
    with conn, conn.cursor() as cur:
        for statement in statements:
            cur.execute(statement)
            rows = list(cur.fetchall())
        conn.commit()
    return rows


@pytest.fixture
def names() -> Iterator[tuple[str, str]]:
    token = uuid.uuid4().hex[:8]
    source, target = f"src_{token}", f"dst_{token}"
    sql(
        f"CREATE DATABASE `{source}` CHARACTER SET utf8mb4",
        f"CREATE DATABASE `{target}` CHARACTER SET utf8mb4",
        f"CREATE TABLE `{source}`.`wp_options` (option_id INT PRIMARY KEY, "
        "option_name VARCHAR(191), option_value LONGBLOB, note VARCHAR(50) CHARACTER SET utf8mb4)",
        f"INSERT INTO `{source}`.`wp_options` VALUES (1, 'db_version', UNHEX('00FF10E2'), 'héllo 🐬')",  # noqa: S608
    )
    yield source, target
    sql(
        f"DROP DATABASE IF EXISTS `{source}`",
        f"DROP DATABASE IF EXISTS `{target}`",
        f"DROP USER IF EXISTS 'u_{token}'@'%'",
    )


def bulk(database: str) -> None:
    """1,000 rows of 2 KB, so a dump is still running after its first chunk."""
    digits = " UNION ALL ".join(f"SELECT {d} AS d" for d in range(10))
    sql(
        f"INSERT INTO `{database}`.`wp_options` "  # noqa: S608 - test fixture
        "SELECT 2 + a.d * 100 + b.d * 10 + c.d, 'bulk', REPEAT('y', 2000), 'z' "
        f"FROM ({digits}) a, ({digits}) b, ({digits}) c"
    )


def checksum(database: str) -> object:
    return sql(f"CHECKSUM TABLE `{database}`.`wp_options`")[0][1]


def site(name: str) -> Connection:
    return Connection(host=HOST, port=PORT, database=name)


def test_round_trip_into_a_differently_named_database(names: tuple[str, str], tmp_path: Path) -> None:
    source, target = names
    path = tmp_path / "site.sql"
    result = dump(site(source), ROOT, path)
    assert result.bytes == path.stat().st_size > 0
    assert b"CREATE DATABASE" not in path.read_bytes()
    load(site(target), ROOT, path)
    assert checksum(target) == checksum(source)


def test_stream_and_iterator_forms(names: tuple[str, str]) -> None:
    source, target = names
    buffer = io.BytesIO()
    dump(site(source), ROOT, buffer)
    chunks = list(iter_dump(site(source), ROOT))
    assert b"".join(chunks).count(b"INSERT INTO") == buffer.getvalue().count(b"INSERT INTO")
    load(site(target), ROOT, iter(chunks))
    assert checksum(target) == checksum(source)


def test_dump_of_an_absent_database_is_refused() -> None:
    with pytest.raises(RefusedError) as info:
        dump(site("no_such_db_x"), ROOT, io.BytesIO())
    assert Code.DATABASE_ABSENT in info.value.verdict.codes


def test_load_into_a_non_empty_database_needs_replace(names: tuple[str, str]) -> None:
    source, target = names
    data = io.BytesIO()
    dump(site(source), ROOT, data)
    with pytest.raises(RefusedError) as info:
        load(site(source), ROOT, io.BytesIO(data.getvalue()))
    assert Code.DATABASE_NOT_EMPTY in info.value.verdict.codes
    with pytest.raises(RefusedError) as info:
        load(site(source), ROOT, io.BytesIO(data.getvalue()), replace=target)
    assert Code.CONFIRMATION_MISMATCH in info.value.verdict.codes
    load(site(source), ROOT, io.BytesIO(data.getvalue()), replace=source)


def test_a_disallowed_option_is_refused(names: tuple[str, str]) -> None:
    verdict = check_dump(site(names[0]), ROOT, options=["--result-file=/tmp/x"])
    assert Code.OPTION_NOT_ALLOWED in verdict.codes


def test_views_and_triggers_are_warned_about(names: tuple[str, str]) -> None:
    source, _ = names
    sql(f"CREATE VIEW `{source}`.`v` AS SELECT option_id FROM `{source}`.`wp_options`")
    verdict = check_dump(site(source), ROOT)
    assert verdict.ok
    assert Code.STORED_OBJECTS_PRESENT in verdict.codes


def test_cross_family_source_is_warned_about(names: tuple[str, str], tmp_path: Path) -> None:
    other = (
        b"-- MariaDB dump 10.19-11.4.13-MariaDB, for debian-linux-gnu (x86_64)\n"
        if not ENGINE.startswith("mariadb")
        else b"-- MySQL dump 10.13  Distrib 8.4.11, for Linux (x86_64)\n"
    )
    path = tmp_path / "other.sql"
    path.write_bytes(other + b"SELECT 1;\n")
    verdict = check_load(site(names[1]), ROOT, source=path)
    assert Code.CROSS_FAMILY_DUMP in verdict.codes


def test_sandbox_line_against_this_client(names: tuple[str, str], tmp_path: Path) -> None:
    """Only MariaDB 10.2's client in the matrix cannot read the sandbox line (V1)."""
    path = tmp_path / "sandboxed.sql"
    path.write_bytes(b"/*M!999999\\- enable the sandbox mode */ \nSELECT 1;\n")
    verdict = check_load(site(names[1]), ROOT, source=path)
    expected = ENGINE == "mariadb:10.2"
    assert (Code.INCOMPATIBLE_DUMP_SOURCE in verdict.codes) is expected
    if expected:
        load(site(names[1]), ROOT, path, allow_unsandboxed=True)
    else:
        load(site(names[1]), ROOT, path)
```

- [ ] **Step 2: Run against two engines**

Run: `make test-transfer ENGINE=mysql:8.4` and `make test-transfer ENGINE=mariadb:10.2`
Expected: all transfer tests pass on both. If one fails, debug with superpowers:systematic-debugging; do not weaken an assertion.

- [ ] **Step 3: Commit**

```bash
git add tests/test_transfer_integration.py
git commit -m "test: transfer round trips, guards and source detection against real servers"
```

---

### Task 9: Real-server tests — secrets, encryption, awkward passwords

**Files:**
- Modify: `tests/test_transfer_integration.py`

- [ ] **Step 1: Append the tests**

```python
import shutil
import tempfile
import threading
import time

from l3io.wp.database.errors import CorruptDumpError, DecryptionError, TransferError

SECRET = "transfer-only-secret-value"


def wordpress_site(name: str, password: str) -> tuple[Connection, Explicit]:
    user = f"u_{name[-8:]}"
    wp = Explicit(user, password)
    ensure(site(name), ROOT, wp)
    return site(name), wp


def test_no_password_in_argv_environment_or_temp_files(names: tuple[str, str]) -> None:
    conn, wp = wordpress_site(names[0], SECRET)
    bulk(names[0])
    before = set(os.listdir(tempfile.gettempdir()))
    stream = iter_dump(conn, wp)
    first = next(stream)
    cmdline = Path(f"/proc/{stream.pid}/cmdline").read_bytes()
    environ = Path(f"/proc/{stream.pid}/environ").read_bytes()
    rest = b"".join(stream)
    assert first and rest is not None
    assert SECRET.encode() not in cmdline
    assert SECRET.encode() not in environ
    assert b"MYSQL_PWD" not in environ
    assert set(os.listdir(tempfile.gettempdir())) == before


def test_hostile_my_cnf_and_mylogin_cnf_change_nothing(names: tuple[str, str]) -> None:
    home = Path.home()
    fixture = Path(__file__).parent / "fixtures" / "hostile.mylogin.cnf"
    planted = [home / ".mylogin.cnf", home / ".my.cnf"]
    saved = {p: p.read_bytes() for p in planted if p.exists()}
    try:
        shutil.copyfile(fixture, planted[0])
        planted[0].chmod(0o600)
        planted[1].write_text("[client]\nuser=nobody\npassword=wrong\nhost=10.255.255.1\n")
        result = dump(site(names[0]), ROOT, io.BytesIO())
        assert result.bytes > 0
    finally:
        for path in planted:
            if path in saved:
                path.write_bytes(saved[path])
            else:
                path.unlink(missing_ok=True)


@pytest.mark.parametrize("password", ["q'uo\"te", "back\\slash", "hash#semi;", "ab);cd", " spaced "])
def test_awkward_password_dumps(names: tuple[str, str], password: str) -> None:
    conn, wp = wordpress_site(names[0], password)
    assert dump(conn, wp, io.BytesIO()).bytes > 0


def test_encrypted_round_trip(names: tuple[str, str], tmp_path: Path) -> None:
    pytest.importorskip("pyrage")
    from l3io.wp.database import encryption

    identity, recipient = encryption.generate_identity()
    path = tmp_path / "site.sql.age"
    dump(site(names[0]), ROOT, path, recipients=[recipient])
    assert path.read_bytes().startswith(encryption.AGE_HEADER)
    with pytest.raises(RefusedError) as info:
        load(site(names[1]), ROOT, path)
    assert Code.IDENTITY_REQUIRED in info.value.verdict.codes
    load(site(names[1]), ROOT, path, identities=[identity])
    assert checksum(names[1]) == checksum(names[0])


def test_wrong_identity_loads_nothing(names: tuple[str, str], tmp_path: Path) -> None:
    pytest.importorskip("pyrage")
    from l3io.wp.database import encryption

    _, recipient = encryption.generate_identity()
    other, _ = encryption.generate_identity()
    path = tmp_path / "site.sql.age"
    dump(site(names[0]), ROOT, path, recipients=[recipient])
    with pytest.raises(DecryptionError):
        load(site(names[1]), ROOT, path, identities=[other])
    assert sql(f"SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = '{names[1]}'")[0][0] == 0  # noqa: S608


def test_truncated_encrypted_dump_is_corrupt(names: tuple[str, str], tmp_path: Path) -> None:
    pytest.importorskip("pyrage")
    from l3io.wp.database import encryption

    identity, recipient = encryption.generate_identity()
    path = tmp_path / "site.sql.age"
    dump(site(names[0]), ROOT, path, recipients=[recipient])
    path.write_bytes(path.read_bytes()[:-40])
    with pytest.raises(CorruptDumpError):
        load(site(names[1]), ROOT, path, identities=[identity])


def test_a_dump_killed_mid_stream_raises(names: tuple[str, str]) -> None:
    bulk(names[0])
    stream = iter_dump(site(names[0]), ROOT)
    next(stream)
    os.kill(stream.pid, 9)
    with pytest.raises(TransferError):
        list(stream)
```

- [ ] **Step 2: Run on all five engines**

```bash
for e in mysql:8.0 mysql:8.4 mysql:9.7 mariadb:10.2 mariadb:11.4; do make test-transfer ENGINE=$e || break; done
```
Expected: every engine passes.

- [ ] **Step 3: Commit**

```bash
git add tests/test_transfer_integration.py
git commit -m "test: transfer secrets, hostile option files, encryption and awkward passwords"
```

---

### Task 10: Public surface — facade, exports, CLI, subprocess guard

**Files:**
- Modify: `src/l3io/wp/database/facade.py`, `__init__.py`, `cli.py`
- Modify: `tests/test_secrets.py`, `tests/test_cli.py`, `tests/test_facade.py`

**Interfaces:**
- Produces: `Database.check_dump/iter_dump/dump/check_load/load` (free functions with `connection` bound); exports `TransferResult`, `DumpStream`, `check_dump`, `iter_dump`, `dump`, `check_load`, `load`, `TransferError`, `DecryptionError`, `CorruptDumpError`, `ClientTool`, `generate_identity`; CLI subcommands `dump` and `load` (and `check dump`, `check load`).

- [ ] **Step 1: Replace the subprocess guard** — in `tests/test_secrets.py` delete `test_no_module_spawns_a_subprocess` and add:

```python
#: The only modules allowed to start processes; each call must pass env=.
SPAWNERS = {"_client.py", "transfer.py"}


def _subprocess_users() -> dict[str, ast.Module]:
    found: dict[str, ast.Module] = {}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Import) and any(a.name == "subprocess" for a in node.names)) or (
                isinstance(node, ast.ImportFrom) and node.module == "subprocess"
            ):
                found[path.name] = tree
    return found


def test_only_the_client_modules_spawn_processes() -> None:
    users = _subprocess_users()
    assert users, "no module imports subprocess -- this guard is vacuous"
    assert set(users) <= SPAWNERS, f"unexpected process spawners: {set(users) - SPAWNERS}"


def test_every_process_gets_an_explicit_environment() -> None:
    missing = []
    for name, tree in _subprocess_users().items():
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"Popen", "run", "call", "check_call", "check_output"}
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "subprocess"
                and not any(k.arg == "env" for k in node.keywords)
            ):
                missing.append(f"{name}:{node.lineno}")
    assert missing == []
```

- [ ] **Step 2: Facade and exports** — add to `facade.py` (import `transfer`):

```python
    def check_dump(self, credentials: CredentialSource, *, options: Sequence[str] = ()) -> Verdict:
        return transfer.check_dump(self._connection, credentials, options=options)

    def iter_dump(
        self, credentials: CredentialSource, *, recipients: Sequence[str] | None = None,
        options: Sequence[str] = (),
    ) -> DumpStream:
        return transfer.iter_dump(self._connection, credentials, recipients=recipients, options=options)

    def dump(
        self, credentials: CredentialSource, to: IO[bytes] | str | os.PathLike[str], *,
        recipients: Sequence[str] | None = None, options: Sequence[str] = (),
    ) -> TransferResult:
        return transfer.dump(self._connection, credentials, to, recipients=recipients, options=options)

    def check_load(
        self, credentials: CredentialSource, *, source: str | os.PathLike[str] | None = None,
        replace: str | None = None, identities: Sequence[str] | None = None,
        options: Sequence[str] = (), allow_unsandboxed: bool = False,
    ) -> Verdict:
        return transfer.check_load(
            self._connection, credentials, source=source, replace=replace,
            identities=identities, options=options, allow_unsandboxed=allow_unsandboxed,
        )

    def load(
        self, credentials: CredentialSource,
        source: IO[bytes] | Iterable[bytes] | str | os.PathLike[str], *,
        replace: str | None = None, identities: Sequence[str] | None = None,
        options: Sequence[str] = (), allow_unsandboxed: bool = False,
    ) -> TransferResult:
        return transfer.load(
            self._connection, credentials, source, replace=replace,
            identities=identities, options=options, allow_unsandboxed=allow_unsandboxed,
        )
```

`facade.py` also needs `import os`, `from collections.abc import Iterable, Sequence`, `from typing import IO`, `from . import transfer` and `from .transfer import DumpStream, TransferResult`.

In `tests/test_facade.py` add `"check_dump", "iter_dump", "dump", "check_load", "load"` to `OPERATIONS` and replace `_free` with:

```python
def _free(name: str) -> Callable[..., Any]:
    for module in (inspection, provision, transfer):
        found = getattr(module, name, None)
        if found is not None:
            return found  # type: ignore[no-any-return]
    raise AssertionError(name)
```
(import `transfer` alongside `inspection, provision`). In `__init__.py` import and export the names listed in this task's Interfaces (keep `__all__` sorted; `tests/test_architecture.py` checks the order).

- [ ] **Step 3: CLI** — in `cli.py`:
  - `_NEEDS_WP` gains `"dump", "load"`; `_CHECKABLE` gains `"dump", "load"`.
  - In `_add_operation_options`:

```python
    if operation == "dump":
        p.add_argument("--output", required=True, help="file to write, or - for stdout")
        p.add_argument("--recipient", action="append", default=[], help="age or SSH public key (repeatable)")
        p.add_argument("--option", action="append", default=[], help="extra dump option (allow-listed)")
    if operation == "load":
        p.add_argument("--input", required=True, help="dump file to read, or - for stdin")
        p.add_argument("--identity", action="append", default=[], help="age identity file (repeatable)")
        p.add_argument("--identity-passphrase-env", metavar="VAR", help="variable holding the identity files' passphrase")
        p.add_argument("--replace", metavar="NAME", help="repeat the target's name to load over its tables")
        p.add_argument("--allow-unsandboxed", action="store_true", help="strip MariaDB's sandbox line for an older client")
        p.add_argument("--option", action="append", default=[], help="extra client option (allow-listed)")
```

  - In `_run`, before the final `drop-database` branch:

```python
    if operation == "dump":
        target = sys.stdout.buffer if args.output == "-" else args.output
        result = dump(connection, _wordpress(args, config), target,
                      recipients=args.recipient or None, options=args.option)
        _emit(result, stream=sys.stderr if args.output == "-" else sys.stdout)
        return Exit.OK
    if operation == "load":
        source = sys.stdin.buffer if args.input == "-" else args.input
        _emit(load(connection, _wordpress(args, config), source, replace=args.replace,
                   identities=_identities(args) or None, options=args.option,
                   allow_unsandboxed=args.allow_unsandboxed))
        return Exit.OK
```

  - Add the check branches to the `checks` dict:

```python
            "dump": lambda: check_dump(connection, _wordpress(args, config), options=args.option),
            "load": lambda: check_load(connection, _wordpress(args, config),
                                       source=None if args.input == "-" else args.input,
                                       replace=args.replace, identities=_identities(args) or None,
                                       options=args.option, allow_unsandboxed=args.allow_unsandboxed),
```

  and make the `check` branch resolve the admin account only for operations that have one (dump and load run as the WordPress account and have no admin options). Replace its first line `admin = _admin(args)` with:

```python
        admin = _admin(args) if operation not in {"dump", "load"} else Explicit("", "")
```
  (the placeholder is never resolved: only the provisioning lambdas use `admin`).

  - Add the helper and the `stream` parameter:

```python
def _identities(args: argparse.Namespace) -> list[str]:
    from .encryption import read_identity

    passphrase = _password(args.identity_passphrase_env, "the identity files") if args.identity_passphrase_env else None
    return [read_identity(path, passphrase) for path in args.identity]


def _emit(value: Any, stream: Any = None) -> None:
    print(json.dumps(_jsonable(value), indent=2), file=stream or sys.stdout)
```

  - Map `DecryptionError` and `CorruptDumpError` to `Exit.FAILED` via the existing `DatabaseError` branch (no change needed) and `TransferError` likewise.

- [ ] **Step 4: CLI tests** — append to `tests/test_cli.py`:

```python
def test_dump_to_stdout_keeps_json_off_stdout(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from l3io.wp.database.server import parse_version
    from l3io.wp.database.transfer import TransferResult

    def fake_dump(connection, credentials, to, **kw):  # type: ignore[no-untyped-def]
        to.write(b"SELECT 1;\n")
        return TransferResult(10, 1.0, "mysqldump 8.4", parse_version("8.4.11"), Verdict("dump"))

    monkeypatch.setattr(cli, "dump", fake_dump)
    assert cli.main(["dump", *SITE, *WP, "--output", "-"]) == cli.Exit.OK
    captured = capsys.readouterr()
    assert '"bytes": 10' in captured.err


def test_load_passes_replace_and_options(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    from l3io.wp.database.server import parse_version
    from l3io.wp.database.transfer import TransferResult

    seen: dict[str, Any] = {}

    def fake_load(connection, credentials, source, **kw):  # type: ignore[no-untyped-def]
        seen.update(source=source, **kw)
        return TransferResult(0, 1.0, "mysql 8.4", parse_version("8.4.11"), Verdict("load"))

    monkeypatch.setattr(cli, "load", fake_load)
    dump_file = tmp_path / "x.sql"
    dump_file.write_text("SELECT 1;\n")
    code = cli.main(["load", *SITE, *WP, "--input", str(dump_file), "--replace", "wp_site", "--option", "--binary-mode"])
    assert code == cli.Exit.OK
    assert (seen["source"], seen["replace"], seen["options"]) == (str(dump_file), "wp_site", ["--binary-mode"])
```

- [ ] **Step 5: Run** `make check` — Expected: pass, including `test_no_option_takes_a_password_value` (the new options end in `-env` or carry no password). Run `make test-transfer ENGINE=mysql:8.4` — Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add src/l3io/wp/database/facade.py src/l3io/wp/database/__init__.py src/l3io/wp/database/cli.py tests/test_secrets.py tests/test_cli.py tests/test_facade.py
git commit -m "feat: dump/load in the facade, exports and CLI; subprocess scope guard"
```

---

### Task 11: Spec amendments and full verification

**Files:**
- Modify: `_bmad-output/planning-artifacts/spec/2026-10-12-l3io-wordpress-database-design.md`

- [ ] **Step 1: Apply the eight amendments** listed under "Spec amendments this plan makes", in present tense, in §6 (codes table: replace `CLIENT_TOO_OLD`, add the four new codes), §7.3 (privileges, `protocol=TCP`, minimal environment, header-only detection, `allow_unsandboxed`, staging note, `check_load` path-only header, `TransferResult.bytes`), §10 (`CorruptDumpError`), §13 (transfer tests run by `make test-transfer` in each server image), and §16 (record V1–V5, V7, V8 results; mark them settled).

- [ ] **Step 2: Full verification**

```bash
make check
for e in mysql:8.0 mysql:8.4 mysql:9.7 mariadb:10.2 mariadb:11.4; do make test-transfer ENGINE=$e || break; done
docker run -d --rm --name l3io-it -e MYSQL_ROOT_PASSWORD=root -p 127.0.0.1:33306:3306 mysql:8.4
until docker exec l3io-it mysqladmin ping -uroot -proot --silent; do sleep 2; done
make test-db DB_HOST=127.0.0.1 DB_PORT=33306 DB_ADMIN_USER=root DB_ADMIN_PASSWORD=root
docker rm -f l3io-it
make ci
uv run python ../l3io-wordpress-backup/scripts/check-cicd-alignment.py
find . -path ./.git -prune -o -path ./.venv -prune -o -user root -print | wc -l
```
Expected: every command succeeds; `make ci` includes the `transfer` job (one leg under act); alignment 0 findings; 0 root-owned files.

- [ ] **Step 3: Commit**

```bash
git add _bmad-output/planning-artifacts/spec/2026-10-12-l3io-wordpress-database-design.md
git commit -m "spec: record plan 2's amendments and the V1-V8 probe results"
```
