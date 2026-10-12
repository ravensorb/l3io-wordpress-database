# Plan 1 of 3 — Core API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 0.0.x surface with the spec's core API — Verdict, credential sources, credential-free `Connection`, server detection, admin-side inspection, honest provisioning with guarded destructive operations, per-operation observability, the `Database` facade and a CLI that never takes a password as an argument — leaving a working, tested package.

**Architecture:** New modules are built beside the old ones (Tasks 2–12), each with its own tests, so the suite stays green throughout. Task 13 switches the package root to the new names and deletes the old modules; Task 14 replaces the CLI. Every mutating operation is split into a preflight that returns a `Verdict` (and, when clean, an open admin session) and an execution step, so `check_X` and `X` run the identical check. Provisioning separates *facts* (queried) from *planning* (a pure function) from *execution*, so idempotence is unit-testable without a server.

**Tech Stack:** Python 3.11+, PyMySQL 1.2, structlog 26.1, opentelemetry-api 1.44 (+ opentelemetry-sdk 1.44 as a dev dependency for span tests), pytest 9, uv 0.11.6, ruff, mypy --strict.

**Spec:** `_bmad-output/planning-artifacts/spec/2026-10-12-l3io-wordpress-database-design.md`

**Plan series:** Plan 1 (this) — core API. Plan 2 — export, import and encryption (§7.3, V1–V5, V7, V8). Plan 3 — release readiness and retirement (§11–14, §15 hand-off, every-code-emitted check). Plans 2 and 3 are written after this one lands, against its real interfaces.

## Global Constraints

- Python `>=3.11`; code must type-check under `mypy --strict` with `python_version = "3.11"`.
- No public name carries a `Wp` prefix (spec §3). Exception: `WpConfigFile`, named for the file.
- No password in an argument vector, child environment, file on disk, log record, span, exception message or `repr` (spec §2.4).
- Administrative operations take administrative credentials explicitly and never fall back to the WordPress account (spec §2.3).
- Existence is answered by the administrator (AD-29).
- GRANT targets use `quote_grant_database`; every other identifier uses `quote_identifier`; identifiers are validated before reaching SQL (spec §7.2, AD-28).
- Never add `__init__.py` at `src/l3io/` or `src/l3io/wp/` (AD-27).
- Only package-owned exception types cross the public boundary; wrap with `raise ... from` (AD-14).
- The package never configures logging; it logs through `structlog` (AD-10, spec §8).
- Optional dependencies are imported inside the function that uses them (AD-8).
- Use the `make` targets (`make check`, `make test-db DB_HOST=127.0.0.1`), not bare tool calls.
- Commit after every task; do not push.

## Spec amendments this plan makes

These refine the approved spec where implementation detail forced a choice. Each is
applied to the spec file in Task 15.

1. **`PRIVILEGES_UNVERIFIED` (warning)** — when the admin session has an active role,
   `information_schema` does not show role-granted privileges, so privilege checks cannot
   be trusted. The check emits this warning instead of `MISSING_PRIVILEGE` blockers (V6).
2. **`WpConfigFile` also exposes `connection()` and `table_prefix`**, so one object reads a
   site's config for both credentials and location. No separate reader class.
3. **`DatabaseUnreachableError`, `AuthenticationFailedError` and `AccessDeniedError` remain**
   for the read operations (`survey`, `schema_version`), which have no check form.
4. **`drop_user` and `drop_database` are idempotent**: an absent target is `changed=False`,
   not a blocker. `rotate_password` and `revoke` keep `USER_ABSENT` as a blocker.
5. **`ensure` requires global `SELECT`** (to read `mysql.user`), reported as
   `MISSING_PRIVILEGE`.
6. **`charset` and `collation` are validated** (`^[A-Za-z0-9_]+$`) because they cannot be
   parameterised.
7. **`Code` grows with the plans that emit codes.** This plan defines the codes it emits;
   Plan 2 adds the transfer codes; Plan 3 adds the every-code-emitted check.
8. **The CLI prints results as JSON on stdout** and keeps a `NOT_READY` exit code for
   `inspect`.

## Review Focus

1. **A WordPress username or database name containing `_` or `%`** — the grant must cover
   exactly that database and no neighbour; `ensure`'s grant-present check must find the
   escaped pattern it wrote, or the second run re-grants forever. Pinned in Task 10 Step 1
   (`test_plan_for_converged_site_is_empty`) and Task 10 Step 9
   (`test_second_ensure_changes_nothing_with_underscore_name`).
2. **A password containing quotes, backslashes, `#`, `;` or `);`** — must reach the server
   intact through `CREATE USER`/`ALTER USER` parameters. Pinned in Task 10 Step 9
   (`test_awkward_password_round_trips`).
3. **An admin account that lacks `SELECT` on `mysql.user` or reaches privileges through a
   role** — must produce a coded verdict, never a crash or a false green. Pinned in Task 7
   Step 1 (`test_role_makes_privileges_unverified`) and Task 10 Step 1
   (`test_missing_select_is_a_blocker`).
4. **A credential source that fails rather than is absent, inside a chain** — must stop the
   chain, never fall through to another credential. Pinned in Task 4 Step 1
   (`test_chain_stops_on_failure`).
5. **Re-running a destructive call against an already-absent target** — must succeed with
   `changed=False`, so a retried cleanup never fails. Pinned in Task 11 Step 7
   (`test_drop_database_twice`).

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `src/l3io/wp/database/verdict.py` | `Severity`, `Code`, `Finding`, `Verdict` | 2 |
| `src/l3io/wp/database/errors.py` | `DatabaseError` hierarchy incl. `CredentialsAbsentError`, `RefusedError` | 3 |
| `src/l3io/wp/database/credentials.py` | `CredentialSource`, `ResolvedCredentials`, `Explicit`, `Environment`, `AwsSecretsManager`, `CredentialChain` | 4 |
| `src/l3io/wp/database/wpconfig.py` | `WpConfigFile` source + reader | 5 |
| `src/l3io/wp/database/connection.py` | `Connection` | 6 |
| `src/l3io/wp/database/_sql.py` | open a PyMySQL connection; classify driver errors | 7 |
| `src/l3io/wp/database/server.py` | `ServerFamily`, `ServerInfo`, `detect_server`, `account_privileges` | 7 |
| `src/l3io/wp/database/_observe.py` | per-operation span + timing + completion event | 8 |
| `src/l3io/wp/database/inspection.py` | `survey`, `Survey`, `inspect`, `schema_version` | 9 |
| `src/l3io/wp/database/versions.py` | `SchemaVersion` (renamed) | 9 |
| `src/l3io/wp/database/provision.py` | preflights, `plan_ensure`, `ensure`, `rotate_password`, `revoke`, `drop_user`, `drop_database`, results | 10, 11 |
| `src/l3io/wp/database/facade.py` | `Database` | 12 |
| `src/l3io/wp/database/__init__.py` | public exports | 13 |
| `src/l3io/wp/database/cli.py` | subcommand CLI | 14 |
| `tests/test_verdict.py`, `tests/test_credentials.py`, `tests/test_wpconfig.py`, `tests/test_connection.py`, `tests/test_server.py`, `tests/test_observability.py`, `tests/test_provision_plan.py`, `tests/test_cli.py`, `tests/test_public_surface.py` | unit tests | per task |
| `tests/test_integration.py` | real-server tests (rewritten) | 9–11, 13 |

Deleted in Task 13: `src/l3io/wp/database/database.py`; classes `WpConnection`, `WpCredentials`, `WpConfigSource`; aliases `WpDatabaseError`, `WpDatabaseVersion`.

---

### Task 0: Preserve the predecessor on `legacy/main`

**Files:** none (git refs only).

- [ ] **Step 1: Create the branch locally from current `main`**

```bash
git branch legacy/main main
git branch --list 'legacy/*'
```
Expected: `legacy/main` listed. Do **not** push; pushing is a confirmed remote action in Plan 3.

---

### Task 1: Probe V6 — privilege and catalog queries on every engine

Throwaway probe; nothing is committed except the recorded result in Task 15's spec amendment. Purpose: confirm the exact `information_schema` queries Task 7 and Tasks 9–11 rely on.

**Files:** Create (outside the repo): `/tmp/l3io-v6/probe.py`

- [ ] **Step 1: Start the five engines**

```bash
for spec in my80:mysql:8.0:33380 my84:mysql:8.4:33384 my97:mysql:9.7:33397 ma102:mariadb:10.2:33302 ma114:mariadb:11.4:33314; do
  IFS=: read n img tag port <<<"$spec"
  docker run -d --rm --name l3io-v6-$n -e MYSQL_ROOT_PASSWORD=root -e MARIADB_ROOT_PASSWORD=root -p 127.0.0.1:$port:3306 $img:$tag
done
```

- [ ] **Step 2: Write the probe**

```python
# /tmp/l3io-v6/probe.py -- run: uv run --with pymysql==1.2.0 python /tmp/l3io-v6/probe.py
import time
import pymysql

PORTS = {"mysql80": 33380, "mysql84": 33384, "mysql97": 33397, "mariadb102": 33302, "mariadb114": 33314}

def connect(port, user="root", password="root"):
    for _ in range(60):
        try:
            return pymysql.connect(host="127.0.0.1", port=port, user=user, password=password, autocommit=True)
        except pymysql.err.OperationalError:
            time.sleep(2)
    raise SystemExit(f"port {port} never came up")

for name, port in PORTS.items():
    c = connect(port)
    with c.cursor() as cur:
        cur.execute("SELECT VERSION(), CURRENT_USER()")
        print(name, cur.fetchone())
        cur.execute("CREATE DATABASE IF NOT EXISTS `wp_probe`")
        cur.execute("CREATE USER IF NOT EXISTS 'u_probe'@'%' IDENTIFIED BY 'p'")
        cur.execute(r"GRANT ALL PRIVILEGES ON `wp\_probe`.* TO 'u_probe'@'%'")
        cur.execute("SELECT PRIVILEGE_TYPE, IS_GRANTABLE FROM information_schema.USER_PRIVILEGES WHERE GRANTEE = %s", ("'root'@'%'",))
        rows = cur.fetchall()
        print("  root global privileges:", len(rows), "grantable:", {r[1] for r in rows}, "has CREATE USER:", any(r[0] == "CREATE USER" for r in rows))
        cur.execute("SELECT TABLE_SCHEMA, PRIVILEGE_TYPE FROM information_schema.SCHEMA_PRIVILEGES WHERE GRANTEE = %s", ("'u_probe'@'%'",))
        rows = cur.fetchall()
        print("  u_probe schema rows:", len(rows), "patterns:", {r[0] for r in rows})
        cur.execute("SELECT COUNT(*) FROM information_schema.SCHEMA_PRIVILEGES WHERE GRANTEE = %s AND %s LIKE TABLE_SCHEMA", ("'u_probe'@'%'", "wp_probe"))
        print("  LIKE match for wp_probe:", cur.fetchone()[0])
        cur.execute("SELECT COUNT(*) FROM information_schema.SCHEMA_PRIVILEGES WHERE GRANTEE = %s AND %s LIKE TABLE_SCHEMA", ("'u_probe'@'%'", "wpXprobe"))
        print("  LIKE match for wpXprobe (must be 0):", cur.fetchone()[0])
        cur.execute("SELECT CURRENT_ROLE()")
        print("  CURRENT_ROLE():", cur.fetchone())
        cur.execute("SELECT 1 FROM mysql.user WHERE User = %s AND Host = %s", ("u_probe", "%"))
        print("  mysql.user lookup:", cur.fetchone())
        cur.execute("DROP USER IF EXISTS 'u_probe'@'%'")
        cur.execute("DROP DATABASE IF EXISTS `wp_probe`")
```

- [ ] **Step 3: Run it and record the output**

Run: `uv run --with pymysql==1.2.0 python /tmp/l3io-v6/probe.py`

Expected on every engine:
- root has `CREATE USER` and some row with `IS_GRANTABLE = 'YES'`;
- `u_probe` schema rows show the escaped pattern `wp\_probe`;
- `LIKE match for wp_probe` ≥ 1 and `wpXprobe` = 0;
- `CURRENT_ROLE()` returns `'NONE'` (MySQL) or `None` (MariaDB);
- `mysql.user lookup` returns `(1,)`.

If any engine differs, stop and adjust Task 7's `account_privileges` and Task 10's `_grant_present` to the observed behaviour **before** writing them, and record the difference in Task 15.

- [ ] **Step 4: Role behaviour**

Append to the probe for `mysql84` and `mariadb114` only, and run again:

```python
# role check: a privilege held only through an active role must NOT appear in USER_PRIVILEGES
cur.execute("CREATE ROLE IF NOT EXISTS 'r_probe'")
cur.execute("GRANT CREATE USER ON *.* TO 'r_probe'")
cur.execute("CREATE USER IF NOT EXISTS 'a_probe'@'%' IDENTIFIED BY 'p'")
cur.execute("GRANT 'r_probe' TO 'a_probe'@'%'")
cur.execute("SET DEFAULT ROLE 'r_probe' FOR 'a_probe'@'%'" if name.startswith("mysql") else "SET DEFAULT ROLE r_probe FOR 'a_probe'@'%'")
a = connect(port, "a_probe", "p")
with a.cursor() as acur:
    acur.execute("SELECT CURRENT_ROLE(), CURRENT_USER()")
    print("  a_probe role/user:", acur.fetchone())
    acur.execute("SELECT PRIVILEGE_TYPE FROM information_schema.USER_PRIVILEGES WHERE GRANTEE = %s", ("'a_probe'@'%'",))
    print("  a_probe visible global privileges:", acur.fetchall())
```
Expected: `CURRENT_ROLE()` names the role; `CREATE USER` is **absent** from the visible privileges. That is the case `PRIVILEGES_UNVERIFIED` exists for.

- [ ] **Step 5: Stop the engines**

```bash
docker rm -f l3io-v6-my80 l3io-v6-my84 l3io-v6-my97 l3io-v6-ma102 l3io-v6-ma114
```

---

### Task 2: `Verdict`

**Files:**
- Create: `src/l3io/wp/database/verdict.py`
- Test: `tests/test_verdict.py`

**Interfaces:**
- Produces: `Severity` (`BLOCKER`, `WARNING`); `Code` (StrEnum) with `.severity -> Severity` and `.description -> str`; `Finding(code: Code, message: str, fields: Mapping[str, str | int | bool] = {})` with `.severity`; `Verdict(operation: str, findings: tuple[Finding, ...] = ())` with `.blockers`, `.warnings`, `.ok`, `.codes -> frozenset[Code]`, `.with_findings(*findings) -> Verdict`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_verdict.py
"""The Verdict vocabulary: one severity per code, and every code described."""

from __future__ import annotations

import pytest

from l3io.wp.database.verdict import Code, Finding, Severity, Verdict


def test_every_code_has_a_severity_and_a_description() -> None:
    for code in Code:
        assert isinstance(code.severity, Severity), code
        assert code.description.strip(), f"{code} has no description"


def test_blockers_and_warnings_are_partitioned() -> None:
    verdict = Verdict(
        "ensure",
        (
            Finding(Code.MISSING_PRIVILEGE, "needs CREATE USER", {"privilege": "CREATE USER"}),
            Finding(Code.END_OF_LIFE_SERVER, "MySQL 8.0 is past end of life"),
        ),
    )
    assert [f.code for f in verdict.blockers] == [Code.MISSING_PRIVILEGE]
    assert [f.code for f in verdict.warnings] == [Code.END_OF_LIFE_SERVER]
    assert not verdict.ok
    assert verdict.codes == frozenset({Code.MISSING_PRIVILEGE, Code.END_OF_LIFE_SERVER})


def test_warnings_alone_are_ok() -> None:
    assert Verdict("ensure", (Finding(Code.END_OF_LIFE_SERVER, "old"),)).ok
    assert Verdict("ensure").ok


def test_with_findings_returns_a_new_verdict() -> None:
    first = Verdict("drop_database")
    second = first.with_findings(Finding(Code.CONFIRMATION_MISMATCH, "wrong name"))
    assert first.findings == ()
    assert not second.ok


@pytest.mark.parametrize(
    ("code", "severity"),
    [
        (Code.UNREACHABLE, Severity.BLOCKER),
        (Code.CONFIRMATION_MISMATCH, Severity.BLOCKER),
        (Code.LIVE_WORDPRESS_SITE, Severity.WARNING),
        (Code.PRIVILEGES_UNVERIFIED, Severity.WARNING),
    ],
)
def test_fixed_severities(code: Code, severity: Severity) -> None:
    assert Finding(code, "x").severity is severity


def test_findings_are_immutable() -> None:
    finding = Finding(Code.UNREACHABLE, "down", {"host": "db"})
    with pytest.raises(TypeError):
        finding.fields["host"] = "other"  # type: ignore[index]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest -q tests/test_verdict.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'l3io.wp.database.verdict'`.

- [ ] **Step 3: Implement**

```python
# src/l3io/wp/database/verdict.py
"""What a check found, as data a caller can branch on.

Every check returns a :class:`Verdict`. An operation runs its check first and
refuses with :class:`~l3io.wp.database.errors.RefusedError` carrying the same
verdict when it holds a blocker; on success the verdict's warnings travel on the
result. A caller therefore branches on :class:`Code` values and never parses a
message.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType


class Severity(StrEnum):
    """Whether a finding stops the operation."""

    BLOCKER = "blocker"
    WARNING = "warning"


class Code(StrEnum):
    """Every finding a check can report. Each code has exactly one severity."""

    UNREACHABLE = "unreachable"
    CREDENTIALS_UNOBTAINABLE = "credentials_unobtainable"
    AUTHENTICATION_FAILED = "authentication_failed"
    SERVER_UNSUPPORTED = "server_unsupported"
    MISSING_PRIVILEGE = "missing_privilege"
    PRIVILEGES_UNVERIFIED = "privileges_unverified"
    DATABASE_ABSENT = "database_absent"
    USER_ABSENT = "user_absent"
    CONFIRMATION_MISMATCH = "confirmation_mismatch"
    LIVE_WORDPRESS_SITE = "live_wordpress_site"
    END_OF_LIFE_SERVER = "end_of_life_server"

    @property
    def severity(self) -> Severity:
        """The fixed severity of this code."""
        return _SEVERITY[self]

    @property
    def description(self) -> str:
        """When this code is raised."""
        return _DESCRIPTION[self]


_B, _W = Severity.BLOCKER, Severity.WARNING

_SEVERITY: Mapping[Code, Severity] = MappingProxyType(
    {
        Code.UNREACHABLE: _B,
        Code.CREDENTIALS_UNOBTAINABLE: _B,
        Code.AUTHENTICATION_FAILED: _B,
        Code.SERVER_UNSUPPORTED: _B,
        Code.MISSING_PRIVILEGE: _B,
        Code.PRIVILEGES_UNVERIFIED: _W,
        Code.DATABASE_ABSENT: _B,
        Code.USER_ABSENT: _B,
        Code.CONFIRMATION_MISMATCH: _B,
        Code.LIVE_WORDPRESS_SITE: _W,
        Code.END_OF_LIFE_SERVER: _W,
    }
)

_DESCRIPTION: Mapping[Code, str] = MappingProxyType(
    {
        Code.UNREACHABLE: "the server could not be reached",
        Code.CREDENTIALS_UNOBTAINABLE: "a credential source failed to supply credentials",
        Code.AUTHENTICATION_FAILED: "the server rejected the supplied account",
        Code.SERVER_UNSUPPORTED: "the server is below MySQL 8.0 or MariaDB 10.2",
        Code.MISSING_PRIVILEGE: (
            "the account lacks a privilege the operation needs; fields.privilege names it"
        ),
        Code.PRIVILEGES_UNVERIFIED: (
            "the account holds an active role, whose privileges information_schema does "
            "not show, so privilege checks were skipped"
        ),
        Code.DATABASE_ABSENT: "the operation needs an existing database",
        Code.USER_ABSENT: "the operation needs an existing account",
        Code.CONFIRMATION_MISMATCH: "confirm= does not equal the operation's target",
        Code.LIVE_WORDPRESS_SITE: (
            "a destructive target has a WordPress options table and schema version"
        ),
        Code.END_OF_LIFE_SERVER: "the server version is past upstream end of life",
    }
)


@dataclass(frozen=True, slots=True)
class Finding:
    """One thing a check found."""

    code: Code
    message: str
    fields: Mapping[str, str | int | bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Frozen dataclasses still hold a mutable dict; freeze the view too.
        object.__setattr__(self, "fields", MappingProxyType(dict(self.fields)))

    @property
    def severity(self) -> Severity:
        """The code's fixed severity."""
        return self.code.severity


@dataclass(frozen=True, slots=True)
class Verdict:
    """Everything one check found about one operation."""

    operation: str
    findings: tuple[Finding, ...] = ()

    @property
    def blockers(self) -> tuple[Finding, ...]:
        """Findings that stop the operation."""
        return tuple(f for f in self.findings if f.severity is Severity.BLOCKER)

    @property
    def warnings(self) -> tuple[Finding, ...]:
        """Findings that let the operation run but describe a risk."""
        return tuple(f for f in self.findings if f.severity is Severity.WARNING)

    @property
    def ok(self) -> bool:
        """Whether nothing blocks the operation."""
        return not self.blockers

    @property
    def codes(self) -> frozenset[Code]:
        """Every code present."""
        return frozenset(f.code for f in self.findings)

    def with_findings(self, *findings: Finding) -> Verdict:
        """A new verdict with ``findings`` appended."""
        return Verdict(self.operation, self.findings + findings)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest -q tests/test_verdict.py && make lint types`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/l3io/wp/database/verdict.py tests/test_verdict.py
git commit -m "feat: Verdict, Finding and the Code catalogue (spec §6)"
```

---

### Task 3: Error hierarchy

**Files:**
- Modify: `src/l3io/wp/database/errors.py`
- Test: `tests/test_errors.py`

**Interfaces:**
- Consumes: `Verdict` (Task 2).
- Produces: `DatabaseError` (base; `WpDatabaseError` kept as an alias until Task 13); `CredentialsAbsentError(message, sources: tuple[str, ...] = ())` with `.sources`; `RefusedError(verdict: Verdict)` with `.verdict`; `ProvisioningError(message, completed: tuple[str, ...] = ())` with `.completed`. All existing classes keep their names and now derive from `DatabaseError`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_errors.py
from __future__ import annotations

from l3io.wp.database import errors
from l3io.wp.database.verdict import Code, Finding, Verdict


def test_every_error_derives_from_database_error() -> None:
    for name in dir(errors):
        obj = getattr(errors, name)
        if isinstance(obj, type) and issubclass(obj, Exception) and obj is not Exception:
            assert issubclass(obj, errors.DatabaseError), name


def test_refused_error_carries_the_verdict_and_names_each_blocker() -> None:
    verdict = Verdict(
        "drop_database",
        (
            Finding(Code.CONFIRMATION_MISMATCH, "confirm='wp_a' but the target is 'wp_b'"),
            Finding(Code.LIVE_WORDPRESS_SITE, "looks live"),
        ),
    )
    exc = errors.RefusedError(verdict)
    assert exc.verdict is verdict
    assert "drop_database refused" in str(exc)
    assert "confirmation_mismatch" in str(exc)
    assert "live_wordpress_site" not in str(exc)  # warnings are not reasons for refusal


def test_credentials_absent_lists_sources() -> None:
    exc = errors.CredentialsAbsentError("nothing", sources=("environment:A,B",))
    assert exc.sources == ("environment:A,B",)


def test_provisioning_error_records_completed_steps() -> None:
    exc = errors.ProvisioningError("grant failed", completed=("create_database",))
    assert exc.completed == ("create_database",)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest -q tests/test_errors.py`
Expected: FAIL — `AttributeError: module ... has no attribute 'DatabaseError'`.

- [ ] **Step 3: Implement** — edit `src/l3io/wp/database/errors.py`:

Replace the base class block:

```python
class DatabaseError(Exception):
    """Base class for every error this package raises."""


#: Removed in Task 13 of plan 1, once nothing imports the old name.
WpDatabaseError = DatabaseError
```

Change every `(WpDatabaseError)` base in the file to `(DatabaseError)`. Then add, after `CredentialsUnobtainableError`:

```python
class CredentialsAbsentError(DatabaseError):
    """A credential source had nothing to offer.

    Distinct from :class:`CredentialsUnobtainableError`: an unset variable is
    absence, a refused AWS call is failure. A
    :class:`~l3io.wp.database.CredentialChain` moves on only after absence.
    """

    def __init__(self, message: str, sources: tuple[str, ...] = ()) -> None:
        self.sources = sources
        super().__init__(message)
```

Add at the end of the file (with `from typing import TYPE_CHECKING` and a `TYPE_CHECKING` import of `Verdict` from `.verdict` at the top):

```python
class RefusedError(DatabaseError):
    """A check found a blocker, so the operation did not run."""

    def __init__(self, verdict: Verdict) -> None:
        self.verdict = verdict
        reasons = "; ".join(f"{f.code}: {f.message}" for f in verdict.blockers)
        super().__init__(f"{verdict.operation} refused: {reasons}")
```

Replace `ProvisioningError`:

```python
class ProvisioningError(DatabaseError):
    """A provisioning operation started and failed part-way."""

    def __init__(self, message: str, completed: tuple[str, ...] = ()) -> None:
        self.completed = completed
        super().__init__(message)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest -q tests/test_errors.py && make check`
Expected: all pass (old code still imports `WpDatabaseError` through the alias).

- [ ] **Step 5: Commit**

```bash
git add src/l3io/wp/database/errors.py tests/test_errors.py
git commit -m "feat: DatabaseError base, CredentialsAbsentError, RefusedError (spec §10)"
```

---

### Task 4: Credential sources and the chain

**Files:**
- Modify: `src/l3io/wp/database/credentials.py`
- Test: `tests/test_credential_sources.py` (new; `tests/test_credentials.py` covers `WpCredentials` until Task 13)

**Interfaces:**
- Consumes: `CredentialsAbsentError`, `CredentialsUnobtainableError`, `InvalidArgumentsError`, `MissingDependencyError`, `RegionNotKnownError` (Task 3).
- Produces:
  - `CredentialSource` — `runtime_checkable` Protocol: property `source -> str`; method `resolve() -> ResolvedCredentials`.
  - `ResolvedCredentials(username: str, password: str, source: str = "explicit")`, frozen, password redacted in `repr`.
  - `Explicit(username: str, password: str)`; `.source == "explicit"`.
  - `Environment(username_var: str = "DB_USER", password_var: str = "DB_PASSWORD")`; `.source == f"environment:{username_var},{password_var}"`; both unset → `CredentialsAbsentError`; exactly one unset → `CredentialsUnobtainableError`.
  - `AwsSecretsManager(secret_id: str, region: str | None = None)`; `.source == f"aws-secrets-manager:{secret_id}"`.
  - `CredentialChain(*sources: CredentialSource)`; `.source == "chain(" + ", ".join(...) + ")"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_credential_sources.py
"""Credential sources: absent versus failed, and the chain that respects it."""

from __future__ import annotations

import pytest

from l3io.wp.database.credentials import (
    AwsSecretsManager,
    CredentialChain,
    CredentialSource,
    Environment,
    Explicit,
    ResolvedCredentials,
)
from l3io.wp.database.errors import (
    CredentialsAbsentError,
    CredentialsUnobtainableError,
    InvalidArgumentsError,
)

SECRET = "s3cr3t-value"


class _Failing:
    source = "failing"

    def resolve(self) -> ResolvedCredentials:
        raise CredentialsUnobtainableError("refused")


class _Absent:
    source = "absent"

    def resolve(self) -> ResolvedCredentials:
        raise CredentialsAbsentError("nothing here", sources=(self.source,))


def test_protocol_accepts_a_plain_object() -> None:
    assert isinstance(_Failing(), CredentialSource)
    assert isinstance(Explicit("u", "p"), CredentialSource)


def test_explicit_resolves_and_redacts() -> None:
    source = Explicit("wpuser", SECRET)
    resolved = source.resolve()
    assert resolved == ResolvedCredentials("wpuser", SECRET, "explicit")
    assert SECRET not in repr(source)
    assert SECRET not in repr(resolved)


def test_empty_password_is_a_value() -> None:
    assert Explicit("u", "").resolve().password == ""


def test_environment_both_unset_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("X_USER", raising=False)
    monkeypatch.delenv("X_PASS", raising=False)
    with pytest.raises(CredentialsAbsentError) as info:
        Environment("X_USER", "X_PASS").resolve()
    assert info.value.sources == ("environment:X_USER,X_PASS",)


def test_environment_half_set_is_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("X_USER", "u")
    monkeypatch.delenv("X_PASS", raising=False)
    with pytest.raises(CredentialsUnobtainableError, match="X_PASS"):
        Environment("X_USER", "X_PASS").resolve()


def test_environment_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("X_USER", "u")
    monkeypatch.setenv("X_PASS", SECRET)
    resolved = Environment("X_USER", "X_PASS").resolve()
    assert (resolved.username, resolved.password) == ("u", SECRET)
    assert resolved.source == "environment:X_USER,X_PASS"


def test_chain_skips_absent_and_names_who_answered() -> None:
    resolved = CredentialChain(_Absent(), Explicit("u", "p")).resolve()
    assert resolved.source == "explicit"


def test_chain_stops_on_failure() -> None:
    with pytest.raises(CredentialsUnobtainableError):
        CredentialChain(_Failing(), Explicit("u", "p")).resolve()


def test_chain_all_absent_names_every_source() -> None:
    with pytest.raises(CredentialsAbsentError) as info:
        CredentialChain(_Absent(), _Absent()).resolve()
    assert info.value.sources == ("absent", "absent")


def test_empty_chain_is_rejected() -> None:
    with pytest.raises(InvalidArgumentsError):
        CredentialChain()


def test_aws_source_label_names_the_secret_not_its_value() -> None:
    assert AwsSecretsManager("prod/wp-admin", region="us-east-1").source == (
        "aws-secrets-manager:prod/wp-admin"
    )
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest -q tests/test_credential_sources.py`
Expected: FAIL — `ImportError: cannot import name 'AwsSecretsManager'`.

- [ ] **Step 3: Implement** — edit `src/l3io/wp/database/credentials.py`.

Replace the `ResolvedCredentials` class with:

```python
@dataclass(frozen=True, slots=True)
class ResolvedCredentials:
    """A concrete username and password, and which source produced them.

    The password is redacted in ``repr`` so it cannot reach a log line or a
    traceback frame summary by accident.
    """

    username: str
    password: str
    source: str = "explicit"

    def __repr__(self) -> str:
        return (
            f"ResolvedCredentials(username={self.username!r}, password='***', "
            f"source={self.source!r})"
        )
```

Add imports at the top: `import os`, `from typing import Any, Protocol, runtime_checkable`, and extend the errors import with `CredentialsAbsentError`.

Add after `ResolvedCredentials`:

```python
@runtime_checkable
class CredentialSource(Protocol):
    """Anything that can produce credentials. Nothing needs to subclass a package type."""

    @property
    def source(self) -> str:
        """A label for logs and errors. Never the secret."""
        ...

    def resolve(self) -> ResolvedCredentials:
        """Obtain the credentials, performing I/O if the source requires it.

        Raises:
            CredentialsAbsentError: the source has nothing to offer.
            CredentialsUnobtainableError: the source tried and failed.
        """
        ...


@dataclass(frozen=True, slots=True, repr=False)
class Explicit:
    """Credentials given directly."""

    username: str
    password: str

    @property
    def source(self) -> str:
        return "explicit"

    def resolve(self) -> ResolvedCredentials:
        return ResolvedCredentials(self.username, self.password, self.source)

    def __repr__(self) -> str:
        return f"Explicit(username={self.username!r}, password='***')"


@dataclass(frozen=True, slots=True)
class Environment:
    """Credentials held in two environment variables."""

    username_var: str = "DB_USER"
    password_var: str = "DB_PASSWORD"

    @property
    def source(self) -> str:
        return f"environment:{self.username_var},{self.password_var}"

    def resolve(self) -> ResolvedCredentials:
        username = os.environ.get(self.username_var)
        password = os.environ.get(self.password_var)
        if username is None and password is None:
            msg = f"neither {self.username_var} nor {self.password_var} is set"
            raise CredentialsAbsentError(msg, sources=(self.source,))
        if username is None or password is None:
            unset = self.username_var if username is None else self.password_var
            msg = f"{unset} is not set, although its partner variable is"
            raise CredentialsUnobtainableError(msg)
        return ResolvedCredentials(username, password, self.source)


@dataclass(frozen=True, slots=True)
class AwsSecretsManager:
    """Credentials held in AWS Secrets Manager as JSON ``username``/``password``.

    Needs the ``aws`` extra.
    """

    secret_id: str
    region: str | None = None

    @property
    def source(self) -> str:
        return f"aws-secrets-manager:{self.secret_id}"

    def resolve(self) -> ResolvedCredentials:
        try:
            import boto3
        except ImportError as exc:
            raise MissingDependencyError(extra="aws", distribution="boto3") from exc

        region = self.region or boto3.session.Session().region_name
        if not region:
            raise RegionNotKnownError

        _log.debug("resolving secret", source=self.source, region=region)
        try:
            client = boto3.client("secretsmanager", region_name=region)
            payload: Any = client.get_secret_value(SecretId=self.secret_id)["SecretString"]
            document = json.loads(payload)
            username, password = document["username"], document["password"]
        except (KeyError, ValueError) as exc:
            msg = (
                f"secret {self.secret_id!r} is not shaped as expected: "
                "it must be JSON containing 'username' and 'password'"
            )
            raise CredentialsUnobtainableError(msg) from exc
        except Exception as exc:  # noqa: BLE001 - boto3 errors are not a public type (AD-14)
            msg = f"could not read secret {self.secret_id!r} from AWS Secrets Manager"
            raise CredentialsUnobtainableError(msg) from exc
        return ResolvedCredentials(str(username), str(password), self.source)


class CredentialChain:
    """The first source with an answer.

    Moves to the next source only when one is *absent*. A source that *failed*
    stops the chain, because falling through to a different credential after a
    failure is a silent substitution.
    """

    __slots__ = ("_sources",)

    def __init__(self, *sources: CredentialSource) -> None:
        if not sources:
            msg = "a CredentialChain needs at least one source"
            raise InvalidArgumentsError(msg)
        self._sources = sources

    @property
    def source(self) -> str:
        return "chain(" + ", ".join(s.source for s in self._sources) + ")"

    def resolve(self) -> ResolvedCredentials:
        tried: list[str] = []
        for candidate in self._sources:
            try:
                return candidate.resolve()
            except CredentialsAbsentError:
                tried.append(candidate.source)
        msg = "no credential source had an answer: " + ", ".join(tried)
        raise CredentialsAbsentError(msg, sources=tuple(tried))

    def __repr__(self) -> str:
        return f"CredentialChain({self.source})"
```

Leave `WpCredentials` in place (removed in Task 13).

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest -q tests/test_credential_sources.py tests/test_credentials.py tests/test_secrets.py && make lint types`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/l3io/wp/database/credentials.py tests/test_credential_sources.py
git commit -m "feat: CredentialSource protocol, built-in sources and CredentialChain (spec §5)"
```

---

### Task 5: `WpConfigFile` source and reader

**Files:**
- Modify: `src/l3io/wp/database/wpconfig.py`
- Test: `tests/test_wpconfig_file.py` (new; `tests/test_wpconfig.py` keeps covering `WpConfigSource` until Task 13)

**Interfaces:**
- Consumes: `ResolvedCredentials`, `CredentialsAbsentError` (Tasks 3–4); `Connection.from_db_host` (Task 6 — implement Task 6 first if executing out of order; this task's `connection()` test imports it).
- Produces: `WpConfigFile(path: str | Path)` with `.path`, `.table_prefix`, `.source == f"wp-config:{path}"`, `.resolve() -> ResolvedCredentials` (both `DB_USER` and `DB_PASSWORD` undefined → `CredentialsAbsentError`; one undefined → `MissingConfigValueError`), `.connection() -> Connection`.

**Order note:** do Task 6 before this task.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_wpconfig_file.py
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("l3io.wp.config")

from l3io.wp.database.connection import Connection
from l3io.wp.database.credentials import CredentialSource
from l3io.wp.database.errors import CredentialsAbsentError, MissingConfigValueError
from l3io.wp.database.wpconfig import WpConfigFile


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "wp-config.php"
    path.write_text("<?php\n" + body, encoding="utf-8")
    return path


def test_resolves_credentials_and_connection(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "define('DB_NAME', 'wp_site');\ndefine('DB_USER', 'wpuser');\n"
        "define('DB_PASSWORD', 'pw');\ndefine('DB_HOST', 'db:3307');\n"
        "$table_prefix = 'xy_';\n",
    )
    source = WpConfigFile(path)
    assert isinstance(source, CredentialSource)
    resolved = source.resolve()
    assert (resolved.username, resolved.password) == ("wpuser", "pw")
    assert resolved.source == f"wp-config:{path}"
    assert source.connection() == Connection(host="db", database="wp_site", port=3307)
    assert source.table_prefix == "xy_"


def test_no_credentials_defined_is_absent(tmp_path: Path) -> None:
    with pytest.raises(CredentialsAbsentError):
        WpConfigFile(write(tmp_path, "define('DB_NAME', 'wp');\n")).resolve()


def test_half_defined_is_a_failure(tmp_path: Path) -> None:
    with pytest.raises(MissingConfigValueError, match="DB_PASSWORD"):
        WpConfigFile(write(tmp_path, "define('DB_USER', 'u');\n")).resolve()


def test_default_prefix(tmp_path: Path) -> None:
    assert WpConfigFile(write(tmp_path, "define('DB_USER', 'u');\n")).table_prefix == "wp_"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest -q tests/test_wpconfig_file.py`
Expected: FAIL — `ImportError: cannot import name 'WpConfigFile'`.

- [ ] **Step 3: Implement** — add to `src/l3io/wp/database/wpconfig.py` (keep `WpConfigSource` until Task 13). Add imports `from .connection import Connection`, `from .credentials import ResolvedCredentials` and `CredentialsAbsentError` to the errors import.

```python
class WpConfigFile:
    """A site's ``wp-config.php``: a credential source, and where its database lives.

    Needs the ``wpconfig`` extra.
    """

    __slots__ = ("_config", "_missing", "_path")

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        try:
            from l3io.wp.config import MISSING, WpConfigError
            from l3io.wp.config import WpConfigFile as _Upstream
        except ImportError as exc:
            raise MissingDependencyError(
                extra="wpconfig", distribution="l3io-wordpress-config"
            ) from exc
        self._missing = MISSING
        try:
            self._config: Any = _Upstream(filename=self._path)
        except WpConfigError as exc:
            raise ConfigUnreadableError(self._path, str(exc)) from exc

    @property
    def path(self) -> str:
        return self._path

    @property
    def source(self) -> str:
        return f"wp-config:{self._path}"

    @property
    def table_prefix(self) -> str:
        """WordPress's ``$table_prefix``, or ``wp_`` when unset."""
        value = self._config.get_variable("table_prefix")
        return DEFAULT_TABLE_PREFIX if value is self._missing else str(value)

    def resolve(self) -> ResolvedCredentials:
        user, password = self._get("DB_USER"), self._get("DB_PASSWORD")
        if user is None and password is None:
            msg = f"{self._path} defines neither DB_USER nor DB_PASSWORD"
            raise CredentialsAbsentError(msg, sources=(self.source,))
        if user is None:
            raise MissingConfigValueError("DB_USER", self._path)
        if password is None:
            raise MissingConfigValueError("DB_PASSWORD", self._path)
        return ResolvedCredentials(user, password, self.source)

    def connection(self) -> Connection:
        """Where the configured database lives."""
        host, name = self._get("DB_HOST"), self._get("DB_NAME")
        if host is None:
            raise MissingConfigValueError("DB_HOST", self._path)
        if name is None:
            raise MissingConfigValueError("DB_NAME", self._path)
        return Connection.from_db_host(host, name)

    def _get(self, key: str) -> str | None:
        value: Any = self._config.get(key)
        if value is self._missing:
            return None
        return value if isinstance(value, str) else str(value)

    def __repr__(self) -> str:
        return f"WpConfigFile(path={self._path!r})"
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest -q tests/test_wpconfig_file.py tests/test_declared_facts.py && make lint types`
Expected: all pass (`test_declared_facts` verifies the new `MissingDependencyError` names a distribution the `wpconfig` extra installs).

- [ ] **Step 5: Commit**

```bash
git add src/l3io/wp/database/wpconfig.py tests/test_wpconfig_file.py
git commit -m "feat: WpConfigFile credential source and site reader (spec §5)"
```

---

### Task 6: `Connection`

**Files:**
- Modify: `src/l3io/wp/database/connection.py`
- Test: `tests/test_connection_new.py` (merged into `tests/test_connection.py` in Task 13)

**Interfaces:**
- Produces: `Connection(host: str, database: str, port: int = 3306)`, frozen; `Connection.from_db_host(db_host: str, database: str) -> Connection`. Invalid host/port → `InvalidArgumentsError`; invalid database → `InvalidDatabaseNameError`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_connection_new.py
from __future__ import annotations

import pytest

from l3io.wp.database.connection import Connection
from l3io.wp.database.errors import InvalidArgumentsError, InvalidDatabaseNameError


def test_from_db_host_parses_port() -> None:
    assert Connection.from_db_host("db.example:3307", "wp_site") == Connection(
        host="db.example", database="wp_site", port=3307
    )


def test_from_db_host_defaults_port() -> None:
    assert Connection.from_db_host("db", "wp").port == 3306


@pytest.mark.parametrize("db_host", ["", "db:notaport"])
def test_bad_db_host(db_host: str) -> None:
    with pytest.raises(InvalidArgumentsError):
        Connection.from_db_host(db_host, "wp")


@pytest.mark.parametrize("port", [0, 65536])
def test_bad_port(port: int) -> None:
    with pytest.raises(InvalidArgumentsError):
        Connection(host="db", database="wp", port=port)


def test_bad_database_name() -> None:
    with pytest.raises(InvalidDatabaseNameError):
        Connection(host="db", database="wp.site")


def test_carries_no_credentials() -> None:
    assert not hasattr(Connection(host="db", database="wp"), "credentials")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest -q tests/test_connection_new.py`
Expected: FAIL — `ImportError: cannot import name 'Connection'`.

- [ ] **Step 3: Implement** — in `src/l3io/wp/database/connection.py`, add a shared parser and the new class, and make `WpConnection.from_db_host` use the parser:

```python
def _split_db_host(db_host: str) -> tuple[str, int]:
    """Split WordPress's ``DB_HOST`` (``host`` or ``host:port``)."""
    if not db_host:
        msg = "DB_HOST must not be empty"
        raise InvalidArgumentsError(msg)
    host, separator, port_text = db_host.partition(":")
    if separator and port_text:
        try:
            return host, int(port_text)
        except ValueError as exc:
            msg = f"DB_HOST port {port_text!r} is not an integer"
            raise InvalidArgumentsError(msg) from exc
    return host, DEFAULT_PORT


@dataclass(frozen=True, slots=True)
class Connection:
    """Where one WordPress database lives. Carries no credentials."""

    host: str
    database: str
    port: int = DEFAULT_PORT

    def __post_init__(self) -> None:
        if not self.host:
            msg = "host must not be empty"
            raise InvalidArgumentsError(msg)
        if not isinstance(self.port, int) or not (0 < self.port < 65536):
            msg = f"port must be an integer between 1 and 65535, not {self.port!r}"
            raise InvalidArgumentsError(msg)
        validate_database_name(self.database)

    @classmethod
    def from_db_host(cls, db_host: str, database: str) -> Connection:
        """Build from WordPress's ``DB_HOST``, which may carry ``host:port``."""
        host, port = _split_db_host(db_host)
        return cls(host=host, database=database, port=port)
```

Replace the body of `WpConnection.from_db_host` with:

```python
        host, port = _split_db_host(db_host)
        return cls(host=host, database=db_name, credentials=credentials, port=port)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest -q tests/test_connection_new.py tests/test_connection.py && make lint types`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/l3io/wp/database/connection.py tests/test_connection_new.py
git commit -m "feat: credential-free Connection (spec §4)"
```

---

### Task 7: Server detection, privileges and the SQL session helper

**Files:**
- Create: `src/l3io/wp/database/_sql.py`, `src/l3io/wp/database/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `Connection` (Task 6), `ResolvedCredentials` (Task 4), `ConnectionState` (`state.py`, unchanged).
- Produces:
  - `_sql.open_connection(connection: Connection, credentials: ResolvedCredentials, *, database: str | None) -> pymysql.connections.Connection` (`autocommit=False`, `connect_timeout=10`).
  - `_sql.classify(exc: pymysql.err.MySQLError) -> ConnectionState`.
  - `server.ServerFamily` (`MYSQL`, `MARIADB`); `server.ServerInfo(family, version: tuple[int, int, int], version_text: str)` with `.is_supported`, `.is_end_of_life`.
  - `server.parse_version(text: str) -> ServerInfo`; `server.detect_server(cursor) -> ServerInfo`.
  - `server.Privileges(names: frozenset[str], grantable: bool, unverified: bool)` with `.has(name: str) -> bool` (`"GRANT OPTION"` maps to `grantable`).
  - `server.account_privileges(cursor, database: str) -> Privileges` for the session's own account (global ∪ database-level).
  - `server.grantee(user: str, host: str) -> str` returning `"'user'@'host'"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_server.py
from __future__ import annotations

from typing import Any

import pymysql
import pytest

from l3io.wp.database._sql import classify
from l3io.wp.database.server import (
    Privileges,
    ServerFamily,
    account_privileges,
    grantee,
    parse_version,
)
from l3io.wp.database.state import ConnectionState


@pytest.mark.parametrize(
    ("text", "family", "version"),
    [
        ("8.4.11", ServerFamily.MYSQL, (8, 4, 11)),
        ("8.0.46", ServerFamily.MYSQL, (8, 0, 46)),
        ("9.7.2", ServerFamily.MYSQL, (9, 7, 2)),
        ("11.4.5-MariaDB-ubu2404", ServerFamily.MARIADB, (11, 4, 5)),
        ("10.2.44-MariaDB-1:10.2.44+maria~bionic", ServerFamily.MARIADB, (10, 2, 44)),
    ],
)
def test_parse_version(text: str, family: ServerFamily, version: tuple[int, int, int]) -> None:
    info = parse_version(text)
    assert (info.family, info.version, info.version_text) == (family, version, text)


@pytest.mark.parametrize(
    ("text", "supported", "eol"),
    [
        ("5.7.44", False, True),
        ("8.0.46", True, True),
        ("8.4.11", True, False),
        ("10.1.48-MariaDB", False, True),
        ("10.2.44-MariaDB", True, True),
        ("11.4.5-MariaDB", True, False),
    ],
)
def test_support_and_end_of_life(text: str, supported: bool, eol: bool) -> None:
    info = parse_version(text)
    assert (info.is_supported, info.is_end_of_life) == (supported, eol)


def test_unparseable_version_is_rejected() -> None:
    with pytest.raises(ValueError, match="version"):
        parse_version("not-a-version")


@pytest.mark.parametrize(
    ("code", "state"),
    [
        (1045, ConnectionState.AUTHENTICATION_FAILED),
        (1044, ConnectionState.ACCESS_DENIED),
        (1049, ConnectionState.DATABASE_ABSENT),
        (2003, ConnectionState.UNREACHABLE),
    ],
)
def test_classify(code: int, state: ConnectionState) -> None:
    assert classify(pymysql.err.OperationalError(code, "x")) is state


def test_grantee_format() -> None:
    assert grantee("wpuser", "%") == "'wpuser'@'%'"


class _Cursor:
    """A cursor that answers the queries account_privileges issues, in order."""

    def __init__(self, answers: list[Any]) -> None:
        self._answers = answers
        self.executed: list[tuple[str, Any]] = []

    def execute(self, sql: str, args: Any = None) -> None:
        self.executed.append((sql, args))
        self._current = self._answers.pop(0)

    def fetchone(self) -> Any:
        return self._current

    def fetchall(self) -> Any:
        return self._current


def test_account_privileges_merges_global_and_schema() -> None:
    cursor = _Cursor(
        [
            ("admin@%",),  # CURRENT_USER()
            ("NONE",),  # CURRENT_ROLE()
            [("CREATE USER", "YES"), ("SELECT", "YES")],  # USER_PRIVILEGES
            [("DROP", "NO")],  # SCHEMA_PRIVILEGES matching the database
        ]
    )
    privs = account_privileges(cursor, "wp_site")
    assert privs == Privileges(frozenset({"CREATE USER", "SELECT", "DROP"}), True, False)
    assert privs.has("GRANT OPTION")
    assert cursor.executed[2][1] == ("'admin'@'%'",)
    assert cursor.executed[3][1] == ("'admin'@'%'", "wp_site")


def test_role_makes_privileges_unverified() -> None:
    cursor = _Cursor([("admin@%",), ("`r_admin`@`%`",), [], []])
    assert account_privileges(cursor, "wp_site").unverified


def test_mariadb_null_role_is_no_role() -> None:
    cursor = _Cursor([("admin@localhost",), (None,), [], []])
    assert not account_privileges(cursor, "wp_site").unverified
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest -q tests/test_server.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'l3io.wp.database._sql'`.

- [ ] **Step 3: Implement `_sql.py`**

```python
# src/l3io/wp/database/_sql.py
"""Opening a server connection and classifying driver errors. Internal."""

from __future__ import annotations

import pymysql

from .connection import Connection
from .credentials import ResolvedCredentials
from .state import ConnectionState

CONNECT_TIMEOUT_SECONDS = 10

ER_DBACCESS_DENIED = 1044
ER_ACCESS_DENIED = 1045
ER_BAD_DB = 1049
ER_NONEXISTING_GRANT = 1141
ER_TABLEACCESS_DENIED = 1142


def open_connection(
    connection: Connection, credentials: ResolvedCredentials, *, database: str | None
) -> pymysql.connections.Connection:
    """Open a connection. Credentials are call arguments, never a URI."""
    return pymysql.connect(
        host=connection.host,
        port=connection.port,
        user=credentials.username,
        password=credentials.password,
        database=database,
        connect_timeout=CONNECT_TIMEOUT_SECONDS,
        autocommit=False,
    )


def error_code(exc: pymysql.err.MySQLError) -> int | None:
    """The server error number, when the driver reports one."""
    code = exc.args[0] if exc.args else None
    return code if isinstance(code, int) else None


def classify(exc: pymysql.err.MySQLError) -> ConnectionState:
    """Map a connection failure onto a :class:`ConnectionState`."""
    code = error_code(exc)
    if code == ER_ACCESS_DENIED:
        return ConnectionState.AUTHENTICATION_FAILED
    if code == ER_DBACCESS_DENIED:
        return ConnectionState.ACCESS_DENIED
    if code == ER_BAD_DB:
        return ConnectionState.DATABASE_ABSENT
    return ConnectionState.UNREACHABLE
```

- [ ] **Step 4: Implement `server.py`** — the `information_schema` queries are those confirmed in Task 1; if Task 1 recorded a difference, apply it here.

```python
# src/l3io/wp/database/server.py
"""Which server this is, and what the session's own account may do."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

#: Floors: MariaDB 10.1 rejects ALTER USER, which provisioning needs.
_FLOOR = {"mysql": (8, 0, 0), "mariadb": (10, 2, 0)}

#: Upstream end of life, per (family, major, minor) series. Data, not logic:
#: extend it as series retire.
_END_OF_LIFE: frozenset[tuple[str, int, int]] = frozenset(
    {
        ("mysql", 5, 7),
        ("mysql", 8, 0),
        ("mariadb", 10, 1),
        ("mariadb", 10, 2),
        ("mariadb", 10, 3),
        ("mariadb", 10, 4),
        ("mariadb", 10, 5),
    }
)

_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)")


class ServerFamily(StrEnum):
    """The two server families this package supports."""

    MYSQL = "mysql"
    MARIADB = "mariadb"


@dataclass(frozen=True, slots=True)
class ServerInfo:
    """A server's family and version."""

    family: ServerFamily
    version: tuple[int, int, int]
    version_text: str

    @property
    def is_supported(self) -> bool:
        return self.version >= _FLOOR[self.family.value]

    @property
    def is_end_of_life(self) -> bool:
        major, minor, _ = self.version
        return (self.family.value, major, minor) in _END_OF_LIFE or not self.is_supported


def parse_version(text: str) -> ServerInfo:
    """Interpret ``SELECT VERSION()``."""
    match = _VERSION.match(text)
    if match is None:
        msg = f"unrecognised server version {text!r}"
        raise ValueError(msg)
    major, minor, patch = (int(g) for g in match.groups())
    family = ServerFamily.MARIADB if "mariadb" in text.lower() else ServerFamily.MYSQL
    return ServerInfo(family, (major, minor, patch), text)


def detect_server(cursor: Any) -> ServerInfo:
    """Ask the server what it is."""
    cursor.execute("SELECT VERSION()")
    return parse_version(str(cursor.fetchone()[0]))


def grantee(user: str, host: str) -> str:
    """The ``GRANTEE`` form ``information_schema`` uses."""
    return f"'{user}'@'{host}'"


@dataclass(frozen=True, slots=True)
class Privileges:
    """What the session's own account holds on one database."""

    names: frozenset[str]
    grantable: bool
    unverified: bool

    def has(self, name: str) -> bool:
        return self.grantable if name == "GRANT OPTION" else name in self.names


def account_privileges(cursor: Any, database: str) -> Privileges:
    """Global and database-level privileges of the session's own account.

    ``unverified`` is set when a role is active: ``information_schema`` lists
    only directly granted privileges, so a role-held privilege would read as
    missing.
    """
    cursor.execute("SELECT CURRENT_USER()")
    user, _, host = str(cursor.fetchone()[0]).rpartition("@")
    cursor.execute("SELECT CURRENT_ROLE()")
    role = cursor.fetchone()[0]
    unverified = role is not None and str(role).upper() != "NONE"

    who = grantee(user, host)
    cursor.execute(
        "SELECT PRIVILEGE_TYPE, IS_GRANTABLE FROM information_schema.USER_PRIVILEGES "
        "WHERE GRANTEE = %s",
        (who,),
    )
    rows = list(cursor.fetchall())
    cursor.execute(
        "SELECT PRIVILEGE_TYPE, IS_GRANTABLE FROM information_schema.SCHEMA_PRIVILEGES "
        "WHERE GRANTEE = %s AND %s LIKE TABLE_SCHEMA",
        (who, database),
    )
    rows += list(cursor.fetchall())
    names = frozenset(str(r[0]) for r in rows)
    grantable = any(str(r[1]).upper() == "YES" for r in rows)
    return Privileges(names, grantable, unverified)
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest -q tests/test_server.py && make lint types`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/l3io/wp/database/_sql.py src/l3io/wp/database/server.py tests/test_server.py
git commit -m "feat: server detection, privilege reading and SQL session helper"
```

---

### Task 8: Per-operation observability

**Files:**
- Create: `src/l3io/wp/database/_observe.py`
- Modify: `pyproject.toml` (dev group), `uv.lock`
- Test: `tests/test_observability.py`

**Interfaces:**
- Consumes: `Connection` (Task 6), `RefusedError` (Task 3).
- Produces: `_observe.operation(name: str, connection: Connection) -> ContextManager[dict[str, object]]`. Opens span `l3io.wp.database.<name>` (child of the caller's current span) with `db.name`, `server.address`, `server.port`; on exit emits one structlog event `"operation complete"` with `operation`, `outcome` (`succeeded`/`refused`/`failed`), `duration_ms`, `database`, plus anything the caller put in the yielded dict. On `RefusedError`, sets span attribute `l3io.verdict.codes`.

- [ ] **Step 1: Add the SDK as a dev dependency**

Edit `pyproject.toml`'s `[dependency-groups] dev` list, adding after `"packaging==26.3",`:

```toml
  # Span assertions need a real SDK; the package itself depends on the API only.
  "opentelemetry-sdk==1.44.0",
```

Run: `uv lock && uv sync --locked --all-extras --dev`
Expected: lock updates; sync succeeds.

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_observability.py
"""Correlation by contextvars, one span per operation, timing on every completion."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import structlog
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from structlog.testing import LogCapture

from l3io.wp.database._observe import operation
from l3io.wp.database.connection import Connection
from l3io.wp.database.errors import RefusedError
from l3io.wp.database.verdict import Code, Finding, Verdict

CONN = Connection(host="127.0.0.1", database="wp_site", port=1)
_EXPORTER = InMemorySpanExporter()
_PROVIDER = TracerProvider()
_PROVIDER.add_span_processor(SimpleSpanProcessor(_EXPORTER))
trace.set_tracer_provider(_PROVIDER)


@pytest.fixture
def logs() -> Iterator[LogCapture]:
    capture = LogCapture()
    structlog.configure(processors=[structlog.contextvars.merge_contextvars, capture])
    yield capture
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()


@pytest.fixture(autouse=True)
def _spans() -> Iterator[None]:
    _EXPORTER.clear()
    yield


def test_bound_run_id_appears_on_the_completion_event(logs: LogCapture) -> None:
    structlog.contextvars.bind_contextvars(run_id="run-123")
    with operation("survey", CONN):
        pass
    [event] = [e for e in logs.entries if e["event"] == "operation complete"]
    assert event["run_id"] == "run-123"
    assert event["operation"] == "survey"
    assert event["outcome"] == "succeeded"
    assert isinstance(event["duration_ms"], float)


def test_fields_set_inside_the_block_are_reported(logs: LogCapture) -> None:
    with operation("ensure", CONN) as fields:
        fields["created_database"] = True
    assert logs.entries[-1]["created_database"] is True


def test_refusal_is_reported_with_codes(logs: LogCapture) -> None:
    verdict = Verdict("drop_database", (Finding(Code.CONFIRMATION_MISMATCH, "no"),))
    with pytest.raises(RefusedError), operation("drop_database", CONN):
        raise RefusedError(verdict)
    assert logs.entries[-1]["outcome"] == "refused"
    [span] = _EXPORTER.get_finished_spans()
    assert span.attributes is not None
    assert span.attributes["l3io.verdict.codes"] == ("confirmation_mismatch",)


def test_failure_is_reported_and_reraised(logs: LogCapture) -> None:
    with pytest.raises(ZeroDivisionError), operation("ensure", CONN):
        _ = 1 / 0
    assert logs.entries[-1]["outcome"] == "failed"
    [span] = _EXPORTER.get_finished_spans()
    assert span.status.status_code is trace.StatusCode.ERROR


def test_span_nests_under_the_callers_span() -> None:
    tracer = trace.get_tracer("caller")
    with tracer.start_as_current_span("phase"), operation("survey", CONN):
        pass
    spans = {s.name: s for s in _EXPORTER.get_finished_spans()}
    child, parent = spans["l3io.wp.database.survey"], spans["phase"]
    assert child.parent is not None
    assert child.parent.span_id == parent.context.span_id
    assert child.attributes is not None
    assert child.attributes["db.name"] == "wp_site"
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest -q tests/test_observability.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'l3io.wp.database._observe'`.

- [ ] **Step 4: Implement**

```python
# src/l3io/wp/database/_observe.py
"""One span, one timed completion event, per public operation. Internal.

The package never configures logging. A caller that binds a Run ID with
``structlog.contextvars`` sees it here because the caller's processor chain
merges it, not because this module does anything.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

import structlog
from opentelemetry import trace

from .connection import Connection
from .errors import RefusedError

_log = structlog.get_logger("l3io.wp.database")
_tracer = trace.get_tracer("l3io.wp.database")


@contextmanager
def operation(name: str, connection: Connection) -> Iterator[dict[str, object]]:
    """Wrap one public operation in a span and a completion event."""
    fields: dict[str, object] = {}
    started = time.monotonic()
    with _tracer.start_as_current_span(f"l3io.wp.database.{name}") as span:
        span.set_attribute("db.name", connection.database)
        span.set_attribute("server.address", connection.host)
        span.set_attribute("server.port", connection.port)
        try:
            yield fields
        except RefusedError as exc:
            span.set_attribute("l3io.verdict.codes", [str(f.code) for f in exc.verdict.blockers])
            _complete(name, connection, "refused", started, fields)
            raise
        except BaseException:
            _complete(name, connection, "failed", started, fields)
            raise
        _complete(name, connection, "succeeded", started, fields)


def _complete(
    name: str, connection: Connection, outcome: str, started: float, fields: dict[str, object]
) -> None:
    _log.info(
        "operation complete",
        operation=name,
        outcome=outcome,
        duration_ms=round((time.monotonic() - started) * 1000, 1),
        database=connection.database,
        **fields,
    )
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest -q tests/test_observability.py && make lint types`
Expected: all pass. If ruff flags `except BaseException` (BLE001), it is re-raised; ruff exempts re-raising handlers — if this ruff version does not, add `# noqa: BLE001 - re-raised after reporting`.

- [ ] **Step 6: Commit**

```bash
git add src/l3io/wp/database/_observe.py tests/test_observability.py pyproject.toml uv.lock
git commit -m "feat: per-operation span, timing and completion event (spec §8)"
```

---

### Task 9: Inspection — `survey`, `inspect`, `schema_version`

**Files:**
- Create: `src/l3io/wp/database/inspection.py`
- Modify: `src/l3io/wp/database/versions.py` (rename `WpDatabaseVersion` → `SchemaVersion`, keep alias)
- Modify: `tests/test_integration.py` (add new tests; old ones stay until Task 13)
- Test: `tests/test_inspection.py` (unit), `tests/test_integration.py` (server)

**Interfaces:**
- Consumes: `operation` (Task 8), `open_connection`, `classify`, `error_code`, `ER_TABLEACCESS_DENIED` (Task 7), `detect_server`, `grantee`, `ServerInfo` (Task 7), `CredentialSource` (Task 4), `quote_identifier`, `validate_user_name`.
- Produces:
  - `Survey(server: ServerInfo, database_exists: bool, table_count: int, size_bytes: int, is_wordpress: bool, schema_version: SchemaVersion | None, user_exists: bool | None, user_privileges: frozenset[str] | None)`.
  - `survey(connection, admin, *, wordpress_user: str | None = None, user_host: str = "%", table_prefix: str = "wp_") -> Survey`. Raises `CredentialsUnobtainableError`/`CredentialsAbsentError`, `DatabaseUnreachableError`, `AuthenticationFailedError`.
  - `inspect(connection, credentials) -> ConnectionState` (never raises for ordinary failure).
  - `schema_version(connection, credentials, table_prefix: str = "wp_") -> SchemaVersion | None`.
  - Internal helpers `_resolve(source) -> ResolvedCredentials` and `_admin_session(connection, admin) -> pymysql Connection` (raising `DatabaseUnreachableError`/`AuthenticationFailedError`), used by the read operations only. Task 10 has its own preflight, because a mutating operation reports these conditions as `Verdict` findings rather than exceptions.

- [ ] **Step 1: Rename the version class** — in `src/l3io/wp/database/versions.py`, rename `class WpDatabaseVersion` to `class SchemaVersion` and append:

```python
#: Removed in Task 13 of plan 1.
WpDatabaseVersion = SchemaVersion
```

Run: `make check` — Expected: pass.

- [ ] **Step 2: Write the failing unit tests**

```python
# tests/test_inspection.py
from __future__ import annotations

from l3io.wp.database.connection import Connection
from l3io.wp.database.credentials import Explicit
from l3io.wp.database.inspection import inspect
from l3io.wp.database.state import ConnectionState


def test_unreachable_server_is_a_state_not_an_exception() -> None:
    state = inspect(Connection(host="127.0.0.1", database="wp", port=1), Explicit("u", "p"))
    assert state is ConnectionState.UNREACHABLE


class _Unobtainable:
    source = "broken"

    def resolve(self):  # type: ignore[no-untyped-def]
        from l3io.wp.database.errors import CredentialsUnobtainableError

        raise CredentialsUnobtainableError("nope")


def test_unobtainable_credentials_are_a_state() -> None:
    state = inspect(Connection(host="127.0.0.1", database="wp", port=1), _Unobtainable())
    assert state is ConnectionState.CREDENTIALS_UNOBTAINABLE
```

- [ ] **Step 3: Write the failing integration tests** — append to `tests/test_integration.py`:

```python
# --- new API (plan 1, task 9) ---------------------------------------------------
from l3io.wp.database.connection import Connection
from l3io.wp.database.credentials import Explicit
from l3io.wp.database.inspection import schema_version, survey
from l3io.wp.database.server import ServerFamily


def new_admin() -> Explicit:
    return Explicit(ADMIN_USER, ADMIN_PASSWORD)


def test_survey_of_an_absent_database(suffix: str) -> None:
    result = survey(Connection(host=HOST, port=PORT, database=f"wp_{suffix}"), new_admin())
    assert result.database_exists is False
    assert result.table_count == 0
    assert result.is_wordpress is False
    assert result.server.family in (ServerFamily.MYSQL, ServerFamily.MARIADB)


def test_survey_of_a_wordpress_database(suffix: str) -> None:
    name = f"wp_{suffix}"
    admin_sql(
        f"CREATE DATABASE `{name}`",
        f"CREATE TABLE `{name}`.`xy_options` (option_name VARCHAR(191), option_value LONGTEXT)",
        f"INSERT INTO `{name}`.`xy_options` VALUES ('db_version', '58975')",
        f"CREATE USER 'u_{suffix}'@'%' IDENTIFIED BY 'p'",
        f"GRANT SELECT ON `{name}`.* TO 'u_{suffix}'@'%'",
    )
    result = survey(
        Connection(host=HOST, port=PORT, database=name),
        new_admin(),
        wordpress_user=f"u_{suffix}",
        table_prefix="xy_",
    )
    assert result.database_exists and result.table_count == 1 and result.is_wordpress
    assert result.schema_version is not None and result.schema_version.release == "6.7"
    assert result.user_exists is True
    assert result.user_privileges == frozenset({"SELECT"})


def test_schema_version_with_custom_prefix_via_new_api(suffix: str) -> None:
    name = f"wp_{suffix}"
    admin_sql(
        f"CREATE DATABASE `{name}`",
        f"CREATE TABLE `{name}`.`xy_options` (option_name VARCHAR(191), option_value LONGTEXT)",
        f"INSERT INTO `{name}`.`xy_options` VALUES ('db_version', '58975')",
    )
    version = schema_version(Connection(host=HOST, port=PORT, database=name), new_admin(), "xy_")
    assert version is not None and version.release == "6.7"
```

- [ ] **Step 4: Run to verify failure**

Run: `uv run pytest -q tests/test_inspection.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'l3io.wp.database.inspection'`.

- [ ] **Step 5: Implement**

```python
# src/l3io/wp/database/inspection.py
"""Read-only questions about a database, answered by the right account.

:func:`survey` runs as the administrator and is the authority on what exists
(AD-29). :func:`inspect` is the WordPress account's own login probe: it
describes the account, never whether the database exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pymysql

from ._observe import operation
from ._sql import ER_TABLEACCESS_DENIED, classify, error_code, open_connection
from .connection import Connection
from .credentials import CredentialSource, ResolvedCredentials
from .errors import (
    AccessDeniedError,
    AuthenticationFailedError,
    CredentialsAbsentError,
    CredentialsUnobtainableError,
    DatabaseUnreachableError,
)
from .identifiers import quote_identifier, validate_user_name
from .server import ServerInfo, detect_server, grantee
from .state import ConnectionState
from .versions import SchemaVersion


@dataclass(frozen=True, slots=True)
class Survey:
    """What the administrator can see about one database."""

    server: ServerInfo
    database_exists: bool
    table_count: int
    size_bytes: int
    is_wordpress: bool
    schema_version: SchemaVersion | None
    user_exists: bool | None
    user_privileges: frozenset[str] | None


def _resolve(source: CredentialSource) -> ResolvedCredentials:
    return source.resolve()


def _admin_session(connection: Connection, admin: ResolvedCredentials) -> Any:
    """An admin connection with no default database, or a package error."""
    try:
        return open_connection(connection, admin, database=None)
    except pymysql.err.MySQLError as exc:
        if classify(exc) is ConnectionState.AUTHENTICATION_FAILED:
            msg = f"the administrator account {admin.username!r} was rejected"
            raise AuthenticationFailedError(msg) from exc
        msg = f"{connection.host}:{connection.port} could not be reached"
        raise DatabaseUnreachableError(msg) from exc


def _read_schema_version(cursor: Any, database: str, table_prefix: str) -> SchemaVersion | None:
    table = f"{quote_identifier(database)}.{quote_identifier(table_prefix + 'options')}"
    cursor.execute(
        f"SELECT option_value FROM {table} WHERE option_name = %s",  # noqa: S608 - quoted identifiers
        ("db_version",),
    )
    row = cursor.fetchone()
    if row is None or row[0] is None:
        return None
    try:
        return SchemaVersion(int(row[0]))
    except (TypeError, ValueError) as exc:
        msg = f"db_version {row[0]!r} in {table} is not an integer"
        raise AccessDeniedError(msg) from exc


def survey(
    connection: Connection,
    admin: CredentialSource,
    *,
    wordpress_user: str | None = None,
    user_host: str = "%",
    table_prefix: str = "wp_",
) -> Survey:
    """Everything the administrator can see about this database and account."""
    with operation("survey", connection) as fields:
        session = _admin_session(connection, _resolve(admin))
        database = connection.database
        with session, session.cursor() as cur:
            server = detect_server(cur)
            cur.execute(
                "SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s",
                (database,),
            )
            exists = int(cur.fetchone()[0]) > 0
            cur.execute(
                "SELECT COUNT(*), COALESCE(SUM(DATA_LENGTH + INDEX_LENGTH), 0) "
                "FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s",
                (database,),
            )
            table_count, size_bytes = (int(v) for v in cur.fetchone())
            cur.execute(
                "SELECT COUNT(*) FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
                (database, f"{table_prefix}options"),
            )
            is_wordpress = int(cur.fetchone()[0]) > 0
            version = _read_schema_version(cur, database, table_prefix) if is_wordpress else None

            user_exists: bool | None = None
            user_privileges: frozenset[str] | None = None
            if wordpress_user is not None:
                validate_user_name(wordpress_user)
                try:
                    cur.execute(
                        "SELECT COUNT(*) FROM mysql.user WHERE User = %s AND Host = %s",
                        (wordpress_user, user_host),
                    )
                    user_exists = int(cur.fetchone()[0]) > 0
                except pymysql.err.MySQLError as exc:
                    if error_code(exc) != ER_TABLEACCESS_DENIED:
                        raise
                cur.execute(
                    "SELECT PRIVILEGE_TYPE FROM information_schema.SCHEMA_PRIVILEGES "
                    "WHERE GRANTEE = %s AND %s LIKE TABLE_SCHEMA",
                    (grantee(wordpress_user, user_host), database),
                )
                user_privileges = frozenset(str(r[0]) for r in cur.fetchall())
        fields.update(database_exists=exists, table_count=table_count, is_wordpress=is_wordpress)
        return Survey(
            server, exists, table_count, size_bytes, is_wordpress, version,
            user_exists, user_privileges,
        )


def inspect(connection: Connection, credentials: CredentialSource) -> ConnectionState:
    """Whether this account can use this database, and if not, why."""
    with operation("inspect", connection) as fields:
        try:
            resolved = _resolve(credentials)
        except (CredentialsUnobtainableError, CredentialsAbsentError):
            fields["state"] = str(ConnectionState.CREDENTIALS_UNOBTAINABLE)
            return ConnectionState.CREDENTIALS_UNOBTAINABLE
        try:
            session = open_connection(connection, resolved, database=connection.database)
        except pymysql.err.MySQLError as exc:
            state = classify(exc)
        else:
            session.close()
            state = ConnectionState.READY
        fields["state"] = str(state)
        return state


def schema_version(
    connection: Connection, credentials: CredentialSource, table_prefix: str = "wp_"
) -> SchemaVersion | None:
    """The WordPress schema revision recorded in the options table."""
    with operation("schema_version", connection):
        resolved = _resolve(credentials)
        try:
            session = open_connection(connection, resolved, database=connection.database)
        except pymysql.err.MySQLError as exc:
            msg = f"could not connect to read {table_prefix}options"
            raise DatabaseUnreachableError(msg) from exc
        try:
            with session, session.cursor() as cur:
                return _read_schema_version(cur, connection.database, table_prefix)
        except pymysql.err.MySQLError as exc:
            msg = f"could not read {table_prefix}options; is the table prefix correct?"
            raise AccessDeniedError(msg) from exc
```

- [ ] **Step 6: Run unit and integration tests**

Run: `uv run pytest -q tests/test_inspection.py && make lint types`
Then start a server and run the integration tests:
```bash
docker run -d --rm --name l3io-it -e MYSQL_ROOT_PASSWORD=root -p 127.0.0.1:33306:3306 mysql:8.4
until docker exec l3io-it mysqladmin ping -uroot -proot --silent; do sleep 2; done
make test-db DB_HOST=127.0.0.1 DB_PORT=33306 DB_ADMIN_USER=root DB_ADMIN_PASSWORD=root
```
Expected: all pass. Keep the container for Tasks 10–13; repeat against `mariadb:11.4` (env `MARIADB_ROOT_PASSWORD=root`) before Task 13.

- [ ] **Step 7: Commit**

```bash
git add src/l3io/wp/database/inspection.py src/l3io/wp/database/versions.py tests/test_inspection.py tests/test_integration.py
git commit -m "feat: survey as administrator, inspect and schema_version (spec §7.1)"
```

---

### Task 10: `ensure` — facts, plan, execution

**Files:**
- Create: `src/l3io/wp/database/provision.py`
- Modify: `src/l3io/wp/database/identifiers.py` (add `grant_pattern`, `validate_charset`)
- Test: `tests/test_provision_plan.py` (unit), `tests/test_integration.py` (server)

**Interfaces:**
- Consumes: Tasks 2–9 (`Verdict`, `Finding`, `Code`, `RefusedError`, `ProvisioningError`, `operation`, `open_connection`, `classify`, `detect_server`, `account_privileges`, `grantee`, `_resolve`, `inspect`).
- Produces:
  - `identifiers.grant_pattern(name: str) -> str` — the escaped, *unquoted* LIKE pattern; `quote_grant_database(name) == quote_identifier(grant_pattern(name))`.
  - `identifiers.validate_charset(value: str, kind: str) -> str` — `^[A-Za-z0-9_]+$`, else `InvalidArgumentsError`.
  - `provision.EnsureFacts(database_exists: bool, user_exists: bool, password_works: bool, grant_present: bool)`.
  - `provision.plan_ensure(facts: EnsureFacts) -> tuple[str, ...]` — ordered subset of `("create_database", "create_user", "set_password", "grant")`.
  - `provision.EnsureResult(created_database: bool, created_user: bool, password_set: bool, granted: bool, verdict: Verdict)` with `.changed`.
  - `provision.check_ensure(connection, admin, wordpress, *, user_host="%") -> Verdict`.
  - `provision.ensure(connection, admin, wordpress, *, user_host="%", charset="utf8mb4", collation="utf8mb4_unicode_ci") -> EnsureResult`.
  - `provision._preflight(connection, admin, operation_name, required: tuple[str, ...]) -> tuple[Verdict, Any | None]` — shared by Task 11. Returns the verdict and, when it is ok, an open admin session the caller must close.
  - `provision.WORDPRESS_PRIVILEGES: frozenset[str]` — `SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, ALTER, INDEX`.

- [ ] **Step 1: Write the failing unit tests**

```python
# tests/test_provision_plan.py
"""ensure's planner is pure, so idempotence is provable without a server."""

from __future__ import annotations

import pytest

from l3io.wp.database.errors import InvalidArgumentsError
from l3io.wp.database.identifiers import (
    grant_pattern,
    quote_grant_database,
    quote_identifier,
    validate_charset,
)
from l3io.wp.database.provision import EnsureFacts, plan_ensure
from l3io.wp.database.server import Privileges
from l3io.wp.database.verdict import Code
from l3io.wp.database import provision


def test_plan_for_converged_site_is_empty() -> None:
    assert plan_ensure(EnsureFacts(True, True, True, True)) == ()


def test_plan_for_fresh_site() -> None:
    assert plan_ensure(EnsureFacts(False, False, False, False)) == (
        "create_database",
        "create_user",
        "grant",
    )


def test_existing_user_with_wrong_password_gets_set_password() -> None:
    assert plan_ensure(EnsureFacts(True, True, False, True)) == ("set_password",)


def test_new_user_never_also_gets_set_password() -> None:
    assert "set_password" not in plan_ensure(EnsureFacts(True, False, False, True))


@pytest.mark.parametrize("name", ["wp_site", "wp%site", "plain"])
def test_grant_pattern_is_the_unquoted_form(name: str) -> None:
    assert quote_grant_database(name) == quote_identifier(grant_pattern(name))


def test_grant_pattern_escapes_wildcards() -> None:
    assert grant_pattern("wp_a%b") == r"wp\_a\%b"


@pytest.mark.parametrize("value", ["utf8mb4", "utf8mb4_unicode_ci"])
def test_charset_accepted(value: str) -> None:
    assert validate_charset(value, "charset") == value


@pytest.mark.parametrize("value", ["utf8mb4; DROP DATABASE x", "", "utf8 mb4"])
def test_charset_rejected(value: str) -> None:
    with pytest.raises(InvalidArgumentsError):
        validate_charset(value, "charset")


def test_privilege_findings_for_ensure() -> None:
    privs = Privileges(frozenset({"CREATE"}), grantable=False, unverified=False)
    codes = provision._privilege_findings(privs, ("CREATE", "CREATE USER", "SELECT", "GRANT OPTION"))
    assert [f.fields["privilege"] for f in codes] == ["CREATE USER", "SELECT", "GRANT OPTION"]
    assert all(f.code is Code.MISSING_PRIVILEGE for f in codes)


def test_missing_select_is_a_blocker() -> None:
    privs = Privileges(frozenset({"CREATE", "CREATE USER"}), grantable=True, unverified=False)
    [finding] = provision._privilege_findings(privs, provision.ENSURE_PRIVILEGES)
    assert finding.fields["privilege"] == "SELECT"


def test_role_turns_blockers_into_one_warning() -> None:
    privs = Privileges(frozenset(), grantable=False, unverified=True)
    [finding] = provision._privilege_findings(privs, provision.ENSURE_PRIVILEGES)
    assert finding.code is Code.PRIVILEGES_UNVERIFIED
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest -q tests/test_provision_plan.py`
Expected: FAIL — `ImportError: cannot import name 'grant_pattern'`.

- [ ] **Step 3: Implement the identifier helpers** — in `src/l3io/wp/database/identifiers.py`, add `import re` and `from .errors import InvalidArgumentsError` (extend the existing import), and replace `quote_grant_database`:

```python
def grant_pattern(name: str) -> str:
    """The database name as the ``LIKE`` pattern a GRANT stores, unquoted.

    ``information_schema.SCHEMA_PRIVILEGES.TABLE_SCHEMA`` holds this form, so
    comparing against it finds exactly the grant :func:`quote_grant_database`
    wrote.
    """
    return name.replace("\\", "\\\\").replace("_", r"\_").replace("%", r"\%")


def quote_grant_database(name: str) -> str:
    """Quote a database name for the ``ON <db>.*`` clause of a GRANT.

    The clause is matched as a ``LIKE`` pattern, so ``_`` and ``%`` must be
    escaped or the grant silently widens to every database matching it.
    """
    return quote_identifier(grant_pattern(name))


_CHARSET = re.compile(r"^[A-Za-z0-9_]+$")


def validate_charset(value: str, kind: str) -> str:
    """Return a character set or collation name, or raise.

    These cannot be parameterised, so they are restricted to the characters
    every real name uses.
    """
    if not isinstance(value, str) or not _CHARSET.match(value):
        msg = f"{kind} {value!r} is not a valid name"
        raise InvalidArgumentsError(msg)
    return value
```

- [ ] **Step 4: Implement `provision.py` (ensure part)**

```python
# src/l3io/wp/database/provision.py
"""Provisioning operations, each checked before it runs.

Every operation's preflight produces a :class:`Verdict`. ``check_X`` returns it;
``X`` raises :class:`RefusedError` with it on a blocker, so the check is never
skipped and never differs from the run. ``ensure`` queries facts, plans with a
pure function, and executes only what the plan names, so a converged server
sees no writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pymysql

from ._observe import operation
from ._sql import classify, open_connection
from .connection import Connection
from .credentials import CredentialSource, Explicit, ResolvedCredentials
from .errors import (
    CredentialsAbsentError,
    CredentialsUnobtainableError,
    ProvisioningError,
    RefusedError,
)
from .identifiers import (
    grant_pattern,
    quote_grant_database,
    quote_identifier,
    validate_charset,
    validate_user_name,
)
from .inspection import inspect
from .server import Privileges, account_privileges, detect_server, grantee
from .state import ConnectionState
from .verdict import Code, Finding, Verdict

WORDPRESS_PRIVILEGES = frozenset(
    {"SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER", "INDEX"}
)
ENSURE_PRIVILEGES = ("CREATE", "CREATE USER", "SELECT", "GRANT OPTION")


@dataclass(frozen=True, slots=True)
class EnsureFacts:
    """What already exists, as the administrator sees it."""

    database_exists: bool
    user_exists: bool
    password_works: bool
    grant_present: bool


@dataclass(frozen=True, slots=True)
class EnsureResult:
    """What :func:`ensure` changed. Each flag is true only if it changed something."""

    created_database: bool
    created_user: bool
    password_set: bool
    granted: bool
    verdict: Verdict

    @property
    def changed(self) -> bool:
        return self.created_database or self.created_user or self.password_set or self.granted


def plan_ensure(facts: EnsureFacts) -> tuple[str, ...]:
    """The steps that converge the server on the desired state, in order."""
    steps: list[str] = []
    if not facts.database_exists:
        steps.append("create_database")
    if not facts.user_exists:
        steps.append("create_user")
    elif not facts.password_works:
        steps.append("set_password")
    if not facts.grant_present:
        steps.append("grant")
    return tuple(steps)


def _privilege_findings(privileges: Privileges, required: tuple[str, ...]) -> list[Finding]:
    if privileges.unverified:
        return [
            Finding(
                Code.PRIVILEGES_UNVERIFIED,
                "the administrator has an active role; its privileges cannot be "
                "checked in advance, so the operation will be attempted",
            )
        ]
    return [
        Finding(
            Code.MISSING_PRIVILEGE,
            f"the administrator lacks {name}",
            {"privilege": name},
        )
        for name in required
        if not privileges.has(name)
    ]


def _preflight(
    connection: Connection,
    admin: CredentialSource,
    operation_name: str,
    required: tuple[str, ...],
) -> tuple[Verdict, Any | None]:
    """Connect as the administrator and check server and privileges.

    Returns the verdict and, only when it holds no blocker, the open session.
    """
    verdict = Verdict(operation_name)
    try:
        resolved = admin.resolve()
    except (CredentialsUnobtainableError, CredentialsAbsentError) as exc:
        return verdict.with_findings(Finding(Code.CREDENTIALS_UNOBTAINABLE, str(exc))), None
    try:
        session = open_connection(connection, resolved, database=None)
    except pymysql.err.MySQLError as exc:
        if classify(exc) is ConnectionState.AUTHENTICATION_FAILED:
            finding = Finding(
                Code.AUTHENTICATION_FAILED,
                f"the administrator account {resolved.username!r} was rejected",
            )
        else:
            finding = Finding(
                Code.UNREACHABLE,
                f"{connection.host}:{connection.port} could not be reached",
                {"host": connection.host, "port": connection.port},
            )
        return verdict.with_findings(finding), None

    with session.cursor() as cur:
        server = detect_server(cur)
        findings: list[Finding] = []
        if not server.is_supported:
            findings.append(
                Finding(
                    Code.SERVER_UNSUPPORTED,
                    f"{server.family} {server.version_text} is below the supported floor",
                    {"version": server.version_text},
                )
            )
        elif server.is_end_of_life:
            findings.append(
                Finding(
                    Code.END_OF_LIFE_SERVER,
                    f"{server.family} {server.version_text} is past upstream end of life",
                    {"version": server.version_text},
                )
            )
        findings += _privilege_findings(account_privileges(cur, connection.database), required)
    verdict = verdict.with_findings(*findings)
    if not verdict.ok:
        session.close()
        return verdict, None
    return verdict, session


def _ensure_facts(
    cur: Any, connection: Connection, wordpress: ResolvedCredentials, user_host: str
) -> EnsureFacts:
    database = connection.database
    cur.execute(
        "SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s", (database,)
    )
    database_exists = int(cur.fetchone()[0]) > 0
    cur.execute(
        "SELECT COUNT(*) FROM mysql.user WHERE User = %s AND Host = %s",
        (wordpress.username, user_host),
    )
    user_exists = int(cur.fetchone()[0]) > 0
    password_works = False
    if user_exists:
        try:
            open_connection(connection, wordpress, database=None).close()
            password_works = True
        except pymysql.err.MySQLError as exc:
            if classify(exc) is not ConnectionState.AUTHENTICATION_FAILED:
                msg = f"could not test {wordpress.username!r}'s password"
                raise ProvisioningError(msg) from exc
    cur.execute(
        "SELECT PRIVILEGE_TYPE FROM information_schema.SCHEMA_PRIVILEGES "
        "WHERE GRANTEE = %s AND TABLE_SCHEMA = %s",
        (grantee(wordpress.username, user_host), grant_pattern(database)),
    )
    held = frozenset(str(r[0]) for r in cur.fetchall())
    return EnsureFacts(database_exists, user_exists, password_works, WORDPRESS_PRIVILEGES <= held)


def check_ensure(
    connection: Connection,
    admin: CredentialSource,
    wordpress: CredentialSource,
    *,
    user_host: str = "%",
) -> Verdict:
    """What :func:`ensure` would find, without changing anything."""
    with operation("check_ensure", connection):
        verdict, session = _preflight(connection, admin, "ensure", ENSURE_PRIVILEGES)
        if session is not None:
            session.close()
        try:
            validate_user_name(wordpress.resolve().username)
        except (CredentialsUnobtainableError, CredentialsAbsentError) as exc:
            verdict = verdict.with_findings(Finding(Code.CREDENTIALS_UNOBTAINABLE, str(exc)))
        return verdict


def ensure(
    connection: Connection,
    admin: CredentialSource,
    wordpress: CredentialSource,
    *,
    user_host: str = "%",
    charset: str = "utf8mb4",
    collation: str = "utf8mb4_unicode_ci",
) -> EnsureResult:
    """Converge the server on: database exists, account exists with this password,
    account holds ALL on this database only.

    Raises:
        RefusedError: the check found a blocker; nothing ran.
        ProvisioningError: a statement failed, or the account still cannot use
            the database afterwards; ``completed`` lists the steps that ran.
    """
    validate_charset(charset, "charset")
    validate_charset(collation, "collation")
    with operation("ensure", connection) as fields:
        verdict, session = _preflight(connection, admin, "ensure", ENSURE_PRIVILEGES)
        try:
            wp = wordpress.resolve()
        except (CredentialsUnobtainableError, CredentialsAbsentError) as exc:
            if session is not None:
                session.close()
            verdict = verdict.with_findings(Finding(Code.CREDENTIALS_UNOBTAINABLE, str(exc)))
            raise RefusedError(verdict) from exc
        if session is None:
            raise RefusedError(verdict)
        username = validate_user_name(wp.username)
        database = connection.database
        statements = {
            "create_database": (
                f"CREATE DATABASE {quote_identifier(database)} "
                f"CHARACTER SET {charset} COLLATE {collation}",
                None,
            ),
            "create_user": ("CREATE USER %s@%s IDENTIFIED BY %s", (username, user_host, wp.password)),
            "set_password": ("ALTER USER %s@%s IDENTIFIED BY %s", (username, user_host, wp.password)),
            "grant": (
                f"GRANT ALL PRIVILEGES ON {quote_grant_database(database)}.* TO %s@%s",
                (username, user_host),
            ),
        }
        completed: list[str] = []
        with session, session.cursor() as cur:
            steps = plan_ensure(_ensure_facts(cur, connection, wp, user_host))
            try:
                for step in steps:
                    sql, args = statements[step]
                    cur.execute(sql, args)
                    completed.append(step)
                session.commit()
            except pymysql.err.MySQLError as exc:
                msg = f"ensuring {database!r} failed after {len(completed)} step(s)"
                raise ProvisioningError(msg, completed=tuple(completed)) from exc

        final = inspect(connection, Explicit(wp.username, wp.password))
        if not final.is_ready:
            msg = f"ensure ran but {database!r} is still not usable by {username!r}: {final}"
            raise ProvisioningError(msg, completed=tuple(completed))

        result = EnsureResult(
            created_database="create_database" in completed,
            created_user="create_user" in completed,
            password_set="create_user" in completed or "set_password" in completed,
            granted="grant" in completed,
            verdict=verdict,
        )
        fields.update(
            created_database=result.created_database,
            created_user=result.created_user,
            password_set=result.password_set,
            granted=result.granted,
        )
        return result
```

- [ ] **Step 5: Run unit tests**

Run: `uv run pytest -q tests/test_provision_plan.py tests/test_identifiers.py && make lint types`
Expected: all pass. (`test_identifiers.py`'s existing escaping tests still pass because `quote_grant_database`'s output is unchanged.)

- [ ] **Step 6: Write the failing integration tests** — append to `tests/test_integration.py`:

```python
from l3io.wp.database.errors import RefusedError
from l3io.wp.database.provision import check_ensure, ensure
from l3io.wp.database.verdict import Code


def new_site(suffix: str) -> Connection:
    return Connection(host=HOST, port=PORT, database=f"wp_{suffix}")


def test_ensure_fresh_site_reports_what_it_created(suffix: str) -> None:
    result = ensure(new_site(suffix), new_admin(), Explicit(f"u_{suffix}", "wp-pass"))
    assert (result.created_database, result.created_user, result.password_set, result.granted) == (
        True, True, True, True,
    )


def test_second_ensure_changes_nothing_with_underscore_name(suffix: str) -> None:
    wp = Explicit(f"u_{suffix}", "wp-pass")
    ensure(new_site(suffix), new_admin(), wp)
    again = ensure(new_site(suffix), new_admin(), wp)
    assert not again.changed


def test_existing_database_without_user_is_not_reported_as_created(suffix: str) -> None:
    admin_sql(f"CREATE DATABASE `wp_{suffix}`")
    result = ensure(new_site(suffix), new_admin(), Explicit(f"u_{suffix}", "wp-pass"))
    assert result.created_database is False
    assert result.created_user is True


def test_wrong_password_is_reset_and_reported(suffix: str) -> None:
    ensure(new_site(suffix), new_admin(), Explicit(f"u_{suffix}", "first"))
    result = ensure(new_site(suffix), new_admin(), Explicit(f"u_{suffix}", "second"))
    assert (result.created_user, result.password_set, result.granted) == (False, True, False)


@pytest.mark.parametrize("password", ["q'uo\"te", "back\\slash", "hash#semi;", "ab);cd", " spaced "])
def test_awkward_password_round_trips(suffix: str, password: str) -> None:
    ensure(new_site(suffix), new_admin(), Explicit(f"u_{suffix}", password))
    conn = pymysql.connect(host=HOST, port=PORT, user=f"u_{suffix}", password=password, database=f"wp_{suffix}")
    conn.close()


def test_grant_does_not_reach_a_name_matching_the_unescaped_pattern(suffix: str) -> None:
    admin_sql(f"CREATE DATABASE `wpX{suffix}`")
    ensure(new_site(suffix), new_admin(), Explicit(f"u_{suffix}", "wp-pass"))
    conn = pymysql.connect(host=HOST, port=PORT, user=f"u_{suffix}", password="wp-pass")
    with conn, conn.cursor() as cur:
        cur.execute("SHOW DATABASES")
        visible = {r[0] for r in cur.fetchall()}
    assert f"wp_{suffix}" in visible
    assert f"wpX{suffix}" not in visible


def test_wrong_admin_password_is_a_coded_refusal(suffix: str) -> None:
    verdict = check_ensure(new_site(suffix), Explicit(ADMIN_USER, "wrong"), Explicit("u", "p"))
    assert verdict.codes == frozenset({Code.AUTHENTICATION_FAILED})
    with pytest.raises(RefusedError) as info:
        ensure(new_site(suffix), Explicit(ADMIN_USER, "wrong"), Explicit("u", "p"))
    assert info.value.verdict == verdict


def test_check_and_run_agree_on_unreachable() -> None:
    conn = Connection(host="127.0.0.1", port=1, database="wp_x")
    verdict = check_ensure(conn, new_admin(), Explicit("u", "p"))
    assert Code.UNREACHABLE in verdict.codes
```

Note: `test_wrong_admin_password_is_a_coded_refusal` and `test_check_and_run_agree_on_unreachable` compare whole verdicts; both functions produce the same findings because both call `_preflight`.

- [ ] **Step 7: Run integration tests**

Run: `make test-db DB_HOST=127.0.0.1 DB_PORT=33306 DB_ADMIN_USER=root DB_ADMIN_PASSWORD=root`
Expected: all pass.

- [ ] **Step 8: Run against MariaDB 11.4 too**

```bash
docker run -d --rm --name l3io-it-ma -e MARIADB_ROOT_PASSWORD=root -p 127.0.0.1:33307:3306 mariadb:11.4
until docker exec l3io-it-ma healthcheck.sh --connect --innodb_initialized; do sleep 2; done
make test-db DB_HOST=127.0.0.1 DB_PORT=33307 DB_ADMIN_USER=root DB_ADMIN_PASSWORD=root
```
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add src/l3io/wp/database/provision.py src/l3io/wp/database/identifiers.py tests/test_provision_plan.py tests/test_integration.py
git commit -m "feat: ensure with honest created/set/granted flags and a shared preflight (spec §7.2)"
```

---

### Task 11: `rotate_password`, `revoke`, `drop_user`, `drop_database`

**Files:**
- Modify: `src/l3io/wp/database/provision.py`
- Test: `tests/test_provision_guards.py` (unit), `tests/test_integration.py` (server)

**Interfaces:**
- Consumes: `_preflight`, `_privilege_findings` (Task 10); `ER_NONEXISTING_GRANT` (Task 7).
- Produces:
  - `OperationResult(changed: bool, verdict: Verdict)`.
  - `check_rotate_password(connection, admin, wordpress, *, user_host="%") -> Verdict`; `rotate_password(...) -> OperationResult`. Blocker `USER_ABSENT`. Needs `CREATE USER`, `SELECT`.
  - `check_revoke(connection, admin, user: str, *, user_host="%", confirm: str) -> Verdict`; `revoke(...) -> OperationResult`. Blockers `CONFIRMATION_MISMATCH` (confirm ≠ user), `USER_ABSENT`. Needs `SELECT`, `GRANT OPTION`. No grant present → `changed=False`.
  - `check_drop_user(connection, admin, user: str, *, user_host="%", confirm: str) -> Verdict`; `drop_user(...) -> OperationResult`. Blocker `CONFIRMATION_MISMATCH`. Needs `CREATE USER`, `SELECT`. Absent → `changed=False`.
  - `check_drop_database(connection, admin, *, confirm: str) -> Verdict`; `drop_database(...) -> OperationResult`. Blocker `CONFIRMATION_MISMATCH` (confirm ≠ `connection.database`); warning `LIVE_WORDPRESS_SITE` when a table named `%options` holds a `db_version` row. Needs `DROP`. Absent → `changed=False`.
  - `_confirmation(target: str, confirm: str) -> list[Finding]` helper.

- [ ] **Step 1: Write the failing unit tests**

```python
# tests/test_provision_guards.py
from __future__ import annotations

from l3io.wp.database.provision import _confirmation
from l3io.wp.database.verdict import Code


def test_matching_confirmation_has_no_findings() -> None:
    assert _confirmation("wp_site", "wp_site") == []


def test_mismatched_confirmation_is_a_blocker_naming_both() -> None:
    [finding] = _confirmation("wp_site", "wp_stie")
    assert finding.code is Code.CONFIRMATION_MISMATCH
    assert finding.fields == {"target": "wp_site", "confirm": "wp_stie"}


def test_confirmation_is_exact_not_case_folded() -> None:
    assert _confirmation("wp_site", "WP_SITE")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest -q tests/test_provision_guards.py`
Expected: FAIL — `ImportError: cannot import name '_confirmation'`.

- [ ] **Step 3: Implement** — append to `src/l3io/wp/database/provision.py` (add `ER_NONEXISTING_GRANT, error_code` to the `._sql` import):

```python
@dataclass(frozen=True, slots=True)
class OperationResult:
    """Whether an operation changed anything, and what its check found."""

    changed: bool
    verdict: Verdict


def _confirmation(target: str, confirm: str) -> list[Finding]:
    if confirm == target:
        return []
    return [
        Finding(
            Code.CONFIRMATION_MISMATCH,
            f"confirm={confirm!r} does not match the target {target!r}",
            {"target": target, "confirm": confirm},
        )
    ]


def _user_exists(cur: Any, user: str, user_host: str) -> bool:
    cur.execute(
        "SELECT COUNT(*) FROM mysql.user WHERE User = %s AND Host = %s", (user, user_host)
    )
    return int(cur.fetchone()[0]) > 0


def _guarded(
    connection: Connection,
    admin: CredentialSource,
    name: str,
    required: tuple[str, ...],
    extra: list[Finding],
    user: tuple[str, str] | None,
) -> tuple[Verdict, Any | None]:
    """Preflight plus confirmation and, when ``user`` is given, account existence."""
    verdict, session = _preflight(connection, admin, name, required)
    verdict = verdict.with_findings(*extra)
    if session is not None and user is not None:
        with session.cursor() as cur:
            if not _user_exists(cur, *user):
                verdict = verdict.with_findings(
                    Finding(Code.USER_ABSENT, f"{user[0]!r}@{user[1]!r} does not exist")
                )
    if session is not None and not verdict.ok:
        session.close()
        session = None
    return verdict, session


def check_rotate_password(
    connection: Connection, admin: CredentialSource, wordpress: CredentialSource,
    *, user_host: str = "%",
) -> Verdict:
    """What :func:`rotate_password` would find."""
    with operation("check_rotate_password", connection):
        username = validate_user_name(wordpress.resolve().username)
        verdict, session = _guarded(
            connection, admin, "rotate_password", ("CREATE USER", "SELECT"), [], (username, user_host)
        )
        if session is not None:
            session.close()
        return verdict


def rotate_password(
    connection: Connection, admin: CredentialSource, wordpress: CredentialSource,
    *, user_host: str = "%",
) -> OperationResult:
    """Set the account's password to the one ``wordpress`` resolves to."""
    with operation("rotate_password", connection) as fields:
        wp = wordpress.resolve()
        username = validate_user_name(wp.username)
        verdict, session = _guarded(
            connection, admin, "rotate_password", ("CREATE USER", "SELECT"), [], (username, user_host)
        )
        if session is None:
            raise RefusedError(verdict)
        with session, session.cursor() as cur:
            try:
                cur.execute("ALTER USER %s@%s IDENTIFIED BY %s", (username, user_host, wp.password))
                session.commit()
            except pymysql.err.MySQLError as exc:
                msg = f"setting the password for {username!r} failed"
                raise ProvisioningError(msg) from exc
        fields["changed"] = True
        return OperationResult(True, verdict)


def check_revoke(
    connection: Connection, admin: CredentialSource, user: str,
    *, user_host: str = "%", confirm: str,
) -> Verdict:
    """What :func:`revoke` would find."""
    with operation("check_revoke", connection):
        validate_user_name(user)
        verdict, session = _guarded(
            connection, admin, "revoke", ("SELECT", "GRANT OPTION"),
            _confirmation(user, confirm), (user, user_host),
        )
        if session is not None:
            session.close()
        return verdict


def revoke(
    connection: Connection, admin: CredentialSource, user: str,
    *, user_host: str = "%", confirm: str,
) -> OperationResult:
    """Revoke the account's privileges on this database only."""
    with operation("revoke", connection) as fields:
        validate_user_name(user)
        verdict, session = _guarded(
            connection, admin, "revoke", ("SELECT", "GRANT OPTION"),
            _confirmation(user, confirm), (user, user_host),
        )
        if session is None:
            raise RefusedError(verdict)
        changed = True
        with session, session.cursor() as cur:
            try:
                cur.execute(
                    f"REVOKE ALL PRIVILEGES ON {quote_grant_database(connection.database)}.* "  # noqa: S608
                    "FROM %s@%s",
                    (user, user_host),
                )
                session.commit()
            except pymysql.err.MySQLError as exc:
                if error_code(exc) != ER_NONEXISTING_GRANT:
                    msg = f"revoking {user!r} on {connection.database!r} failed"
                    raise ProvisioningError(msg) from exc
                changed = False
        fields["changed"] = changed
        return OperationResult(changed, verdict)


def check_drop_user(
    connection: Connection, admin: CredentialSource, user: str,
    *, user_host: str = "%", confirm: str,
) -> Verdict:
    """What :func:`drop_user` would find."""
    with operation("check_drop_user", connection):
        validate_user_name(user)
        verdict, session = _guarded(
            connection, admin, "drop_user", ("CREATE USER", "SELECT"),
            _confirmation(user, confirm), None,
        )
        if session is not None:
            session.close()
        return verdict


def drop_user(
    connection: Connection, admin: CredentialSource, user: str,
    *, user_host: str = "%", confirm: str,
) -> OperationResult:
    """Drop the account. An absent account is ``changed=False``."""
    with operation("drop_user", connection) as fields:
        validate_user_name(user)
        verdict, session = _guarded(
            connection, admin, "drop_user", ("CREATE USER", "SELECT"),
            _confirmation(user, confirm), None,
        )
        if session is None:
            raise RefusedError(verdict)
        with session, session.cursor() as cur:
            existed = _user_exists(cur, user, user_host)
            try:
                cur.execute("DROP USER IF EXISTS %s@%s", (user, user_host))
                session.commit()
            except pymysql.err.MySQLError as exc:
                msg = f"dropping {user!r} failed"
                raise ProvisioningError(msg) from exc
        fields["changed"] = existed
        return OperationResult(existed, verdict)


def _looks_live(cur: Any, database: str) -> bool:
    cur.execute(
        "SELECT TABLE_NAME FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME LIKE %s",
        (database, "%options"),
    )
    for (table,) in cur.fetchall():
        try:
            cur.execute(
                f"SELECT COUNT(*) FROM {quote_identifier(database)}.{quote_identifier(table)} "  # noqa: S608
                "WHERE option_name = %s",
                ("db_version",),
            )
        except pymysql.err.MySQLError:
            continue
        if int(cur.fetchone()[0]) > 0:
            return True
    return False


def _drop_database_verdict(
    connection: Connection, admin: CredentialSource, confirm: str
) -> tuple[Verdict, Any | None]:
    verdict, session = _guarded(
        connection, admin, "drop_database", ("DROP",),
        _confirmation(connection.database, confirm), None,
    )
    if session is not None:
        with session.cursor() as cur:
            if _looks_live(cur, connection.database):
                verdict = verdict.with_findings(
                    Finding(
                        Code.LIVE_WORDPRESS_SITE,
                        f"{connection.database!r} holds a WordPress options table with a "
                        "schema version",
                    )
                )
    return verdict, session


def check_drop_database(
    connection: Connection, admin: CredentialSource, *, confirm: str
) -> Verdict:
    """What :func:`drop_database` would find."""
    with operation("check_drop_database", connection):
        verdict, session = _drop_database_verdict(connection, admin, confirm)
        if session is not None:
            session.close()
        return verdict


def drop_database(
    connection: Connection, admin: CredentialSource, *, confirm: str
) -> OperationResult:
    """Drop the database. An absent database is ``changed=False``."""
    with operation("drop_database", connection) as fields:
        verdict, session = _drop_database_verdict(connection, admin, confirm)
        if session is None:
            raise RefusedError(verdict)
        with session, session.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s",
                (connection.database,),
            )
            existed = int(cur.fetchone()[0]) > 0
            try:
                cur.execute(f"DROP DATABASE IF EXISTS {quote_identifier(connection.database)}")
                session.commit()
            except pymysql.err.MySQLError as exc:
                msg = f"dropping {connection.database!r} failed"
                raise ProvisioningError(msg) from exc
        fields["changed"] = existed
        return OperationResult(existed, verdict)
```

- [ ] **Step 4: Run unit tests**

Run: `uv run pytest -q tests/test_provision_guards.py tests/test_provision_plan.py && make lint types`
Expected: all pass.

- [ ] **Step 5: Write the failing integration tests** — append to `tests/test_integration.py`:

```python
from l3io.wp.database.provision import (
    check_drop_database,
    drop_database,
    drop_user,
    revoke,
    rotate_password,
)


def provisioned(suffix: str) -> Connection:
    ensure(new_site(suffix), new_admin(), Explicit(f"u_{suffix}", "wp-pass"))
    return new_site(suffix)


def test_drop_database_refuses_a_wrong_confirmation(suffix: str) -> None:
    conn = provisioned(suffix)
    with pytest.raises(RefusedError) as info:
        drop_database(conn, new_admin(), confirm="wp_something_else")
    assert Code.CONFIRMATION_MISMATCH in info.value.verdict.codes
    assert survey(conn, new_admin()).database_exists


def test_drop_database_warns_on_a_live_site(suffix: str) -> None:
    conn = provisioned(suffix)
    admin_sql(
        f"CREATE TABLE `wp_{suffix}`.`wp_options` (option_name VARCHAR(191), option_value LONGTEXT)",
        f"INSERT INTO `wp_{suffix}`.`wp_options` VALUES ('db_version', '58975')",
    )
    verdict = check_drop_database(conn, new_admin(), confirm=conn.database)
    assert verdict.ok and Code.LIVE_WORDPRESS_SITE in verdict.codes


def test_drop_database_twice(suffix: str) -> None:
    conn = provisioned(suffix)
    assert drop_database(conn, new_admin(), confirm=conn.database).changed is True
    assert drop_database(conn, new_admin(), confirm=conn.database).changed is False


def test_drop_user_twice(suffix: str) -> None:
    conn = provisioned(suffix)
    user = f"u_{suffix}"
    assert drop_user(conn, new_admin(), user, confirm=user).changed is True
    assert drop_user(conn, new_admin(), user, confirm=user).changed is False


def test_revoke_then_revoke_again(suffix: str) -> None:
    conn = provisioned(suffix)
    user = f"u_{suffix}"
    assert revoke(conn, new_admin(), user, confirm=user).changed is True
    assert revoke(conn, new_admin(), user, confirm=user).changed is False
    assert survey(conn, new_admin(), wordpress_user=user).user_privileges == frozenset()


def test_revoke_absent_user_is_a_blocker(suffix: str) -> None:
    conn = new_site(suffix)
    with pytest.raises(RefusedError) as info:
        revoke(conn, new_admin(), f"u_{suffix}", confirm=f"u_{suffix}")
    assert Code.USER_ABSENT in info.value.verdict.codes


def test_rotate_password(suffix: str) -> None:
    conn = provisioned(suffix)
    rotate_password(conn, new_admin(), Explicit(f"u_{suffix}", "rotated"))
    pymysql.connect(host=HOST, port=PORT, user=f"u_{suffix}", password="rotated").close()
```

- [ ] **Step 6: Run integration tests on both servers**

Run:
```bash
make test-db DB_HOST=127.0.0.1 DB_PORT=33306 DB_ADMIN_USER=root DB_ADMIN_PASSWORD=root
make test-db DB_HOST=127.0.0.1 DB_PORT=33307 DB_ADMIN_USER=root DB_ADMIN_PASSWORD=root
```
Expected: all pass on both.

- [ ] **Step 7: Commit**

```bash
git add src/l3io/wp/database/provision.py tests/test_provision_guards.py tests/test_integration.py
git commit -m "feat: rotate_password, revoke, drop_user, drop_database with name guards (spec §7.2)"
```

---

### Task 12: `Database` facade

**Files:**
- Create: `src/l3io/wp/database/facade.py`
- Test: `tests/test_facade.py`

**Interfaces:**
- Consumes: every public function of Tasks 9–11.
- Produces: `Database(connection: Connection)` with property `connection` and methods `survey`, `inspect`, `schema_version`, `check_ensure`, `ensure`, `check_rotate_password`, `rotate_password`, `check_revoke`, `revoke`, `check_drop_user`, `drop_user`, `check_drop_database`, `drop_database` — each the free function with `connection` bound.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_facade.py
"""The facade binds a connection and adds nothing else."""

from __future__ import annotations

import inspect as pyinspect

from l3io.wp.database import inspection, provision
from l3io.wp.database.connection import Connection
from l3io.wp.database.facade import Database

OPERATIONS = [
    "survey", "inspect", "schema_version",
    "check_ensure", "ensure", "check_rotate_password", "rotate_password",
    "check_revoke", "revoke", "check_drop_user", "drop_user",
    "check_drop_database", "drop_database",
]


def _free(name: str):  # type: ignore[no-untyped-def]
    return getattr(inspection, name, None) or getattr(provision, name)


def test_every_operation_is_bound_with_the_same_parameters() -> None:
    for name in OPERATIONS:
        method = getattr(Database, name)
        free = list(pyinspect.signature(_free(name)).parameters)
        bound = list(pyinspect.signature(method).parameters)
        assert bound == ["self", *free[1:]], name


def test_inspect_delegates() -> None:
    db = Database(Connection(host="127.0.0.1", database="wp", port=1))
    from l3io.wp.database.credentials import Explicit
    from l3io.wp.database.state import ConnectionState

    assert db.inspect(Explicit("u", "p")) is ConnectionState.UNREACHABLE
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest -q tests/test_facade.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'l3io.wp.database.facade'`.

- [ ] **Step 3: Implement**

```python
# src/l3io/wp/database/facade.py
"""One object for one site: every operation with the connection bound."""

from __future__ import annotations

from . import inspection, provision
from .connection import Connection
from .credentials import CredentialSource
from .inspection import Survey
from .provision import EnsureResult, OperationResult
from .state import ConnectionState
from .verdict import Verdict
from .versions import SchemaVersion


class Database:
    """Every operation against one :class:`Connection`."""

    __slots__ = ("_connection",)

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    @property
    def connection(self) -> Connection:
        return self._connection

    def survey(
        self, admin: CredentialSource, *, wordpress_user: str | None = None,
        user_host: str = "%", table_prefix: str = "wp_",
    ) -> Survey:
        return inspection.survey(
            self._connection, admin, wordpress_user=wordpress_user,
            user_host=user_host, table_prefix=table_prefix,
        )

    def inspect(self, credentials: CredentialSource) -> ConnectionState:
        return inspection.inspect(self._connection, credentials)

    def schema_version(
        self, credentials: CredentialSource, table_prefix: str = "wp_"
    ) -> SchemaVersion | None:
        return inspection.schema_version(self._connection, credentials, table_prefix)

    def check_ensure(
        self, admin: CredentialSource, wordpress: CredentialSource, *, user_host: str = "%"
    ) -> Verdict:
        return provision.check_ensure(self._connection, admin, wordpress, user_host=user_host)

    def ensure(
        self, admin: CredentialSource, wordpress: CredentialSource, *, user_host: str = "%",
        charset: str = "utf8mb4", collation: str = "utf8mb4_unicode_ci",
    ) -> EnsureResult:
        return provision.ensure(
            self._connection, admin, wordpress, user_host=user_host,
            charset=charset, collation=collation,
        )

    def check_rotate_password(
        self, admin: CredentialSource, wordpress: CredentialSource, *, user_host: str = "%"
    ) -> Verdict:
        return provision.check_rotate_password(
            self._connection, admin, wordpress, user_host=user_host
        )

    def rotate_password(
        self, admin: CredentialSource, wordpress: CredentialSource, *, user_host: str = "%"
    ) -> OperationResult:
        return provision.rotate_password(self._connection, admin, wordpress, user_host=user_host)

    def check_revoke(
        self, admin: CredentialSource, user: str, *, user_host: str = "%", confirm: str
    ) -> Verdict:
        return provision.check_revoke(
            self._connection, admin, user, user_host=user_host, confirm=confirm
        )

    def revoke(
        self, admin: CredentialSource, user: str, *, user_host: str = "%", confirm: str
    ) -> OperationResult:
        return provision.revoke(self._connection, admin, user, user_host=user_host, confirm=confirm)

    def check_drop_user(
        self, admin: CredentialSource, user: str, *, user_host: str = "%", confirm: str
    ) -> Verdict:
        return provision.check_drop_user(
            self._connection, admin, user, user_host=user_host, confirm=confirm
        )

    def drop_user(
        self, admin: CredentialSource, user: str, *, user_host: str = "%", confirm: str
    ) -> OperationResult:
        return provision.drop_user(
            self._connection, admin, user, user_host=user_host, confirm=confirm
        )

    def check_drop_database(self, admin: CredentialSource, *, confirm: str) -> Verdict:
        return provision.check_drop_database(self._connection, admin, confirm=confirm)

    def drop_database(self, admin: CredentialSource, *, confirm: str) -> OperationResult:
        return provision.drop_database(self._connection, admin, confirm=confirm)

    def __repr__(self) -> str:
        return f"Database({self._connection!r})"
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest -q tests/test_facade.py && make lint types`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/l3io/wp/database/facade.py tests/test_facade.py
git commit -m "feat: Database facade binding one Connection (spec §3)"
```

---

### Task 13: Switch the package root to the new surface; delete the old one

**Files:**
- Modify: `src/l3io/wp/database/__init__.py`, `errors.py`, `credentials.py`, `connection.py`, `wpconfig.py`, `versions.py`
- Delete: `src/l3io/wp/database/database.py`
- Modify/merge tests: `tests/test_connection.py` (absorb `test_connection_new.py`), `tests/test_credentials.py` (absorb `test_credential_sources.py`), `tests/test_wpconfig.py` (absorb `test_wpconfig_file.py`), `tests/test_versions.py`, `tests/test_secrets.py`, `tests/test_integration.py`
- Create: `tests/test_public_surface.py`

**Interfaces:**
- Produces: `l3io.wp.database.__all__` exactly:

```python
__all__ = [
    "AccessDeniedError", "AuthenticationFailedError", "AwsSecretsManager",
    "ConfigUnreadableError", "ConfigurationError", "Connection", "ConnectionState",
    "CredentialChain", "CredentialSource", "CredentialsAbsentError",
    "CredentialsUnobtainableError", "DEFAULT_PORT", "DEFAULT_TABLE_PREFIX", "Database",
    "DatabaseError", "DatabaseUnreachableError", "EnsureResult", "Environment", "Explicit",
    "Finding", "InvalidArgumentsError", "InvalidDatabaseNameError", "InvalidIdentifierError",
    "MissingConfigValueError", "MissingDependencyError", "OperationResult",
    "ProvisioningError", "RefusedError", "RegionNotKnownError", "ResolvedCredentials",
    "SUPPORTED_FROM", "SchemaVersion", "ServerFamily", "ServerInfo", "Severity", "Code",
    "Survey", "Verdict", "WpConfigFile", "__version__",
    "check_drop_database", "check_drop_user", "check_ensure", "check_revoke",
    "check_rotate_password", "drop_database", "drop_user", "ensure", "inspect",
    "quote_grant_database", "quote_identifier", "release_for", "revoke",
    "rotate_password", "schema_version", "survey", "validate_database_name",
    "validate_user_name",
]
```

- [ ] **Step 1: Write the failing surface tests**

```python
# tests/test_public_surface.py
"""The public surface: no Wp prefix, no name colliding with a submodule."""

from __future__ import annotations

import pkgutil
from pathlib import Path

import l3io.wp.database as pkg

SRC = Path(pkg.__file__).parent


def test_no_public_name_has_a_wp_prefix() -> None:
    offenders = [n for n in pkg.__all__ if n.startswith("Wp") and n != "WpConfigFile"]
    assert offenders == []


def test_no_root_export_shadows_a_submodule() -> None:
    modules = {m.name for m in pkgutil.iter_modules([str(SRC)])}
    assert modules, "no submodules found -- this guard is vacuous"
    assert modules.isdisjoint(pkg.__all__)


def test_every_exported_name_exists() -> None:
    for name in pkg.__all__:
        assert hasattr(pkg, name), name


def test_old_names_are_gone() -> None:
    for name in ("WpDatabase", "WpConnection", "WpCredentials", "WpConfigSource",
                 "WpDatabaseError", "WpDatabaseVersion"):
        assert not hasattr(pkg, name), name
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest -q tests/test_public_surface.py`
Expected: FAIL — `WpDatabase` etc. still present.

- [ ] **Step 3: Rewrite `src/l3io/wp/database/__init__.py`**

```python
"""WordPress database operations, each checked before it runs.

``l3io`` and ``l3io.wp`` are a PEP 420 namespace shared with
``l3io-wordpress-config`` and ``l3io-wordpress-backup``; this is the only
``__init__.py`` above this directory (AD-27).
"""

from __future__ import annotations

from ._version import __version__
from .connection import DEFAULT_PORT, Connection
from .credentials import (
    AwsSecretsManager,
    CredentialChain,
    CredentialSource,
    Environment,
    Explicit,
    ResolvedCredentials,
)
from .errors import (
    AccessDeniedError,
    AuthenticationFailedError,
    ConfigUnreadableError,
    ConfigurationError,
    CredentialsAbsentError,
    CredentialsUnobtainableError,
    DatabaseError,
    DatabaseUnreachableError,
    InvalidArgumentsError,
    InvalidDatabaseNameError,
    InvalidIdentifierError,
    MissingConfigValueError,
    MissingDependencyError,
    ProvisioningError,
    RefusedError,
    RegionNotKnownError,
)
from .facade import Database
from .identifiers import (
    quote_grant_database,
    quote_identifier,
    validate_database_name,
    validate_user_name,
)
from .inspection import Survey, inspect, schema_version, survey
from .provision import (
    EnsureResult,
    OperationResult,
    check_drop_database,
    check_drop_user,
    check_ensure,
    check_revoke,
    check_rotate_password,
    drop_database,
    drop_user,
    ensure,
    revoke,
    rotate_password,
)
from .server import ServerFamily, ServerInfo
from .state import ConnectionState
from .verdict import Code, Finding, Severity, Verdict
from .versions import SUPPORTED_FROM, SchemaVersion, release_for
from .wpconfig import DEFAULT_TABLE_PREFIX, WpConfigFile

__all__ = [
    # (the list from this task's Interfaces block, verbatim)
]
```

Paste the `__all__` list from the Interfaces block in place of the comment.

- [ ] **Step 4: Delete the old implementation**

```bash
git rm src/l3io/wp/database/database.py
```
Then remove: class `WpCredentials` from `credentials.py`; class `WpConnection` from `connection.py` (keep `_split_db_host`, `DEFAULT_PORT`); class `WpConfigSource` from `wpconfig.py`; the `WpDatabaseError` alias from `errors.py`; the `WpDatabaseVersion` alias from `versions.py`.

- [ ] **Step 5: Merge and port the old tests**
  - `tests/test_connection.py` → replace its content with `tests/test_connection_new.py`'s; `git rm tests/test_connection_new.py`.
  - `tests/test_credentials.py` → replace with `tests/test_credential_sources.py`'s content; `git rm tests/test_credential_sources.py`.
  - `tests/test_wpconfig.py` → replace with `tests/test_wpconfig_file.py`'s content; `git rm tests/test_wpconfig_file.py`.
  - `tests/test_versions.py` → replace `WpDatabaseVersion` with `SchemaVersion` throughout.
  - `tests/test_secrets.py` → replace `unreachable_site()` and every use of `WpDatabase`/`WpConnection`/`WpCredentials` with the new API:

```python
from l3io.wp.database import Connection, Explicit, ResolvedCredentials, ensure, inspect

CONN = Connection(host="127.0.0.1", port=1, database="wp_site")
WORDPRESS = Explicit("wpuser", SECRET)
```
  Use `inspect(CONN, WORDPRESS)` where the old tests called `unreachable_site().inspect()`, and `ensure(CONN, Explicit("root", SECRET), WORDPRESS)` (expecting `RefusedError`) where they called `ensure`. Keep `test_no_module_spawns_a_subprocess` unchanged (Plan 2 replaces it).
  - `tests/test_integration.py` → delete every test using the old API (`site()`, `admin()`, `WpDatabase`, `WpConnection`, `WpCredentials`), keeping the module docstring, constants, `admin_sql`, `suffix`, and all tests added in Tasks 9–11. Port the two remaining behaviours not yet covered by new tests:

```python
from l3io.wp.database import ConnectionState, inspect


def test_fresh_site_reports_authentication_failure_not_absence(suffix: str) -> None:
    """The server authenticates before it resolves the database, so the
    WordPress account's own probe cannot report DATABASE_ABSENT before the
    account exists. The administrator is the authority (AD-29)."""
    state = inspect(new_site(suffix), Explicit(f"u_{suffix}", "wp-pass"))
    assert state is ConnectionState.AUTHENTICATION_FAILED
    assert state.needs_provisioning


def test_inspect_ready_after_ensure(suffix: str) -> None:
    wp = Explicit(f"u_{suffix}", "wp-pass")
    ensure(new_site(suffix), new_admin(), wp)
    assert inspect(new_site(suffix), wp) is ConnectionState.READY
```

- [ ] **Step 6: Run everything**

Run: `make check`
Then: `make test-db DB_HOST=127.0.0.1 DB_PORT=33306 DB_ADMIN_USER=root DB_ADMIN_PASSWORD=root` and the same with `DB_PORT=33307`.
Expected: all pass. `tests/test_cli.py` will fail until Task 14 — mark it with `pytestmark = pytest.mark.skip(reason="replaced in plan 1 task 14")` at the top of the file in this task, and remove that line in Task 14.

- [ ] **Step 7: Commit**

```bash
git add -A src tests
git commit -m "refactor!: switch the public surface to the new API and remove the 0.0.x one"
```

---

### Task 14: CLI — one subcommand per operation, no password-valued options

**Files:**
- Modify: `src/l3io/wp/database/cli.py` (full rewrite)
- Modify: `tests/test_cli.py` (full rewrite)

**Interfaces:**
- Consumes: the public surface from Task 13.
- Produces: `cli.main(argv: list[str] | None = None) -> int`; `cli.build_parser() -> argparse.ArgumentParser`; `cli.Exit` (`OK=0, FAILED=1, USAGE=2, REFUSED=3, CREDENTIALS=4, UNREACHABLE=5, NOT_READY=7`).

Subcommands and their options:

| Subcommand | Site | WordPress account | Admin | Other |
|---|---|---|---|---|
| `survey` | yes | — | yes | `--wordpress-user`, `--user-host`, `--table-prefix` |
| `inspect` | yes | yes | — | — |
| `schema-version` | yes | yes | — | `--table-prefix` |
| `ensure` | yes | yes | yes | `--user-host` |
| `rotate-password` | yes | yes | yes | `--user-host` |
| `revoke`, `drop-user` | yes | — | yes | `--user`, `--user-host`, `--confirm` |
| `drop-database` | yes | — | yes | `--confirm` |
| `check OPERATION` | as the operation | | | `OPERATION` ∈ `ensure, rotate-password, revoke, drop-user, drop-database` |

Option groups:
- Site: `--wp-config PATH` **or** `--db-host HOST[:PORT]` with `--db-name NAME`.
- WordPress account: `--wp-config PATH` **or** `--db-user NAME` with `--db-password-env VAR` (or a prompt when stdin is a TTY).
- Admin: `--admin-user NAME` with `--admin-password-env VAR` (or a TTY prompt), **or** `--admin-aws-secret-id ID` [`--admin-aws-region R`].
- Global: `--log-level` (default `INFO`), `--log-format {console,json}` (default `console`), `--version`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cli.py
"""The command line: argument handling, exit codes, and no password on argv."""

from __future__ import annotations

import json
from typing import Any

import pytest

from l3io.wp.database import cli
from l3io.wp.database.provision import EnsureResult, OperationResult
from l3io.wp.database.state import ConnectionState
from l3io.wp.database.verdict import Code, Finding, Verdict

SITE = ["--db-host", "db:3307", "--db-name", "wp_site"]
WP = ["--db-user", "wpuser", "--db-password-env", "WP_PW"]
ADMIN = ["--admin-user", "root", "--admin-password-env", "ADMIN_PW"]


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WP_PW", "wp-secret")
    monkeypatch.setenv("ADMIN_PW", "admin-secret")


def _actions(parser: Any) -> list[Any]:
    found = list(parser._actions)
    for action in parser._actions:
        for sub in (getattr(action, "choices", None) or {}).values():
            if hasattr(sub, "_actions"):
                found += _actions(sub)
    return found


def test_no_option_takes_a_password_value() -> None:
    offenders = [
        a.option_strings for a in _actions(cli.build_parser())
        if any("password" in s for s in a.option_strings) and not all(s.endswith("-env") for s in a.option_strings)
    ]
    assert offenders == []


def test_ensure_success_prints_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    calls: dict[str, Any] = {}

    def fake_ensure(connection, admin, wordpress, **kw):  # type: ignore[no-untyped-def]
        calls.update(connection=connection, admin=admin.resolve(), wordpress=wordpress.resolve(), kw=kw)
        return EnsureResult(True, True, True, True, Verdict("ensure"))

    monkeypatch.setattr(cli, "ensure", fake_ensure)
    assert cli.main(["ensure", *SITE, *WP, *ADMIN]) == cli.Exit.OK
    out = json.loads(capsys.readouterr().out)
    assert out["created_database"] is True
    assert calls["connection"].port == 3307
    assert calls["admin"].password == "admin-secret"
    assert calls["wordpress"].password == "wp-secret"


def test_refusal_maps_to_refused_exit(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from l3io.wp.database.errors import RefusedError

    def refuse(*a: Any, **k: Any) -> Any:
        raise RefusedError(Verdict("drop_database", (Finding(Code.CONFIRMATION_MISMATCH, "no"),)))

    monkeypatch.setattr(cli, "drop_database", refuse)
    code = cli.main(["drop-database", *SITE, *ADMIN, "--confirm", "wrong"])
    assert code == cli.Exit.REFUSED
    assert "confirmation_mismatch" in capsys.readouterr().err


def test_unreachable_refusal_maps_to_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    from l3io.wp.database.errors import RefusedError

    def refuse(*a: Any, **k: Any) -> Any:
        raise RefusedError(Verdict("ensure", (Finding(Code.UNREACHABLE, "down"),)))

    monkeypatch.setattr(cli, "ensure", refuse)
    assert cli.main(["ensure", *SITE, *WP, *ADMIN]) == cli.Exit.UNREACHABLE


def test_inspect_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "inspect", lambda *a, **k: ConnectionState.DATABASE_ABSENT)
    assert cli.main(["inspect", *SITE, *WP]) == cli.Exit.NOT_READY


def test_destructive_subcommands_require_confirm() -> None:
    with pytest.raises(SystemExit) as info:
        cli.main(["drop-database", *SITE, *ADMIN])
    assert info.value.code == cli.Exit.USAGE


def test_missing_password_variable_is_a_credentials_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADMIN_PW")
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert cli.main(["drop-database", *SITE, *ADMIN, "--confirm", "wp_site"]) == cli.Exit.CREDENTIALS


def test_check_subcommand_prints_the_verdict(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        cli, "check_drop_database",
        lambda *a, **k: Verdict("drop_database", (Finding(Code.LIVE_WORDPRESS_SITE, "live"),)),
    )
    assert cli.main(["check", "drop-database", *SITE, *ADMIN, "--confirm", "wp_site"]) == cli.Exit.OK
    out = json.loads(capsys.readouterr().out)
    assert out["findings"][0]["code"] == "live_wordpress_site"


def test_revoke_passes_user_and_confirm(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake(connection, admin, user, **kw):  # type: ignore[no-untyped-def]
        seen.update(user=user, **kw)
        return OperationResult(True, Verdict("revoke"))

    monkeypatch.setattr(cli, "revoke", fake)
    assert cli.main(["revoke", *SITE, *ADMIN, "--user", "wpuser", "--confirm", "wpuser"]) == cli.Exit.OK
    assert seen == {"user": "wpuser", "user_host": "%", "confirm": "wpuser"}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest -q tests/test_cli.py`
Expected: FAIL (old CLI has no subcommands).

- [ ] **Step 3: Implement** — replace `src/l3io/wp/database/cli.py` entirely:

```python
"""Command line entry point.

The library never configures logging; this does, because it owns the process.
No option takes a password value: an argument vector is visible to every user
on the machine. Passwords come from environment variables, wp-config.php, AWS,
or a prompt on a terminal.
"""

from __future__ import annotations

import argparse
import dataclasses
import getpass
import json
import logging
import os
import sys
from collections.abc import Mapping
from enum import Enum, IntEnum
from typing import Any

import structlog

from ._version import __version__
from .connection import Connection
from .credentials import AwsSecretsManager, CredentialSource, Explicit
from .errors import (
    ConfigurationError,
    CredentialsAbsentError,
    CredentialsUnobtainableError,
    DatabaseError,
    DatabaseUnreachableError,
    InvalidArgumentsError,
    InvalidIdentifierError,
    MissingDependencyError,
    RefusedError,
)
from .inspection import inspect, schema_version, survey
from .provision import (
    check_drop_database,
    check_drop_user,
    check_ensure,
    check_revoke,
    check_rotate_password,
    drop_database,
    drop_user,
    ensure,
    revoke,
    rotate_password,
)
from .verdict import Code, Verdict


class Exit(IntEnum):
    """Process exit codes. Part of the CLI contract."""

    OK = 0
    FAILED = 1
    USAGE = 2
    REFUSED = 3
    CREDENTIALS = 4
    UNREACHABLE = 5
    NOT_READY = 7


_NEEDS_WP = {"inspect", "schema-version", "ensure", "rotate-password"}
_NEEDS_ADMIN = {"survey", "ensure", "rotate-password", "revoke", "drop-user", "drop-database"}
_NAMED_USER = {"revoke", "drop-user"}
_CONFIRM = {"revoke", "drop-user", "drop-database"}
_CHECKABLE = ["ensure", "rotate-password", "revoke", "drop-user", "drop-database"]


def _add_operation_options(p: argparse.ArgumentParser, operation: str) -> None:
    site = p.add_argument_group("site")
    site.add_argument("--wp-config", help="path to wp-config.php (needs the 'wpconfig' extra)")
    site.add_argument("--db-host", help="database host, optionally host:port")
    site.add_argument("--db-name", help="database name")
    if operation in _NEEDS_WP:
        wp = p.add_argument_group("WordPress account (or --wp-config)")
        wp.add_argument("--db-user", help="WordPress database user")
        wp.add_argument("--db-password-env", metavar="VAR", help="variable holding its password")
    if operation in _NEEDS_ADMIN:
        admin = p.add_argument_group("administrative account (required)")
        admin.add_argument("--admin-user", help="administrative user")
        admin.add_argument("--admin-password-env", metavar="VAR", help="variable holding its password")
        admin.add_argument("--admin-aws-secret-id", help="AWS secret holding the admin credentials")
        admin.add_argument("--admin-aws-region", help="AWS region of that secret")
    if operation in {"survey", "ensure", "rotate-password", *_NAMED_USER}:
        p.add_argument("--user-host", default="%", help="host part of the account (default: %%)")
    if operation in _NAMED_USER:
        p.add_argument("--user", required=True, help="the account to act on")
    if operation in _CONFIRM:
        p.add_argument("--confirm", required=True, metavar="NAME", help="repeat the target's name")
    if operation == "survey":
        p.add_argument("--wordpress-user", help="also report this account's existence and privileges")
    if operation in {"survey", "schema-version"}:
        p.add_argument("--table-prefix", help="WordPress $table_prefix (default: from wp-config, else wp_)")


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="l3io-wordpress-database",
        description="WordPress database operations, each checked before it runs.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--log-level", default="INFO", help="logging level (default: INFO)")
    parser.add_argument("--log-format", choices=["console", "json"], default="console")
    sub = parser.add_subparsers(dest="operation", required=True)
    for name in ["survey", "inspect", "schema-version", *_CHECKABLE]:
        _add_operation_options(sub.add_parser(name), name)
    check = sub.add_parser("check", help="run an operation's check only")
    check_sub = check.add_subparsers(dest="checked", required=True)
    for name in _CHECKABLE:
        _add_operation_options(check_sub.add_parser(name), name)
    return parser


def _configure_logging(level: str, fmt: str) -> None:
    numeric = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
    logging.basicConfig(level=numeric, format="%(message)s", stream=sys.stderr)
    renderer: Any = (
        structlog.processors.JSONRenderer() if fmt == "json" else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )


def _password(var: str | None, who: str) -> str:
    if var is not None:
        value = os.environ.get(var)
        if value is None:
            msg = f"{var} is not set"
            raise CredentialsUnobtainableError(msg)
        return value
    if sys.stdin.isatty():
        return getpass.getpass(f"password for {who}: ")
    msg = f"no password source for {who}: give the -env option or run on a terminal"
    raise CredentialsUnobtainableError(msg)


def _site(args: argparse.Namespace) -> tuple[Connection, Any]:
    if args.wp_config:
        if args.db_host or args.db_name:
            msg = "give either --wp-config or --db-host/--db-name, not both"
            raise InvalidArgumentsError(msg)
        from .wpconfig import WpConfigFile

        config = WpConfigFile(args.wp_config)
        return config.connection(), config
    if not (args.db_host and args.db_name):
        msg = "give --wp-config, or both --db-host and --db-name"
        raise InvalidArgumentsError(msg)
    return Connection.from_db_host(args.db_host, args.db_name), None


def _wordpress(args: argparse.Namespace, config: Any) -> CredentialSource:
    if config is not None and not getattr(args, "db_user", None):
        return config  # type: ignore[no-any-return]
    if not getattr(args, "db_user", None):
        msg = "give --wp-config or --db-user"
        raise InvalidArgumentsError(msg)
    return Explicit(args.db_user, _password(args.db_password_env, args.db_user))


def _admin(args: argparse.Namespace) -> CredentialSource:
    if args.admin_aws_secret_id:
        if args.admin_user:
            msg = "give either --admin-user or --admin-aws-secret-id, not both"
            raise InvalidArgumentsError(msg)
        return AwsSecretsManager(args.admin_aws_secret_id, args.admin_aws_region)
    if not args.admin_user:
        msg = "administrative credentials are required: give --admin-user or --admin-aws-secret-id"
        raise InvalidArgumentsError(msg)
    return Explicit(args.admin_user, _password(args.admin_password_env, args.admin_user))


def _jsonable(obj: Any) -> Any:
    """Convert a result to JSON-ready data.

    Not ``dataclasses.asdict``: it deep-copies values, and a Finding's fields
    are a read-only mapping that cannot be copied.
    """
    if isinstance(obj, Verdict):
        return {
            "operation": obj.operation,
            "ok": obj.ok,
            "findings": [
                {"code": str(f.code), "severity": str(f.severity), "message": f.message,
                 "fields": dict(f.fields)}
                for f in obj.findings
            ],
        }
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, Enum):
        return str(obj.value)
    if isinstance(obj, Mapping):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (set, frozenset)):
        return sorted(_jsonable(v) for v in obj)
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


def _emit(value: Any) -> None:
    print(json.dumps(_jsonable(value), indent=2))


def _run(args: argparse.Namespace) -> int:
    operation = args.checked if args.operation == "check" else args.operation
    connection, config = _site(args)
    prefix = getattr(args, "table_prefix", None) or (config.table_prefix if config else "wp_")

    if args.operation == "check":
        admin = _admin(args)
        checks: dict[str, Any] = {
            "ensure": lambda: check_ensure(connection, admin, _wordpress(args, config), user_host=args.user_host),
            "rotate-password": lambda: check_rotate_password(connection, admin, _wordpress(args, config), user_host=args.user_host),
            "revoke": lambda: check_revoke(connection, admin, args.user, user_host=args.user_host, confirm=args.confirm),
            "drop-user": lambda: check_drop_user(connection, admin, args.user, user_host=args.user_host, confirm=args.confirm),
            "drop-database": lambda: check_drop_database(connection, admin, confirm=args.confirm),
        }
        verdict = checks[operation]()
        _emit(verdict)
        return Exit.OK if verdict.ok else Exit.REFUSED

    if operation == "inspect":
        state = inspect(connection, _wordpress(args, config))
        _emit({"state": str(state)})
        return Exit.OK if state.is_ready else Exit.NOT_READY
    if operation == "schema-version":
        version = schema_version(connection, _wordpress(args, config), prefix)
        _emit({"db_version": getattr(version, "db_version", None),
               "release": getattr(version, "release", None)})
        return Exit.OK
    if operation == "survey":
        _emit(survey(connection, _admin(args), wordpress_user=args.wordpress_user,
                     user_host=args.user_host, table_prefix=prefix))
        return Exit.OK
    if operation == "ensure":
        _emit(ensure(connection, _admin(args), _wordpress(args, config), user_host=args.user_host))
        return Exit.OK
    if operation == "rotate-password":
        _emit(rotate_password(connection, _admin(args), _wordpress(args, config), user_host=args.user_host))
        return Exit.OK
    if operation == "revoke":
        _emit(revoke(connection, _admin(args), args.user, user_host=args.user_host, confirm=args.confirm))
        return Exit.OK
    if operation == "drop-user":
        _emit(drop_user(connection, _admin(args), args.user, user_host=args.user_host, confirm=args.confirm))
        return Exit.OK
    _emit(drop_database(connection, _admin(args), confirm=args.confirm))
    return Exit.OK


def _refusal_exit(verdict: Verdict) -> Exit:
    if Code.UNREACHABLE in verdict.codes:
        return Exit.UNREACHABLE
    if Code.CREDENTIALS_UNOBTAINABLE in verdict.codes:
        return Exit.CREDENTIALS
    return Exit.REFUSED


def main(argv: list[str] | None = None) -> int:
    """Run the command line interface."""
    args = build_parser().parse_args(argv)
    _configure_logging(args.log_level, args.log_format)
    try:
        return _run(args)
    except RefusedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return _refusal_exit(exc.verdict)
    except (CredentialsUnobtainableError, CredentialsAbsentError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return Exit.CREDENTIALS
    except DatabaseUnreachableError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return Exit.UNREACHABLE
    except (InvalidArgumentsError, InvalidIdentifierError, MissingDependencyError, ConfigurationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return Exit.USAGE
    except DatabaseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return Exit.FAILED
```

Check the `SchemaVersion` attribute names used in `_emit` for `schema-version` against `versions.py` (`db_version` field and `release` property); adjust if they differ.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest -q tests/test_cli.py && make check`
Expected: all pass. Also confirm the console script still runs: `uv run l3io-wordpress-database --help` lists every subcommand.

- [ ] **Step 5: Commit**

```bash
git add src/l3io/wp/database/cli.py tests/test_cli.py
git commit -m "feat!: subcommand CLI with no password-valued option (spec §9)"
```

---

### Task 15: Record the spec amendments and verify the whole

**Files:**
- Modify: `_bmad-output/planning-artifacts/spec/2026-10-12-l3io-wordpress-database-design.md`

- [ ] **Step 1: Apply the amendments** — edit the spec so it states, in present tense:
  1. §6 catalogue: add row `PRIVILEGES_UNVERIFIED | warning | the account holds an active role, so privileges were not checked in advance`; and add after the table: "Codes are added by the plan that emits them; Plan 2 adds the transfer codes."
  2. §3 and §5: `WpConfigFile` also provides `connection()` and `table_prefix`.
  3. §10 table: add `DatabaseUnreachableError`, `AuthenticationFailedError`, `AccessDeniedError` — "raised by the read operations `survey` and `schema_version`, which have no check form".
  4. §7.2 table: `drop_user` and `drop_database` — "an absent target is `changed=False`"; `ensure` — "needs `CREATE`, `CREATE USER`, global `SELECT` and `GRANT OPTION`"; `charset` and `collation` validated as `^[A-Za-z0-9_]+$`.
  5. §9: "Results are printed as JSON on stdout; `inspect` exits `NOT_READY` (7) when the account cannot use the database."
  6. §16 V6: replace with the observed result from Task 1.

- [ ] **Step 2: Full verification**

```bash
make check
make test-db DB_HOST=127.0.0.1 DB_PORT=33306 DB_ADMIN_USER=root DB_ADMIN_PASSWORD=root
make test-db DB_HOST=127.0.0.1 DB_PORT=33307 DB_ADMIN_USER=root DB_ADMIN_PASSWORD=root
make ci
uv run python ../l3io-wordpress-backup/scripts/check-cicd-alignment.py
```
Expected: every command succeeds; `make ci` passes all jobs; alignment reports 0 findings.

- [ ] **Step 3: Stop the test servers**

```bash
docker rm -f l3io-it l3io-it-ma
```

- [ ] **Step 4: Commit**

```bash
git add _bmad-output/planning-artifacts/spec/2026-10-12-l3io-wordpress-database-design.md
git commit -m "spec: record plan 1's amendments (V6 result, idempotent drops, CLI output)"
```
