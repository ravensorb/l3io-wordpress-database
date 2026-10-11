# PRD Quality Review — l3io-wp-database (reconciled, update mode)

Reviewed 2026-09-26 against `main` at `945069bf`, the tree under
`src/l3io/wp/database/`, `pyproject.toml`, `.github/workflows/`, `tests/`, `tools/`,
`CHANGELOG.md` and GitHub Actions run `35176988612`.

Judged as a **record**, not a plan: the bar is accuracy, traceability and honesty about
gaps.

## Overall verdict

Section 11 is the best thing in this document — every claim in it that can be checked from
the repository holds exactly, including the two nobody would expect to (90 + 13 tests, 15
green jobs), and the FR-23 and FR-50 deferral notes are models of how to record a gap
without softening it. But the reconciliation was **not uniform**: sections 1–4, 7.1–7.4, 10
and 11 were swept carefully, while 7.5, 7.6, 7.7 and 9 were largely left alone. The result
is that roughly a dozen unmarked requirements now assert things that are false — four of
them name public methods and classes that do not exist in the shipped surface, and four
more describe CI properties (SHA-pinned actions, a `security-audit` workflow, a
Python-set drift check, a correlation identifier) that were never built. A future reader
who trusts the loud DEFERRED headers will read the silent ones as shipped, which is the
precise failure the markers were added to prevent.

## Decision-readiness — strong

Read as a record, this dimension is about whether a future reader can see *what was
decided and why*, and it delivers. Every supersession states what was given up, not just
what was chosen: §1 and G2 drop the compatibility freeze and name the reason the promise
had no beneficiaries; FR-31 drops the deprecation window and says a window needs users to
warn; FR-30 explains that hiding `opentelemetry-api` behind an extra would have obliged
hand-rolling a no-op shim, straight into global rule #1, and that the ~58KB dependency was
cheaper than the escape hatch. FR-27 is the strongest entry in the document — it records
four rejected candidates with checkable reasons (including the one that acquired
disqualifying evidence *after* the table was written: `wpconfigger`'s regex is
`define()`-only and cannot read `$table_prefix`, which would have made FR-17
unimplementable), names `phply` as the standing fallback, and then refuses to declare
victory, carrying AD-15 forward as a residual constraint that gates any PyPI release.

FR-16's `CORRECTED` block is the model for a reconciled requirement: it states the draft
rule, states that it was *wrong*, explains the mechanism (a MySQL server authenticates
before it resolves a database, so a pre-provisioning inspection as the WordPress account
necessarily fails 1045, never 1049), and names what the wrong rule would have cost — a
refusal on the most common real input. §3's counterweight argues against the product's own
existence ("roughly fifteen lines of SQL", one star in eight years, six years uninstallable
without a bug report loud enough to prompt a fix) and stays in the document. That is nerve.

Open questions 6, 8, 12, 13, 14 and 15 are genuinely open — none has an answer in the next
sentence — and the resolved ones keep their numbers as promised so earlier references still
land.

### Findings
- **low** Frontmatter still says `status: draft` (§ frontmatter) — a document whose whole
  job is now to record shipped, merged, green software is labelled a draft, which is the
  first thing a reader sees. *Fix:* `status: reconciled` (or `shipped`), keeping
  `reconciled_against: 945069bf`.
- **low** FR-48's `[ASSUMPTION]` was never resolved *and* the thing it hedged was never
  built (§7.7) — "`[ASSUMPTION]` that a check is wanted rather than convention alone" reads
  as an open product question, when in fact the decision was taken by default. *Fix:* fold
  it into the FR-48 finding below and record it as declined-by-omission or deferred.

## Substance over theater — strong

There is almost no furniture here. §6 does the unusual and correct thing: it declines to
write personas, says why ("this is a developer library rather than an end-user product"),
tags the whole section `[ASSUMPTION]`, and lists four scenarios each with a one-clause
provenance ("Research rated this the most plausible demand"; "The one demonstrated buyer for
this shape"). §3 is the opposite of innovation theater — it explicitly retires the novelty
claim and substitutes "being maintained, installable and correct — a bar the incumbents
fail", then instructs the reader to judge scope against that.

The NFRs carry product-specific thresholds with the evidence attached, not adjectives.
NFR-4's correction is exemplary: the MariaDB floor moves 10.1 → 10.2 because
`CREATE USER ... IF NOT EXISTS` works on 10.1.48 but `ALTER USER` fails there with
`ERROR 1064`, and "the original floor was derived from one statement of four" — a named
reasoning defect, not a silent edit. The shipped-matrix note then explains why `mysql:8.0`
is pinned deliberately (the only server where `mysql_native_password` is still active, so
an 8.4-only matrix would never exercise the divergence the matrix exists to catch) and
warns that `mysql:8` now resolves to 8.4.x — verified against `ci.yml`, which pins exactly
`mysql:8.0`, `mysql:8.4`, `mariadb:11.4`.

AD-28 and AD-29 in §11 are real findings, not decoration. AD-28 — a database-level `GRANT`
matches its target as a `LIKE` pattern, so a grant on `wp_site` also covered `wpXsite` — is
recorded with the fix scoped correctly (escape the grant pattern *only*) and with the right
kind of test: "asserts the neighbour is *unreachable* rather than that the SQL looks
escaped". `tests/test_identifiers.py` (16 tests) and the reachability leg in
`tests/test_integration.py` bear that out.

FR-33's note on why both optional dependencies are *also* dev dependencies — `uv run` syncs
default groups and prunes extras, so every `uv run` silently uninstalled the `wpconfig`
extra and its tests began skipping, "a green suite measuring nothing" — is exactly the kind
of earned detail that justifies keeping a PRD after shipping. Verified verbatim against the
comment block in `pyproject.toml`.

### Findings
- *(none — the substance bar is met throughout.)*

## Strategic coherence — adequate

The thesis is stated and the document is organised around it: the product's value is
maintenance, installability and correctness rather than capability, and the requirements
that matter most (FR-36's clean-install gate, FR-27's dependency choice, NFR-2's mechanical
BLE001 enforcement) all serve it. The MVP scope kind is coherent — a problem-solving /
platform-hygiene scope, with §5's non-goals drawing the line at `wp core install`,
`search-replace`, non-MySQL engines and Ansible replacement. Nothing in §7 reads as a
capability someone wanted; every FR traces to a defect in §2 or a gap in §3.

Where it weakens is that **§9 was not reconciled at all**, so the metrics no longer
validate the thesis they were written for. Two of five rows are now false on their face,
and two more cite requirements that were superseded. A metrics table that measures the
abandoned freeze is worse than no table, because it is the section a reader would quote to
check whether the thesis was met.

There is a second, more interesting tension that the document handles well: the thesis's
central promise — installable — **is not met**. There is no release, and `[wpconfig]` could
not resolve from PyPI even if there were. Rather than blur this, §11 states "Release:
**none**" and open question 15 makes AD-15 explicitly gating. Coherence survives because
the document is honest that the bet has not yet been collected.

### Findings
- **high** §9 is entirely unreconciled (§9) — row 1 measures `pip install wpdatabase2`, a
  distribution this project no longer publishes; row 2 targets "MySQL 8.x, 9.x, MariaDB in
  CI" when the shipped matrix has no MySQL 9.x leg (verified: run `35176988612` has
  `mysql80`, `mysql84`, `mariadb` only); row 5 is "Frozen surface intact — FR-6 suite green
  on every commit", and both FR-6 and its counter-metric's FR-4 are superseded in full
  alongside the freeze itself. *Fix:* rewrite the table against §11's shipped state —
  clean-install of `l3io-wp-database` asserted by `verify-install`, the 8.0/8.4/11.4 matrix,
  and replace the frozen-surface row with the AD-27 namespace contract and the AD-28
  reachability proof, which are the surface guarantees that actually exist.

## Done-ness clarity — thin

This is where the uneven reconciliation costs the most. §7.1's whole block is marked
SUPERSEDED IN FULL with a preamble that is genuinely informative — it volunteers that the
freeze "was already leaking" (driver exception types escaped three public methods) and that
FR-6's "mechanical enforcement" checked only imports, signatures and flags. §7.2 and §7.3
are mostly accurate: FR-7 idempotence, FR-8's four-statement sequence, FR-10's validation
and `InvalidDatabaseNameError`, FR-11 (verified — `ensure()` takes `admin_credentials` as an
argument and stores nothing; no `self._admin*` attribute exists), FR-12 (`force: bool =
False`), FR-13 and FR-14 all describe what shipped, and FR-14's four distinctions are
delivered by `ConnectionState` with six states.

But **four live, unmarked requirements specify a public API that does not exist**, and an
engineer reading §7 alone would build against names that are not there. The shipped surface
is `inspect() -> ConnectionState`, `exists() -> bool`,
`database_version(table_prefix: str = "wp_") -> WpDatabaseVersion | None`,
`WpDatabaseVersion.release`, `EnsureResult`, `WpConfigSource` — and none of those nouns
appears anywhere in §7. They appear only as a count ("31 exported names") in §11.

The non-functional sections do better on bounds than on accuracy: NFR-1, NFR-2 and NFR-4
give checkable conditions, and NFR-2's "Enforced mechanically by `ruff BLE001` as a CI
error" verifies (`select` includes `BLE`, `ignore = []`, and the `static` job runs
`uv run ruff check --output-format=github .` as a gate). NFR-3's "Every error path is
reachable in tests" is the one adjective-shaped claim with no named check.

### Findings
- **critical** FR-15, FR-17, FR-20 and FR-22 name a public surface that does not exist
  (§7.3, §7.4) — all four are unmarked and read as live-and-delivered. `test_config()` and
  `does_database_exist()` (FR-15) are gone; shipped are `inspect()` and `exists()`.
  `get_database_version()` (FR-17) is `database_version(table_prefix=...)`, and it does not
  itself honour `$table_prefix` — the caller passes it, sourced from
  `WpConfigSource.table_prefix`. `WpDatabaseVersion.wp_version` (FR-20) does not exist; the
  property is `release`, and the "unrecognized or newer" distinction FR-20 asks for is
  actually delivered by `is_newer_than_known` / `is_older_than_supported`, which FR-20 never
  names. `Secret` (FR-22) does not exist at all — the 31 exported names contain no `Secret`,
  and FR-22 additionally promises it "keeps working per FR-1", a requirement superseded in
  full. *Fix:* rewrite all four against the shipped names, or mark them SUPERSEDED with a
  `Shipped surface:` block in the FR-23 style; either way the shipped nouns must appear in
  §7, not only as a count in §11.
- **medium** NFR-3's "Every error path is reachable in tests" (§8) is the one unfalsifiable
  claim in the NFR set — no coverage threshold, no named guard. Coverage *is* collected
  (`--cov=l3io.wp.database --cov-report=term-missing`) but nothing fails on it. *Fix:* state
  the actual posture — coverage reported, not gated — or add the gate.

## Scope honesty — adequate

The two explicit deferrals are exactly right, and the specific question of whether they hide
anything answers cleanly: **they do not.**

**FR-23 does not hide.** The header is `**DEFERRED — NOT IMPLEMENTED.**` *before* the
requirement text, so the reader cannot reach the aspiration without the verdict. The
`Shipped state:` block then names the precise surface — "`credentials.py` exposes exactly
`from_username_and_password` and `from_aws_secrets_manager`" (verified: those are the only
two classmethods) — and volunteers a *worse* fact than the one being reported: "There is no
provider *interface* — those are two factory methods on one class". It then keeps the
recommendation live and improves it (a dependency-free env-var provider over Azure Key
Vault, because it serves S1 and S3 and adds no SDK). Open question 7 restates it as "STILL
OPEN, and now a known gap". Nothing about this reads as done.

**FR-50 does not hide** — it is the most disciplined paragraph in the document. It names the
artifact that *does* exist (`tools/check_dist_metadata.py`; verified, alongside
`generate_version_map.py`, and nothing else in `tools/`), states that it "answers a
different question", and closes by convicting itself: "the release path currently relies on
memory, which is exactly what the requirement forbids." Open question 14 repeats it.

The problem is not either marker. It is the **contrast**. FR-29, FR-42, FR-45 and FR-48 are
not-delivered to the same degree and carry no marker at all, so a reader who has learned
that this document flags its gaps loudly will read silence as delivery. Uneven marking is
more dangerous than uniform silence.

### Findings
- **critical** FR-29 was never implemented and is unmarked (§7.5) — "Every logical operation
  carries a **correlation identifier**, propagated across the calls it fans out into, so one
  `ensure()` is traceable end to end." A case-insensitive search for
  `correlation|request_id|trace_id|contextvars|bind_contextvars` across `src/` and `tests/`
  returns **zero hits**. The three `_log.info` calls in `database.py` bind
  `database`/`state`/`actions` and nothing that correlates them. This is the one silent
  non-delivery that a reader would have no way to detect, because unlike FR-42 or FR-45 it
  leaves no trace in a file they would open. *Fix:* mark DEFERRED in the FR-23 style, and
  note what partially substitutes — a single OTel span per `ensure()` gives trace-context
  correlation to a collector, but nothing binds it into the structlog events.
- **critical** FR-42's SHA-pinning claim is false and unmarked (§7.7) — "third-party actions
  pinned to a full commit SHA with a trailing version comment". **No action in either
  workflow is SHA-pinned.** All 23 `uses:` lines are tag or branch refs:
  `actions/checkout@v7`, `astral-sh/setup-uv@v10.1.0`, `actions/upload-artifact@v7`,
  `actions/download-artifact@v8`, `pypa/gh-action-pypi-publish@release/v1`,
  `LiquidLogicLabs/git-action-tag-validate-version@v2`. `@release/v1` is a *branch*, the
  weakest form available. This is a supply-chain property a future reader would rely on
  without rechecking. *Fix:* mark it DEFERRED with the mutable refs enumerated, or pin them.
- **high** FR-45's workflow layout did not ship and is unmarked (§7.7) — it requires `ci`,
  `build-python`, `release` and `security-audit`. Shipped: `ci.yml` and `publish.yml` only.
  There is **no `security-audit` workflow at all**, so nothing in the gating path performs a
  dependency or supply-chain audit. *Fix:* record the actual two-file layout with the reason
  (addendum H's file-separation argument for publishing is good and belongs here), and mark
  `security-audit` as a named, outstanding gap.
- **high** FR-48's drift check does not exist and is unmarked (§7.7) — "The supported-Python
  set is declared **once** and derived wherever else it is needed... A check fails when they
  disagree." In fact `requires-python = ">=3.11"` lives in `pyproject.toml` while
  `["3.11","3.12","3.13"]` is hardcoded **twice** in `ci.yml` (the `test` and
  `verify-install` matrices), and no check anywhere compares them — the only occurrence of
  the string outside `pyproject.toml` is inside a stub-package fixture in
  `tests/test_architecture.py:129`. This is a global-rule-#4 requirement (derive the scope,
  never hand-enumerate it) that silently did not ship, and it is worth noting that the
  repository *did* honour that rule elsewhere, deliberately and well: the AD-27 contract job
  derives the forbidden `__init__.py` set with `find src/l3io -maxdepth 2` rather than
  trusting the test. *Fix:* mark DEFERRED, and note that the identical rule was satisfied for
  AD-27 so the omission is inconsistency, not disagreement.
- **high** FR-21 reads as delivered and is contradicted only inside FR-23's note (§7.4) —
  "Credential sources are a **pluggable provider interface**." There is no interface; there
  are two classmethods on one class. FR-23 admits this, but a reader extracting FR-21 alone
  gets the wrong answer, and FR-21 is the requirement the addendum's §D still composes
  against. *Fix:* mark FR-21 CORRECTED in place — the base install carrying no provider is
  true and shipped; the interface is not.
- **high** G5, FR-38 and §9 still promise MySQL 9.x (§4, §7.6, §9) — open question 4 records
  "**RESOLVED** — out. Matrix is 8.0/8.4/MariaDB 11.4", NFR-4 and §11 record the same, but
  G5 still reads "Support current database servers: MySQL 8.x, **MySQL 9.x**, MariaDB" and
  FR-38 still requires integration tests "against real MySQL 8.x, **MySQL 9.x** and
  MariaDB". Verified: the 15-job run contains no 9.x leg. The consequence is substantive, not
  cosmetic — FR-8's portable-SQL sequence and FR-9's auth-plugin handling were written
  *specifically* for the 9.0 removal of `mysql_native_password`, and that claim is now
  untested. *Fix:* strike 9.x from G5 and FR-38, and say plainly in FR-9 that the 9.0
  behaviour is reasoned from documentation rather than exercised.
- **high** FR-36 names the wrong distribution and overstates its gate (§7.6) — it still says
  "`pip install wpdatabase2` succeeds" and claims a CI job asserts clean install "separately
  for each declared extra from FR-33". The `verify-install` job installs the **base wheel
  only** into an isolated environment and then asserts the optional dependencies are
  *absent* (`boto3`, `botocore`, `l3io.wp.config`) — a correct and valuable check, but the
  opposite of what FR-36 claims. Neither `[aws]` nor `[wpconfig]` is ever installed from the
  wheel, and per FR-27's own residual note `[wpconfig]` could not resolve from PyPI if it
  were. *Fix:* correct the distribution name, restate the gate as what it is (base install
  clean, optional deps proven absent), and record the per-extra install as unbuilt and
  currently blocked on AD-15.
- **high** FR-30's `RESOLVED` marker answers only half the requirement (§7.5) — the note
  resolves the packaging question (hard dependency, not an extra) so confidently that the
  rest of the FR reads as delivered too. The FR asks for "spans for `ensure()` **and each
  database operation it performs**". There is exactly **one** `start_as_current_span` in the
  entire source tree, on `ensure()`; `inspect()`, `exists()`, `database_version()` and the
  individual statements inside `_provision()` get none. The "error status set on failure"
  clause *does* hold, but incidentally — via OTel's default `set_status_on_exception` on the
  context manager, not by any explicit `set_status` or `record_exception` call (neither
  appears anywhere). This is the one place a marker genuinely does soften a gap. *Fix:* split
  the note — `RESOLVED` for the dependency decision, `PARTIAL` for span coverage, with the
  single-span reality stated.
- **medium** FR-28's "timing" did not ship (§7.5) — the three log events carry operation,
  database, outcome and actions, but no duration or elapsed field. structlog's default
  timestamper stamps the *event*, which is not operation timing. *Fix:* drop "and timing", or
  record it as outstanding.

## Downstream usability — thin

As a record this dimension matters less than for a plan, but it is not moot: the document is
the intended source for `bmad-architecture` and for the two sibling packages that share
family invariants AD-27, AD-28 and AD-29, and those siblings will source-extract from it.

Extraction is currently unsafe in a specific way: **the shipped vocabulary exists nowhere in
§7.** `inspect()`, `exists()`, `ConnectionState`, `EnsureResult`, `WpConfigSource`,
`ResolvedCredentials`, `release_for`, `quote_grant_database`, `SUPPORTED_FROM` — the nouns
another package would need — appear only as "31 exported names" in §11. Meanwhile §7 hands
the extractor `test_config()`, `does_database_exist()`, `get_database_version()`,
`wp_version` and `Secret`, none of which exist.

Cross-references mostly survived the edits, with two that did not. There is no Glossary and
no Assumptions Index despite eleven inline `[ASSUMPTION]` tags, so the roundtrip the rubric
asks for cannot be performed at all. Each section does read standalone, which is real: §11
is self-contained and the addendum is properly partitioned by which FR each part feeds.

### Findings
- **medium** FR-37 (live) requires a superseded requirement's artifact (§7.6) — "CI runs the
  test matrix, **the FR-6 compatibility suite**, and lint." FR-6 is superseded in full and no
  compatibility suite exists; the shipped equivalents are the `contracts` job
  (`tests/test_architecture.py`, 13 tests, plus the derived `find` scope guard) and
  `verify-install`. A live requirement whose content is a dead requirement is the worst kind
  of dangling reference, because it resolves to text that *looks* authoritative. *Fix:* point
  FR-37 at the contracts job and `verify-install` by name.
- **medium** FR-50 cites superseded FR-3 as the standing record (§7.6) — "The one-time check
  was done by hand and recorded in FR-3." FR-3 sits inside the SUPERSEDED-IN-FULL block and
  records the availability of **`wpdatabase2`**, not `l3io-wp-database`. So FR-50 pulls a
  superseded fact forward as live evidence, and the evidence is about the wrong name. *Fix:*
  state that no name check has been performed for `l3io-wp-database` on either index — which,
  read with FR-50's own deferral, is the actual position.
- **medium** No Glossary and no Assumptions Index (§ whole document) — eleven `[ASSUMPTION]`
  tags, none indexed, so there is no way to audit which survived reconciliation. Five sit on
  matters §10 records as RESOLVED: FR-5's deprecation-period assumption (OQ5 — resolved,
  none), FR-34's "Python 3.11+" (OQ3 — resolved), FR-35's 1.0.0 (shipped, verified in
  `_version.py`), FR-37's GitHub Actions (shipped), FR-49's ruff (OQ9 — resolved). An
  `[ASSUMPTION]` on a settled fact invites re-litigation and makes the record look less
  settled than it is. *Fix:* add a short index; retire the five resolved tags, keeping only
  §6, §9, FR-23's Azure recommendation, FR-48 and FR-51.
- **low** FR-5's inline pointer to FR-31 (§7.1) — "`[ASSUMPTION]` Ship it behind a
  deprecation period rather than immediately — see FR-31" points at struck-through text. This
  one *works*, but only because §7.1's preamble says explicitly that FR-5's correction shipped
  immediately without the deprecation period, and because FR-31 carries its own reason. The
  inline pointer alone would mislead. FR-6→G2 is fine for the same reason, and FR-26→FR-27
  resolves cleanly to live, RESOLVED text. *Fix:* optional — append "(superseded; see the
  §7.1 preamble)" to the pointer.
- **low** FR-50 and FR-51 are out of numeric order (§7.6) — they sit between FR-36 and FR-37,
  so the definition order runs …35, 36, **50, 51**, 37, 38…. All 51 IDs are present exactly
  once, with no gaps or duplicates, so this is ordering only. *Fix:* move them to the end of
  §7.6 or renumber.

## Shape fit — strong

The shape is right and was chosen, not defaulted into. This is an internal, single-operator
developer library, and the PRD is a capability spec: no user journeys, no protagonists, §6
explicitly downscaled with its reasoning stated, §9 operational rather than user-facing. The
rubric's brownfield criterion — existing-code references must be accurate, and new work
distinguished from existing — is where a reconciled PRD lives or dies, and §2's handling is
exactly right: it reproduces three defects directly and then *withdraws* the fourth claim,
stating that `ERROR 1064` is real against MySQL 8 with the `mysql` client but "**not
reachable through this code path**" because the connector fails to authenticate first, so it
is "the *next* blocker once the driver is fixed, not a currently observable one". Correcting a
defect claim *downward* is rare and is the single clearest signal that this document was
reconciled honestly rather than dressed up.

Adding §11 is the right structural move for update mode, and putting mechanism in the
addendum keeps §7 readable. The chain-top burden is light here — nothing downstream depends
on §6 or §9, which open question 8 says plainly.

### Findings
- **low** §1's opening sentence is present-tense about the old package (§1) —
  "`wpdatabase2` exists so that…". The paragraph is doing legitimate work (it preserves the
  inherited intent verbatim, which §1 then says was "preserved verbatim"), but the reader
  meets a superseded name in the present tense before the rename is explained three
  paragraphs later. *Fix:* "`wpdatabase2` **existed** so that…", or lead with the inherited
  intent labelled as inherited.

## Is section 11 verifiable? — yes, and every spot-check held

This was checked claim by claim against the repository. Nothing in §11 failed.

| §11 claim | Verified | How |
|---|---|---|
| `l3io-wp-database` 1.0.0, imports as `l3io.wp.database` | ✅ | `pyproject.toml` name/version; `_version.py` `__version__ = "1.0.0"` |
| PEP 420, no `__init__.py` above the area package, proven against the wheel *and* two real distributions in one interpreter | ✅ | `tests/test_architecture.py::test_built_wheel_has_no_namespace_init` and `::test_namespace_coexists_with_a_sibling_distribution`, plus the `contracts` job's derived `find src/l3io -maxdepth 2` scope guard |
| 31 exported names | ✅ | `__all__` in `__init__.py` — exactly 31 |
| `PyMySQL[rsa]` | ✅ | `dependencies = ["PyMySQL[rsa]>=1.2.0", …]` |
| MySQL 8.0, 8.4, MariaDB 11.4 — 13 integration tests each | ✅ | `ci.yml` engine matrix pins those three images; `tests/test_integration.py` collects 13 |
| 90 unit/contract + 13 integration | ✅ | `uv run pytest --collect-only -q` → 103 total, `test_integration.py: 13`, remainder 90 |
| `ruff`, `ruff format`, `mypy --strict` (**22 files**), `uv sync --locked` | ✅ | `static` job runs all three; `uv run mypy --strict` → "Success: no issues found in **22** source files" |
| **15 jobs** green on real GitHub Actions | ✅ | run `35176988612` (`Trigger CI on main only`, the reconciliation commit) — 15 jobs, all `success` |
| all **five** jobs also replay locally under `act` | ⚠️ not independently checkable | `ci.yml` defines exactly five jobs (`static`, `contracts`, `test`, `build`, `verify-install`), so 15 = 1+1+9+1+3 is internally consistent; the `act` replay itself rests on `Makefile`'s `ci` target, `.act.vars` and addendum H rather than on a repo artifact |
| Release: **none** — no tag, no GitHub release, no registry upload | ✅ | `CHANGELOG.md` heads "## 1.0.0 — **unreleased**"; no `v1.0.0` tag exists |

### Findings
- **low** "no tag for this version" is true but will look wrong to anyone who checks
  (§11) — `git tag` prints **`v1.0`**, which resolves to commit `6b88f31` dated
  **2018-12-05** ("Update documentation") and is an ancestor of HEAD. It is a predecessor tag,
  not this release, so the claim stands — but a reader verifying it sees a tag and stops.
  *Fix:* "no `v1.0.0` tag (the repository's only tag, `v1.0`, is a 2018 predecessor tag)".
- **low** NFR-5 states a pin the package does not make (§8) — "Driver is PyMySQL 1.2.0";
  `pyproject.toml` declares `PyMySQL[rsa]>=1.2.0`. The evaluation behind the choice is sound
  and the `[rsa]` reasoning verifies. *Fix:* ">=1.2.0 (evaluated at 1.2.0)".

## Does the addendum contradict the PRD? — in three places, plus one where the addendum is right and the code is wrong

Sections D and F are correctly marked historical and earn their keep — F's confession is the
most valuable paragraph in the addendum ("this inventory was **incomplete in ten
categories**… FR-6's compatibility suite would have passed while breaking callers. That is
the durable lesson: an inventory assembled by hand is the weak point of any freeze"), which
is the same lesson global rule #4 encodes. Sections A, E, G and H are consistent with the
PRD, and H is verified against act 0.2.89 rather than assumed. But three bodies were not
reconciled to match headers or to match §7's resolutions.

### Findings
- **medium** Addendum §C still records the derivation floor as unestablished (addendum §C) —
  "Unverified: how far back tags carry a parseable `$wp_db_version`… so the derivation has a
  floor still to establish." FR-18 settled exactly this: floor **WordPress 5.0**, 328 of 884
  releases at or above it, **all 328 parse**, 15 distinct `db_version` values, 43764 → 5.0
  through 61833 → 7.0, and the 1.x series is unrecoverable because `$wp_db_version` did not
  exist. §C now reads as an open gap that is closed, and it is the section a reader goes to
  for the derivation. *Fix:* add a resolved note pointing at FR-18 and `SUPPORTED_FROM`.
- **medium** Addendum §D still composes against an interface that does not exist (addendum
  §D) — the "Config reading as a pluggable provider" row and the closing paragraph both build
  on "FR-21's provider interface", which shipped as two classmethods. §D's header was
  reconciled; its body was not. *Fix:* one clause noting FR-21's interface is aspirational,
  cross-referencing FR-23's shipped-state block.
- **low** Addendum §B never records NFR-4's corrected floor (addendum §B) — it says the
  MariaDB floor for `IF NOT EXISTS` is **10.1**, which is not strictly contradicted (NFR-4's
  correction to **10.2** turns on `ALTER USER` failing at 10.1, not on `IF NOT EXISTS`), but
  §B is the section that carries the SQL sequence *and* the floor, so a reader lands on 10.1
  and never sees the correction. *Fix:* append the `ALTER USER` evidence and the 10.2 floor.
- **medium** `.github/workflows/ci.yml` contradicts the addendum, `.act.vars` and
  `AGENTS.md` — and here the **documents are right and the code comment is wrong**. Addendum
  §H: "Service containers are on `127.0.0.1` under act too, not at the service label. act
  runs the job container with `--network host` by default, so a label fails DNS outright.
  Leaving `DB_HOST` unset… is correct in both environments." `.act.vars` agrees at length and
  deliberately does **not** set `DB_HOST`; `AGENTS.md` agrees. But the inline comment above
  the `test` job's `env:` block asserts the opposite: "act runs the job in a container, so
  they resolve by service label. **`.act.vars` sets `DB_HOST=db`.**" It does not. The
  workflow's actual expression, `DB_HOST: ${{ vars.DB_HOST || '127.0.0.1' }}`, behaves per
  the addendum. This is reported here because it is precisely the class of defect global rule
  #3 was written about — a stale comment that reads as authoritative and would send the next
  reader to set `DB_HOST=db` and break local runs. *Fix:* replace that comment with §H's
  text; nothing in the PRD or addendum needs to change.

## Mechanical notes

- **ID continuity** — all 51 FR IDs present, each exactly once, no gaps and no duplicates.
  Ordering is non-monotonic: FR-50 and FR-51 sit between FR-36 and FR-37. NFR-1 through NFR-8
  contiguous. §10's open questions 1–15 contiguous, and resolved items keep their numbers as
  the section promises.
- **Broken or misleading cross-references** — FR-37 → FR-6 (superseded; no such suite
  exists) and §9 → FR-6 / FR-4 (both superseded, freeze abandoned) are the two that
  genuinely break. FR-50 → FR-3 resolves but cites superseded text under the old
  distribution name. FR-5 → FR-31 and FR-6 → G2 point at struck text but are rescued by the
  §7.1 preamble. FR-26 → FR-27, FR-33 → FR-23/FR-30/FR-36, NFR-2 → FR-49, FR-46 → FR-38/FR-43
  and FR-50 → FR-47 all resolve to live text and are accurate.
- **Assumptions Index roundtrip** — cannot be performed: eleven inline `[ASSUMPTION]` tags
  (§6, FR-5, FR-23, FR-34, FR-35, FR-51, FR-37, FR-48, FR-49, §9, and OQ8's reference) and no
  index. Five sit on matters §10 records as RESOLVED.
- **Glossary** — absent. Terminology is nonetheless consistent in the places it matters:
  `ensure()`, admin vs WordPress credentials, `db_version`, "provisionable", AD-15/AD-27/
  AD-28/AD-29 are used identically throughout, and the family-invariant AD-numbers are the de
  facto shared vocabulary with the siblings. The drift that exists is not synonym drift but
  **generational** drift — §7 uses the predecessor's method names while §11 uses the shipped
  ones.
- **Stale distribution name** — `wpdatabase2` appears as a live present-tense subject in
  FR-3 (covered by the SUPERSEDED block), FR-36 twice, §9 row 1, and §1's opening sentence.
  FR-36 and §9 are the two that are not covered by any marker.
- **UJ protagonists** — not applicable; no UJs, deliberately, per §6. Correct for the shape.
- **Required sections** — all present for this shape, and §11 is a well-judged addition that
  the template did not require.
- **`pyproject.toml` cross-check** — every FR-33 and NFR-5 claim about the shipped dependency
  set verified exactly: core `PyMySQL[rsa]>=1.2.0` + `structlog>=26.1.0` +
  `opentelemetry-api>=1.30`; extras `aws` and `wpconfig` only, no `azure`, no `otel`, no
  `all`; both optional dependencies also in the `dev` group with the `uv run`-prunes-extras
  reason recorded in a comment; `l3io-wp-config` pinned to annotated tag `v1.5.0` under
  `[tool.uv.sources]` with the must-not-reach-a-release warning attached. One drafting note
  for the project rather than the PRD: `AGENTS.md` still says the sibling "is pinned to a git
  **rev**", where `pyproject.toml` now pins a **tag** — and the pyproject comment explains at
  length why the tag was chosen over a rev.

## Severity tally

| Severity | Count |
|---|---|
| critical | 3 |
| high | 7 |
| medium | 7 |
| low | 7 |
| **total** | **24** |
