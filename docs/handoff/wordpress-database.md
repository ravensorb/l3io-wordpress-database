# Handoff — wordpress-database

> **Resume line:** You are `wordpress-database`. Read `docs/handoff/wordpress-database.md` in
> this repo, then continue.

Written 2026-09-27, at `main` = `945069bf` plus three uncommitted changes (below).

## What I own

This repository only: `l3io-wordpress-database`, second in a three-package family. The siblings are
owned by other sessions — `wordpress-config` (`l3io-wp-config`, release position 1) and
`wordpress-backup` (`l3io-wp-backup`, position 3). Do not edit their repos; message them.

The package is a full rewrite of the abandoned `wpdatabase2`: new distribution, new PEP 420
namespace `l3io.wp.database`, nothing preserved from the old surface, no shim.

## Read first, in this order

1. `AGENTS.md` — the operating rules. Eleven lines, each a trap actually hit. The
   `__init__.py` prohibition is the one that breaks *other* packages if ignored.
2. `_bmad-output/planning-artifacts/prds/prd-py-wordpress-database-2026-09-15/prd.md` —
   `status: final`, reconciled against `945069bf`. **§11 "Shipped state" is the fastest way to
   learn what actually exists.** Superseded requirements keep their text with reasons; items
   marked DEFERRED or PARTIALLY are genuinely not done.
3. `.memlog.md` beside it — 81 entries, the authoritative decision record with reasoning. Go
   here before re-deciding anything.
4. `docs/rewrite-notes.md` (was `CHANGELOG.md`, moved in `731edec`; release notes now come
   from commit messages) — including one change the upstream handoff asked for that was
   rejected with evidence.
5. The family's architecture spine and ADRs live in **`l3io-wordpress-backup`**, not here:
   `_bmad-output/planning-artifacts/architecture/.../ARCHITECTURE-SPINE.md` (29 invariants,
   AD-n) and `docs/adr/`. AD-2, AD-8, AD-9, AD-14, AD-27, AD-28, AD-29 bind this package.

## State

- [done] Rewrite merged to `main`; 15 jobs green on real GitHub Actions (lint/format/types,
  architecture contracts, 9 test legs, build, 3 clean-install legs).
- [done] 90 unit/contract + 13 integration tests; integration verified against MySQL 8.0, 8.4
  and MariaDB 11.4.
- [done] `make ci` replays all five jobs locally under `act`; `make verify-wheel` is the
  fast standalone equivalent.
- [done] PRD reconciled to `final` and addendum corrected.
- [superseded 2026-10-12] **Commit and push three uncommitted tracked changes**: `.github/workflows/ci.yml`
  (a stale comment fix), `pyproject.toml` and `uv.lock` (dependency pin moved from a rev to
  tag `v1.5.0`). All gates pass with them in place; they are simply uncommitted.
- [todo — Shawn's] Delete or deliberately keep the tag **`v1.0`** — a 2018 predecessor tag on
  `6b88f31`, already pushed, and a live match for `publish.yml`'s `v*` trigger.
- [todo — Shawn's] Decide where the architecture record lives: a local doc here, or a pointer from
  `AGENTS.md` to the backup repo's spine. My recommendation was the pointer, on the grounds
  that duplicating 29 invariants across three repos guarantees drift. Not decided.
- [todo — Shawn's] FR-23 — second credential provider. Not implemented; only AWS. Recommendation
  changed from Azure Key Vault to a **dependency-free env-var provider**, which proves the
  interface is not AWS-shaped without adding an SDK.
- [todo — Shawn's] FR-29 — correlation identifier. Not implemented. Either build it or retire it
  deliberately; review argued it adds little for a single-threaded six-statement fan-out, but
  nobody made that call.
- [done 2026-10-12, `0c4e3cf`] FR-48 — no check that `requires-python` and the CI matrices agree. Three hand-kept
  copies of one fact; a global-rule-#4 violation.
- [done 2026-10-12, `57a9c77`] FR-50 — no scripted name-conflict release gate. The release path relies on memory,
  which the requirement forbids.
- [done 2026-10-12, `cc107fb`] FR-45 — no `security-audit` workflow. Nothing scans dependencies or the lock.
- [done 2026-10-12, `bb89bba`] G5 — **no MySQL 9.x test leg**, and 9.x is the generation FR-8/FR-9 exist for, since
  9.0 removed `mysql_native_password`. Cheapest coverage gain available.
- [blocked] **Any PyPI release.** `l3io-wp-config` is tagged, released and mirrored to the
  internal Gitea registry but is **not resolvable from PyPI** — a GitHub Release is not an
  index. Publishing this package while that holds makes
  `pip install l3io-wordpress-database[wpconfig]` unresolvable, reproducing the exact outage this
  rewrite repairs. Family invariant AD-15. Publication goes bottom-up: config, then database,
  then backup.
- [stale — corrected 2026-10-12] Nothing is published anywhere. **False since 2026-09-30:**
  `v0.0.1` (built as `l3io-wp-database`) and `v0.0.2` are GitHub Releases and are on the Gitea
  `liquidlogiclabs` index. Still true: nothing on PyPI or TestPyPI. Original text follows. `publish.yml` is registered and dispatchable but
  has never run; `l3io-wordpress-database` returns 404 from the Gitea index. Release is Shawn's call,
  not an agent's. The first run should target `mirror` — Gitea packages are deletable, PyPI
  burns a filename permanently.

## Corrections the next session inherits — and which I re-tested myself

The peer session asking for this handoff was right that these matter more than the findings,
because you inherit my conclusions without my evidence. Stated precisely:

- [done] **"act switches to a bridge network when services exist, so services resolve by
  service label" — FALSE.** act defaults to `--network host`, so services are on `127.0.0.1`
  and a label fails DNS outright. **I re-tested this myself, both ways**: `DB_HOST=db` fails
  every integration test; leaving it unset passes all of them.
- [done] **`setup-uv@v10` cannot resolve anywhere** — astral-sh publishes no floating major
  past v7; v8/v9/v10 exist only as exact versions. **I verified this myself** with
  `git ls-remote`, and saw the act run fail with `couldn't find remote ref "v10"` before
  pinning `v10.1.0`. Applies to GitHub Actions too, not just act.
- [done 2026-10-12] **MariaDB floor is 10.2, not 10.1** — re-tested against real servers:
  10.1.48 fails 6 of 13 on `ALTER USER` (`ERROR 1064`), 10.2.44 passes all 13, and 10.2 is
  now a CI leg. Original caveat follows. — `CREATE USER IF NOT EXISTS` works on 10.1.48
  but `ALTER USER` fails with `ERROR 1064`, and the sequence needs both. **I did NOT re-test
  this myself.** It came from a feasibility-review subagent, and I propagated it into NFR-4,
  the shared KB note and two peer sessions on that basis. My own integration runs used MariaDB
  11.4, well above either candidate floor, so nothing in this repo's suite exercises 10.1 or
  10.2. **Re-verify before relying on it.**

Others worth knowing, all of which I did confirm directly:

- [done] The PRD's §2 once claimed `ERROR 1064` was reproduced through the code path. It is
  not reachable there — the old driver fails on `caching_sha2_password` first. Corrected.
- [done] My own tests were wrong twice, and the code right: a fresh site reports
  `authentication_failed`, never `database_absent` (the server authenticates before resolving
  the database — family invariant AD-29); and `db_version` 58975 maps to WordPress **6.7**,
  the release that *introduced* the schema, not 6.8 which also reports it.
- [done] My first PRD reconciliation pass was **not uniform** — some sections swept, others
  untouched — which is worse than marking nothing, because a reader who trusts the loud
  markers reads the silent gaps as verified. A rubric review caught it; the second pass fixed
  it. If you reconcile anything here, do it section by section to completion.

## One trap that gets checks deleted rather than fixed

Verifying "no development dependency source leaked into a release" by grepping a wheel's
`METADATA` for a hostname reports a leak on a **completely clean artifact** — `Project-URL`
entries and the README carried in the long description both legitimately contain `github.com`.
Two sessions hit this independently. The check must inspect `Requires-Dist` **lines** for
`git+`, `@ git`, `file://` or `@ http(s)://`. `tools/check_dist_metadata.py` does it that way
and says why in its docstring; do not "simplify" it into a grep.

## Where the durable knowledge lives

Five notes are already in the shared basic-memory KB under `home-lab` — act behaviour, GitHub
Actions versioning and matrix traps, Python toolchain traps (uv/ruff/PEP 420), the Gitea
registry, and MySQL provisioning invariants. Read those rather than rediscovering; this
handoff deliberately does not repeat them.

Credentials: the Gitea publish credential is a username plus the Gitea token, held in
Infisical (project id and environment are recorded in `~/.actrc`'s comments and in the KB note
on the registry). The `PYPI_CUSTOM_USERNAME`/`PASSWORD` pair in Infisical does **not** work
against `git.ravenwolf.org`. No values anywhere in this repo.

## Inferences, marked as such

- My session name `wordpress-database` is **inferred** from the peer naming convention and
  confirmed by the agent listing; the filename follows from it.
- That the architecture record *should* be a pointer rather than a local doc is **my
  recommendation, not a decision**. Shawn has not ruled.
- The claim that FR-29's correlation identifier "adds little" is **a reviewer's argument I
  found persuasive**, not a tested conclusion.

---

## Update — 2026-10-12: rename, BMad 3.2.4, and the hardening brief

### Done since 2026-09-27

- [done] **Repository renamed** on GitHub `ravensorb/py-wordpress-database` →
  `ravensorb/l3io-wordpress-database` (GitHub redirects the old URL), and the local folder to
  `l3io-wordpress-database`. `a62958d` moves the live references: project URLs, the
  `l3io-wordpress-config` uv git source (now `ravensorb/l3io-wordpress-config.git`, still
  `tag = "v0.0.2"`, still commit `1cf1894`), `uv.lock`, act events, BMad `project_name`.
- [done] l3io 3.2.4 was already committed (`d20c419`). `2895ed1` self-installs
  `_bmad/scripts/pm-status.py` 3.4.2, which the module upgrade had left at 3.2.1. All three
  repos now carry the same copy.
- [done] **Verified 2026-10-12 after the rename**, on a fresh `uv sync --locked --all-extras --dev`:
  `pytest` 107 passed, 13 skipped (integration, no `DB_HOST`);
  `../l3io-wordpress-backup/scripts/check-cicd-alignment.py` 3 repos, 0 findings.
- [todo] **Not pushed.** `main` is 3 commits ahead of `origin/main`. Last green GitHub CI:
  `70aa7a0`.

### Known stale in this file and in `AGENTS.md`

- The "commit and push three uncommitted changes … tag `v1.5.0`" item above is superseded:
  the pin is `tag = "v0.0.2"`, committed.
- `AGENTS.md` and the sibling names above still say `l3io-wp-config` / `l3io-wp-backup` and
  "pinned to a git rev". The distributions are `l3io-wordpress-config` /
  `l3io-wordpress-backup`, and the pin is a tag. `AGENTS.md`'s block is managed by
  `bmad-project-context`; refresh it rather than hand-editing inside the markers.

### This session's brief

Shawn's goal: make this package **rock solid and stable**. It is release 2 of 3; config goes
first. Suggested order:

1. `/l3io-doctor`, then reconcile this file against the repo. Everything tagged above
   predates 2026-10-12.
2. Close the open `[todo]` items that are mechanical gaps under the global rules:
   **FR-48** (`requires-python` vs CI matrices, three hand-kept copies), **FR-50** (scripted
   name-conflict release gate), **FR-45** (no dependency/lock audit), and **G5** (no MySQL 9.x
   leg).
3. Re-test the **MariaDB 10.2 floor** before encoding it anywhere; it is still unverified.
4. Decisions that stay Shawn's: FR-23 (second credential provider), FR-29 (correlation id;
   build or retire), the legacy `v1.0` tag, the retired-name `v0.0.1` assets, and the
   architecture-record location.

### Notes for this session

- Secrets: Infisical, project **`home-lab-discovery`**; this machine has a machine identity
  configured and the session is approved to read from it. Pass `--env=prod`; without it
  `infisical secrets get` returns empty with exit 0.
- Legacy PyPI `wpdatabase2` 0.0.15 is ours and still links the old URL, which redirects.
  Its tombstone plan is in
  `../l3io-wordpress-backup/_bmad-output/implementation-artifacts/handoffs/04-legacy-names-and-registrations.md`.
- PyPI trusted publishing binds owner/repo/workflow. `l3io-wordpress-database` does not exist
  on PyPI or TestPyPI (checked 2026-10-12), so register any publisher under the **new** name.

---

## Update — 2026-10-12, later: hardening pass

Commits `0c4e3cf`..`bcdd118` on `main`, **not pushed** (asked, not done). Every gate passes:
`make check` 128 passed / 13 skipped; `make ci-dryrun` resolves every action ref, the four
new security-audit legs included; `security-audit.yml` ran clean under act;
`check-cicd-alignment.py` 3 repos, 0 findings.

- [done] `/l3io-doctor`: PM state tree empty and clean. One Low, on-request finding: no
  agent instruction block for the `claude` runtime (`sync-agent-instructions --check` exit 1).
  Not run; it would write `CLAUDE.md`.
- [done] FR-48, FR-50, FR-45 and G5, plus the MariaDB floor. See State above and the
  memlog entries dated 2026-10-12 for the reasoning behind each choice.
- [done] **Defects found that nothing checked**, all left over from the 3da6f38 rename:
  `make verify-wheel` invoked the retired console script and **failed on `main`**; the
  wpconfig extra's `MissingDependencyError` told users to install `l3io-wp-config`;
  `docs/migration.md` linked the moved `CHANGELOG.md`. `tests/test_declared_facts.py` now
  fails on the first two classes. **Nothing checks Markdown links.**
- [todo] **Push**, then confirm the five-engine matrix on GitHub. The 9.7 and 10.2 legs have
  been verified locally against the same images, but never on a GitHub runner.
- [done] `AGENTS.md` refresh approved and applied: sibling names, rev→tag, and the
  `__init__.py` caveat (now caught in this repo alone). Provenance: 2026-10-12 against
  `6c8c423`.
- [todo — Shawn's] **3.14 support, family-wide.** Config's matrices run 3.11–3.14 but its
  classifiers stop at 3.13, so config's port of the FR-48 check fails until Shawn decides.
  Database runs 3.11–3.13 and agrees with itself.
- [todo — Shawn's] unchanged: FR-23, FR-29, tag `v1.0`, the retired-name `v0.0.1` assets
  (GitHub release and the Gitea `l3io-wp-database` 0.0.1 package), the architecture-record
  location, and any PyPI release. The PyPI block is unchanged: `l3io-wordpress-config`
  still returns 404 from PyPI.
- [inference] The `ubuntu-latest` label moves to Ubuntu 26 from 2026-10-19 (a GitHub
  annotation on every run). The FR-50 gate runs on the runner's `python3` and needs 3.11+
  for `tomllib`; Ubuntu 26's default should satisfy that, but it has not been checked.

The coordination with `wordpress-config` (session `l3io-wordpress-config-8a`): it will port
FR-45 as-is from `cc107fb`, and FR-48 from `0c4e3cf` once the 3.14 question is settled.
