---
title: l3io-wp-database PRD
status: final
created: 2026-09-15
updated: 2026-09-26
reconciled_against: 945069bf36329315f8c2536c8a272b33e1d6b7af
---

# l3io-wp-database — Product Requirements

> **Reconciled 2026-09-26** against what actually shipped on `main` at `945069bf`.
> This document was drafted before implementation. Requirements that the work
> superseded are marked **SUPERSEDED** and keep their original text, because *why*
> a constraint existed and *why* it was dropped is the most reusable thing here.
> Requirements not implemented are marked **DEFERRED** rather than quietly removed.
> Section 11 records the shipped state with its evidence.

## 1. Intent

`wpdatabase2` exists so that **the database a `wp-config.php` points at actually exists —
idempotently, without the caller writing SQL, and without admin credentials living any
longer than the one operation that needs them.**

The load-bearing design idea is the separation of two credential sets. WordPress's own
credentials live in its config file and are the ones *created and granted*. Separate
administrative credentials arrive from elsewhere, are used *only* to do the creating, and
are then discarded. `ensure()` is the verb; everything else in the package supports it.

That intent is sound and was preserved verbatim. This document specifies a **full rewrite**
that re-expresses it in a modern, supportable, better-designed form.

**The original constraint — "the outward surface does not break" — was dropped mid-project.**
Since no release of the predecessor was ever installable from PyPI, a compatibility promise
protected an audience that could not exist through pip. The package was renamed and
re-namespaced instead: distribution `l3io-wp-database`, importing as `l3io.wp.database`, a
PEP 420 namespace shared with siblings `l3io-wp-config` and `l3io-wp-backup`. Nothing from
the old public surface is preserved and no shim is published.

## 2. Why now

The package is currently **unusable by anyone who finds it**:

- It has been **uninstallable from PyPI for roughly six years**. Every published version pins
  `wpconfigr>=1.0.0,<=2.0.0`, and that distribution no longer exists on PyPI (HTTP 404).
  `pip install wpdatabase2` fails with `ResolutionImpossible`.
- Its headline capability does not work. `WpDatabase.test_config()` **always returns `False`**,
  because `with self._connect(...) as conn` raises
  `TypeError: 'MySQLConnection' object does not support the context manager protocol`
  under the pinned driver, and a bare `except Exception` swallows it. Therefore
  `does_database_exist()` is always `False`, `ensure()` always takes the admin-credential
  path, and its closing validation always raises.
- It cannot talk to a current database server at all. The pinned `mysql-connector` 2.2.9 fails
  against MySQL 8 authentication with
  `NotSupportedError: Authentication plugin 'caching_sha2_password' is not supported`.

**A precision correction to the original draft.** It also claimed the user-creation SQL
(`GRANT ... IDENTIFIED BY`) produces a syntax error "reproduced directly". `ERROR 1064` is
real and verified against MySQL 8 with the `mysql` client — but it is **not reachable through
this code path**, because the connector fails to authenticate before the statement is ever
sent. It is the *next* blocker once the driver is fixed, not a currently observable one. Each
other claim above was reproduced directly.

## 3. The gap this fills

Verified across the mainstream toolchain: **nothing standard creates the MySQL user and its
grants.**

- `wp-cli`'s `wp db create` issues `CREATE DATABASE` and nothing more; the user must already
  exist with rights.
- The official WordPress Docker image states in its own documentation that the database
  "needs to already exist... it will not be created by the `wordpress` container."
- `wp core install` creates *tables* inside an already-existing database.

Everyone fills that hole with a raw SQL snippet, `MYSQL_USER` on the database container, or
Ansible's `community.mysql`.

**Counterweight, recorded deliberately.** That hole is roughly fifteen lines of SQL, and
Ansible already fills it idempotently and is broadly maintained. Demand evidence is thin:
the ancestor package earned one star in eight years, and this one sat uninstallable for six
years without a bug report loud enough to prompt a fix. The defensible value here is
**being maintained, installable and correct** — a bar the incumbents fail — not novel
capability. Scope decisions in this document should be read against that.

## 4. Goals

- **G1** — Re-express the existing intent in a modern, supportable, well-designed package.
- **G2** — ~~Preserve outward backward compatibility against the **documented contract**.~~
  **SUPERSEDED** — clean break instead. The predecessor was never installable, so the
  promise had no beneficiaries. See §1.
- **G3** — Be installable from PyPI with no git dependencies and no broken pins.
- **G4** — Make correctness observable: structured logs and tracing as first-class features.
- **G5** — Support current database servers: MySQL 8.x, MySQL 9.x, MariaDB.
  **MET 2026-10-12 (`bb89bba`)** — `mysql:9.7` added to the CI matrix, with `mariadb:10.2` as
  the NFR-4 floor leg; 9.0.1 and 9.7.2 pass all 13 integration tests locally. Before that:
  **PARTIALLY MET — MySQL 9.x is not tested.** The shipped matrix is `mysql:8.0`, `mysql:8.4`
  and `mariadb:11.4`. This matters more than a missing row: FR-8 and FR-9 exist *because* 9.0
  removed `mysql_native_password`, so the requirement driving the SQL design is the one
  server generation never exercised. Adding a 9.x leg is the single cheapest coverage gain
  available.
- **G6** — Keep the base install dependency-light; integrations are opt-in.

## 5. Non-goals

- Creating WordPress *tables* or running the WordPress installer. `wp core install` owns that.
- Content, data or URL migration. `wp-cli search-replace` owns that.
- Non-MySQL engines. WordPress targets MySQL/MariaDB.
- Replacing Ansible, Terraform or wp-cli for teams already standardized on them.
- Managing WordPress itself — plugins, themes, users, updates.

## 6. Users and usage scenarios

`[ASSUMPTION]` These are drawn from research and the code's shape, **not elicited from you**.
Because this is a developer library rather than an end-user product, this section is
deliberately downscaled — no personas, no narrated journeys. Correct or replace it.

- **S1 — Ephemeral test databases.** A Python test suite provisions a throwaway WordPress
  database per test session and tears it down, wanting an in-process API rather than shelling
  out to `wp-cli`. Research rated this the most plausible demand.
- **S2 — Multi-tenant control plane.** An agency or host provisions one database plus one
  scoped user per tenant from a Python service. The one demonstrated buyer for this shape.
- **S3 — Python-driven provisioning.** An operator running Python automation (not Ansible)
  bootstraps a WordPress instance after writing its config file.
- **S4 — Own infrastructure.** You use it in your own WordPress stacks and want it correct
  and installable rather than patched around.

## 7. Functional requirements

### 7.1 Public contract and compatibility

> **SUPERSEDED IN FULL.** FR-1 to FR-6 all rest on freezing the `wpdatabase2` surface, and
> that constraint was dropped (§1). The original text is kept because the reasoning is the
> reusable part — and because the review round that attacked this section found the freeze
> was already leaking: the driver's exception types escaped three public methods, and FR-6's
> "mechanical enforcement" checked only imports, signatures and flags. What actually shipped
> is in §11.
>
> One substantive change survived the supersession: **FR-5's behaviour correction shipped
> immediately, without the deprecation period it assumed.** `from_username_and_password()`
> now raises `InvalidArgumentsError` on partial input. An *empty* password is still accepted
> — MySQL permits it, and conflating empty with absent is the confusion this rewrite exists
> to remove.

- **FR-1** — The following remain importable at their current paths with their current
  behaviour per the documented contract: `wpdatabase2.ensure`; `WpDatabase`, `WpConnection`,
  `WpCredentials`, `Secret`, `WpDatabaseVersion` from `wpdatabase2.classes`;
  `InvalidArgumentsError`, `InvalidDatabaseNameError`, `RegionNotKnownError` from
  `wpdatabase2.exceptions`.
- **FR-2** — The CLI keeps its current flags and semantics: `--wp-config`, `--admin-username`,
  `--admin-password`, `--admin-credentials-aws-secret-id`, `--admin-credentials-aws-region`,
  `--log-level`, `--version`, and the mutual-exclusion rules between them.
- **FR-3** — **SUPERSEDED — the name is now `l3io-wp-database`.** ~~The PyPI distribution name stays `wpdatabase2`.~~ Verified 2026-09-16 as
  registered to this project (author Shawn Anderson, home page this repo, MIT, 13 releases),
  with no conflicting owner and every PEP 503 normalized neighbour unregistered
  (`wpdatabase`, `wp-database`, `wp-database2`, `wpdatabase-2`, `wordpress-database`,
  `wordpress-db`, `wp-db`, `wpdb`, `python-wpdatabase` all 404). See open question 11 —
  the "2" existed only to avoid colliding with cariad's `wpdatabase`, which is now delisted.
- **FR-4** — Where current *behaviour* contradicts the *documented* contract, the documented
  contract wins and the behaviour is corrected. Tests asserting the old behaviour are
  rewritten. Each such correction is enumerated in the release notes.
- **FR-5** — `WpCredentials.from_username_and_password()` returns `None` on partial input
  today, and its docstring does not promise that. Under FR-4 it raises
  `InvalidArgumentsError` instead. This is a **breaking change to observable behaviour**,
  called out explicitly because two existing tests assert the `None` return.
  `[ASSUMPTION]` Ship it behind a deprecation period rather than immediately — see FR-31.
- **FR-6** — A compatibility test suite asserts the frozen surface: every name in FR-1
  imports, every signature accepts its documented arguments, and the CLI parses every flag
  in FR-2. This suite is the mechanical enforcement of G2, not a prose promise.

### 7.2 Provisioning

- **FR-7** — `ensure()` is idempotent: running it against an already-correct database and
  user succeeds and changes nothing.
- **FR-8** — User creation uses portable SQL valid on MySQL 8.x, 9.x and MariaDB:
  `CREATE USER IF NOT EXISTS`, then `ALTER USER` to set the password (required — `IF NOT
  EXISTS` will not update an existing account's password), then `GRANT` **without**
  `IDENTIFIED BY`, then `FLUSH PRIVILEGES`.
- **FR-9** — The authentication plugin is never hardcoded. `mysql_native_password` is
  deprecated in MySQL 8.0.34, off by default in 8.4 and **removed in 9.0**; the server's own
  default is used, and MariaDB's divergence (no `caching_sha2_password`) is accommodated.
- **FR-10** — Database and user identifiers are validated before reaching SQL, and
  `InvalidDatabaseNameError` is actually raised — closing the gap where it is currently
  defined, exported and documented as raised but never raised. Identifiers that cannot be
  parameterized are quoted and escaped rather than interpolated raw.
- **FR-11** — Admin credentials are used only for the operations that require them and are
  not retained on the instance after `ensure()` completes.
- **FR-12** — `force=True` continues to skip the existence check and re-run setup.
- **FR-13** — Grants are scoped to the target database (`db.*`), never global.

### 7.3 State inspection

- **FR-14** — The existence check distinguishes, as separate outcomes: database present and
  reachable; database absent; authentication failed; host unreachable. The current
  catch-all that reports every failure as "not found" is removed.
- **FR-15** — **RENAMED IN SHIPPING.** The intent held; the names did not survive the clean
  break. `test_config()` → **`inspect()`**, returning the `ConnectionState` enum rather than a
  boolean, because a boolean cannot carry FR-14's six outcomes — the defect this section
  exists to fix. `does_database_exist()` → **`exists()`**, a narrow convenience over
  `inspect()` that no longer aliases a connection test.
- **FR-16** — `ensure()` uses FR-14's distinctions to decide whether to proceed.
  **CORRECTED during implementation — the draft rule was wrong and would have broken the
  primary use case.** It said an authentication failure is "reported rather than treated as a
  reason to create things". But a MySQL server *authenticates before it resolves the
  database*, so before first provisioning the WordPress account does not exist and inspecting
  as that account necessarily fails with 1045 — never 1049. Refusing on that would reject the
  most common real input: a database made by `wp db create` or a container's
  `MYSQL_DATABASE`, with no user yet.
  > Shipped rule: **authentication failure and access-denial are provisionable**; only
  > *unreachable server* and *unobtainable credentials* block, because neither says anything
  > about what exists. The administrator is the authority on existence, never the failed
  > login of the account being provisioned. Recorded upstream as family invariant **AD-29**.
- **FR-17** — **RENAMED IN SHIPPING** — `get_database_version()` →
  **`database_version(table_prefix="wp_")`**. Honours `$table_prefix` instead of hardcoding
  `wp_options`, verified against a real server with a custom prefix.
- **FR-18** — The `db_version` to WordPress-release mapping is **derived from a source of
  truth, never hand-enumerated**. No authoritative machine-readable mapping exists; it is
  derivable from `wp-includes/version.php` at each `WordPress/WordPress` release tag, with
  `api.wordpress.org/core/stable-check/1.0/` as the tag roster.
  **Shipped as assumed** — generated and committed as data, so runtime needs no network;
  regenerate with `uv run python tools/generate_version_map.py`.
  > **The supported floor is WordPress 5.0**, a support decision rather than a limit of the
  > derivation. Of 884 releases in the roster, 328 are at or above 5.0 and **all 328 parse**,
  > so the map has no gaps in its supported range — 15 distinct `db_version` values, floor
  > 43764 → 5.0, ceiling 61833 → 7.0. That choice also retired a real problem: derivation
  > cannot reach the 1.x series at all (`$wp_db_version` did not exist), and the old
  > hand-written map claimed two such entries that are simply unrecoverable.
- **FR-19** — Version lookup resolves to the highest release whose `db_version` is less than
  or equal to the observed value, because the mapping is many-to-one.
- **FR-20** — An unrecognized or newer `db_version` is reported as such, distinguishably from
  "no version found". **RENAMED IN SHIPPING** — `WpDatabaseVersion.wp_version` →
  **`.release`**, with `.is_newer_than_known` and `.is_older_than_supported` making the two
  "unknown" cases distinguishable rather than both collapsing to `None`.

### 7.4 Credential and configuration providers

- **FR-21** — Credential sources are a **pluggable provider interface**. The base install
  carries none of them.
- **FR-22** — AWS Secrets Manager ships as an optional provider behind the `aws` extra;
  `WpCredentials.from_aws_secrets_manager()` works when it is installed, and raises a
  `MissingDependencyError` naming the extra when it is not.
  > **The `Secret` class does not exist.** It was folded into `WpCredentials`, so there is no
  > public AWS client type any more — one fewer thing to keep compatible, and the secret
  > shape is validated at resolve time instead. The original clause promised it would "keep
  > working per FR-1", which is doubly void: FR-1 is superseded and the class is gone.
- **FR-23** — **DEFERRED — NOT IMPLEMENTED.** At least one additional provider is supported
  to prove the interface is not AWS-shaped. `[ASSUMPTION]` Azure Key Vault, per your answer
  naming Azure.
  > Shipped state: `credentials.py` exposes exactly `from_username_and_password` and
  > `from_aws_secrets_manager`. There is no provider *interface* — those are two factory
  > methods on one class — so FR-21's "pluggable provider interface" is aspirational as
  > written and FR-23 has nothing to prove against. The intent-fidelity reviewer's
  > alternative is better than Azure and remains the recommendation: a **dependency-free
  > env-var provider** proves the interface is not AWS-shaped without adding an SDK, and
  > serves scenarios S1 and S3, which Azure does not.
- **FR-24** — Using a provider whose dependency is absent raises an actionable error naming
  the exact extra to install — never a bare `ImportError` or `ModuleNotFoundError`.
- **FR-25** — Provider secrets declare their expected shape. The current undocumented
  contract — AWS secret JSON must contain exactly `username` and `password` — becomes
  explicit and validated, with a clear error when it is not met.
- **FR-26** — Reading `wp-config.php` is itself an optional provider. The connection-only
  core works without it, fixing the current defect where `boto3` and `wpconfigr` are imported
  unconditionally at package level and gate the dependency-free core behind both.
- **FR-27** — **RESOLVED.** The reader is a **sibling package this family owns**:
  `l3io-wp-config`, consumed behind the `wpconfig` extra and pinned to annotated tag
  `v1.5.0`. No parser is hand-rolled here and no ADR is owed, because the escape hatch
  global rule #1 demands was never taken.
  > The original decision was "hard-fork and break the `wpconfigr` dependency", which as
  > written required owning a `wp-config.php` reader — and rule #1 names parsers as
  > almost-always-wrong to hand-roll. That collision was raised at decision time rather than
  > resolved silently, and the three-package family architecture then settled it a better
  > way: the dependency on cariad's abandoned `wpconfigr` *is* broken, but the replacement is
  > a maintained package under the same namespace rather than 204 lines of regex absorbed
  > into this one. The hard-fork intent is satisfied; the rule is honoured rather than
  > escaped.
  >
  > Candidates evaluated and rejected, kept for the record: `wpconfigger` 1.0.0 (PyPI,
  > single release 2022, unmaintained — and verified unable to read `$table_prefix` at all,
  > since its regex is `define()`-only, which would have made FR-17 unimplementable);
  > `wpconfigr` 1.4, an unpublished fork; vendoring cariad's MIT implementation (343 lines,
  > 204 of them regex extraction); `phply` 1.2.6, a real PHP parser, which remains the
  > fallback if the sibling ever goes unmaintained.
  >
  > **Residual constraint, not yet satisfied (AD-15):** `l3io-wp-config` is tagged and
  > released on GitHub and mirrored to the internal Gitea registry, but is **not resolvable
  > from PyPI**. A GitHub Release is not an index. So FR-36's clean-install gate holds only
  > for the base install; `pip install l3io-wp-database[wpconfig]` from PyPI would be
  > unresolvable until the sibling is published there. Publication must go bottom-up:
  > config, then database, then backup.

### 7.5 Observability

- **FR-28** — Operations emit **structured events** via `structlog` carrying the operation,
  target database and outcome. Credentials and secret values are never logged.
  > **Two deviations.** No **timing** field is emitted — the requirement asked for it and it
  > did not ship. And secret *identifiers* deliberately **are** logged and may appear in
  > errors: banning them made an actionable message impossible to write, since "a secret could
  > not be read" without naming which one is not actionable. That asymmetry is pinned by a
  > test so it is not "tidied" in either direction. NFR-1's stricter wording is corrected
  > accordingly.
- **FR-29** — **DEFERRED — NOT IMPLEMENTED.** Every logical operation carries a
  **correlation identifier**, propagated across the calls it fans out into, so one `ensure()`
  is traceable end to end.
  > Verified absent: zero occurrences of `correlation`, `request_id`, `trace_id` or
  > `contextvars` anywhere in `src/` or `tests/`. Nothing threads an id through.
  >
  > In fairness to the decision rather than the requirement: the intent-fidelity review
  > argued this was a different product's requirement here — one `ensure()` fans out to a
  > handful of SQL statements on a single connection in a single thread, so an id adds little
  > that the OTel span and the log event do not already carry. That is an argument for
  > **dropping** it deliberately, which was never done. It is recorded as deferred rather
  > than retired because nobody made that call.
- **FR-30** — **PARTIALLY IMPLEMENTED.** OpenTelemetry tracing is first-class: spans for
  `ensure()` and each database operation it performs, with error status set on failure.
  > Shipped: **exactly one span**, on `ensure()`, carrying `db.name`, `server.address`,
  > `server.port` and the initial/final state. Per-operation spans were not written. Error
  > status does hold, though incidentally rather than by design — OTel sets it on an escaping
  > exception by default. The packaging half of this requirement is genuinely resolved below;
  > the span coverage is not, and the earlier `RESOLVED` marker overstated it.
  **RESOLVED — shipped as a hard dependency, not an extra.** The draft assumed an extra.
  `opentelemetry-api` is ~58KB with one dependency and already ships `NonRecordingSpan` and
  `ProxyTracer`, so hiding it behind an extra would have obliged hand-rolling a no-op shim —
  straight into global rule #1. It is therefore a core dependency, and tracing is genuinely
  first-class rather than conditionally present.

### 7.6 Compatibility, packaging and release

- **FR-31** — ~~Behaviour corrections that break observable behaviour (FR-5) emit a
  deprecation warning for at least one minor release before the change lands.~~
  **SUPERSEDED** — a deprecation window needs users to warn, and no release of the
  predecessor was ever installable. FR-5's correction shipped immediately; every behaviour
  change is enumerated in `CHANGELOG.md` instead.
- **FR-32** — Packaging moves to `pyproject.toml` with PEP 621 metadata, replacing `setup.py`.
- **FR-33** — Dependencies are declared as extras. **Shipped set differs from the draft:**
  core is `PyMySQL[rsa]` + `structlog` + `opentelemetry-api`; extras are **`aws`** and
  **`wpconfig`** only. No `azure` (FR-23 deferred), no `otel` (now core, FR-30), no `all`
  (nothing to aggregate across two extras).
  > Both optional dependencies are *also* listed in the dev dependency group. Not
  > redundancy: `uv run` syncs default groups only and **prunes extras**, so every `uv run`
  > silently uninstalled the `wpconfig` extra and its tests began skipping rather than
  > running — a green suite measuring nothing. Optionality is still enforced where it counts,
  > against the built wheel in an isolated environment (FR-36).
- **FR-34** — The package declares a Python floor and ships type hints with `py.typed`.
  `[ASSUMPTION]` Python 3.11+.
- **FR-35** — The release is versioned **1.0.0**, reflecting a stable, intentional public
  contract rather than the current `0.0.x`. `[ASSUMPTION]`
- **FR-36** — `pip install l3io-wp-database` succeeds from a clean environment with no git
  dependencies. A CI job asserts this against the built artifact, in an isolated environment
  with no local caches or pre-installed dependencies.
  > **Two corrections.** The name was stale — it read `wpdatabase2`. And the per-extra clause
  > **did not ship**: `verify-install` installs the **base wheel only** and asserts the
  > optional dependencies are *absent*, which tests the opposite property. No extra is ever
  > installed in CI, so `pip install l3io-wp-database[aws]` is unverified — and
  > `[wpconfig]` could not pass anyway while the sibling is off-index (see FR-27's residual
  > constraint). **Note the starting point: no release of this package has ever been
  installable.** `pip install --dry-run wpdatabase2` fails with `ResolutionImpossible` after
  walking back through all thirteen published versions, so 1.0.0 will be the first
  installable release and the release notes must say so plainly.
- **FR-50** — **MET 2026-10-12 (`57a9c77`)** — `tools/check_name_claim.py` runs before both
  pypa uploads in `publish.yml`; a test asserts every upload step is gated for its own index.
  Covers PyPI and TestPyPI, canonical and separator-stripped names; the Gitea mirror is out
  of scope (org-namespaced). Previously: **DEFERRED — NOT IMPLEMENTED.** Name conflict verification is a release gate,
  not a one-time check: before publishing, the distribution name is confirmed to resolve to
  this project on PyPI and on the Gitea registry from FR-47, and normalized-name neighbours
  are re-checked. The check is scripted, not performed from memory.
  > `tools/check_dist_metadata.py` exists but answers a different question — whether a
  > development dependency source leaked into published metadata. No scripted name-conflict
  > gate was written. The one-time check was done by hand and recorded in FR-3; the recurring
  > gate this requires does not exist, so the release path currently relies on memory, which
  > is exactly what the requirement forbids.
- **FR-51** — Naming avoids implying endorsement by the WordPress project. The WordPress
  Foundation requires permission to use "WordPress" "as part of any project, product,
  service, domain name, or company name," and asks that "WP" not be used "in any way that
  confuses people." The distribution name uses only the `wp` abbreviation and never claims
  affiliation; "WordPress" appears in prose descriptively. `[ASSUMPTION]` that descriptive
  use is the intended posture — this is a flag for your judgment, not legal advice, and it
  applies to the repository name `py-wordpress-database` more than to the package name.
- **FR-37** — CI runs the test matrix, the architecture contract suite, and lint. It must
  fail when any of them fail, and provisions its environment with `uv` per FR-40. Shipped on
  GitHub Actions; `.circleci/` deleted.
  > The original wording required "the FR-6 compatibility suite", which is superseded along
  > with the freeze. What replaced it is the **architecture contract suite** — AD-27 namespace
  > guards including a two-distribution coexistence test, and AD-28 identifier escaping.
- **FR-38** — Integration tests run against real MySQL and MariaDB in containers, covering
  the auth-plugin and `CREATE USER` divergences in FR-8 and FR-9. **Shipped as 8.0 / 8.4 /
  MariaDB 11.4 — no 9.x leg**, per G5. 9.7 and MariaDB 10.2 added 2026-10-12.
- **FR-39** — `README.md` is corrected. Its install instructions are currently unrunnable and
  its library example (`WpDatabase('path to wp-config.php')`) raises `InvalidArgumentsError`,
  because the constructor requires a `WpConfigFile` instance.
- **FR-40** — Project tooling standardizes on **`uv`**. It manages the development
  environment, dependency resolution, interpreter provisioning for the FR-34 matrix, task
  running, and release via `uv build` / `uv publish`. This retires `build.sh` and
  `publish.sh` — including the `sudo python3 setup.py install` step — and the manual
  venv-plus-pip sequence in CI. `uv` is chosen over Poetry because it is already a hard
  requirement of this repo's tooling, so it adds nothing new to install. Note the repo
  currently uses neither; this is adoption, not migration.
- **FR-41** — A `uv.lock` is committed for reproducible development and CI. It governs
  **development only**: consumers resolve from the published metadata, so the FR-33 extras
  contract and FR-36's clean-environment install are unaffected by it.

### 7.7 CI/CD

House pattern reference: `ravensorb/exchange/owa-exchange-mcp` — the existing uv-based project
whose workflows these requirements conform to rather than reinvent.

- **FR-42** — CI/CD runs on GitHub Actions with `astral-sh/setup-uv` for environment setup,
  `uv sync` with the needed extras, and a Python matrix. `.circleci/config.yml` is deleted.
  > **The SHA-pinning clause did NOT ship.** No action in either workflow is pinned to a
  > commit SHA — all 23 `uses:` lines are tag or branch refs, and
  > `pypa/gh-action-pypi-publish@release/v1` is a *branch*, the weakest form. The house
  > pattern this cites does SHA-pin, so this is a genuine divergence from it, not a
  > reinterpretation.
  >
  > What was learned instead, and is worth more than the clause it displaced:
  > `astral-sh/setup-uv` publishes **no floating major past v7**, so `setup-uv@v10` resolves
  > nowhere — on GitHub Actions or under act. It is pinned to the exact `v10.1.0`. Check with
  > `git ls-remote` rather than shortening a reported version.
- **FR-43** — **Every merge-gating workflow must execute locally under `nektos/act`** against
  the existing `~/.actrc` (catthehacker runner images, `--no-cache-server`,
  `--artifact-server-path`, `--bind`, `--rm`). No gating path may depend on a
  GitHub-hosted-only feature. Where a step genuinely cannot run locally, it is excluded from
  the gating path and the reason is documented in the workflow.
- **FR-44** — Local-versus-CI behavioural differences are expressed through **workflow
  variables** and a committed `.act.vars`, following the existing `vars.PUBLISH` convention —
  not through `if: env.ACT` branching. One code path, different inputs.
- **FR-45** — **PARTIALLY MET; the substantive gap closed 2026-10-12 (`cc107fb`)** —
  `security-audit.yml` runs `uv audit --locked` over the whole lock (runtime, extras, dev
  group) on push, PR, weekly and dispatch. `release.yml` also exists now. Still no separate
  `build-python` workflow. Original assessment: **PARTIALLY MET.** Workflow layout mirrors the house set: `ci` (lint and test),
  `build-python`, `release`, and `security-audit`.
  > Shipped: `ci.yml` and `publish.yml` only. `build` and `verify-install` are *jobs* inside
  > `ci.yml` rather than a separate `build-python` workflow; there is **no `release` workflow**
  > and **no `security-audit` workflow at all**. The last is the substantive gap — nothing
  > scans dependencies or the lock for advisories.
- **FR-46** — The FR-38 database servers run as service containers that work both on GitHub
  runners and under `act`. **Met**, and it was indeed the hardest part — see addendum §H for
  the three act behaviours that had to be discovered to make it work. Covers 8.0 / 8.4 /
  MariaDB 11.4, not 9.x (G5).
- **FR-47** — Release publishes via `uv build` / `uv publish`, using the established
  `PYPI_CUSTOM_URL` and `PYPI_CUSTOM_*` variable and secret names. No release path invokes
  `build.sh` or `publish.sh`, which FR-40 retires.
  > **Trigger corrected — a tag does not publish to PyPI.** The original wording had one tag
  > publishing to both targets. Shipped: a `v*` tag or an explicit `mirror` dispatch publishes
  > to the **Gitea mirror only**, because Gitea packages are deletable; **PyPI requires a
  > deliberate `workflow_dispatch` naming the target**, because PyPI burns a filename
  > permanently and a tag push is too easy to do by accident for an action that cannot be
  > undone. Consistent with open question 10.
  >
  > Not yet exercised: the workflow has never run. Two findings from the sibling package's
  > first tag run apply when it does — `uv publish --check-url` does *not* make a re-publish
  > idempotent (the check URL is the authenticated index and the check does not receive the
  > publish credentials, so it 409s anyway), and a release job must not depend on the mirror
  > job or a mirror problem costs a release.
- **FR-48** — **MET 2026-10-12 (`0c4e3cf`), as a check rather than a derivation** —
  `tests/test_declared_facts.py` fails when any workflow's Python matrix differs from the
  classifiers, or `requires-python`'s floor differs from the lowest classifier. Matrices are
  found by globbing every workflow. Previously: **DEFERRED — NOT IMPLEMENTED.** The supported-Python set is declared **once**
  and derived wherever else it is needed, so `requires-python` and the CI matrix cannot drift
  apart. A check fails when they disagree.
  > No such check exists. `requires-python = ">=3.11"` lives in `pyproject.toml` while
  > `["3.11","3.12","3.13"]` is hardcoded **twice** in `ci.yml` (the `test` and
  > `verify-install` matrices). Three hand-kept copies of one fact.
  >
  > Worth naming as a rule violation rather than an oversight: global rule #4 says derive the
  > scope from the source of truth, never enumerate it by hand. This repo *does* honour that
  > for AD-27 — the namespace guard derives the forbidden set with `find` rather than listing
  > paths — so the capability and the habit both exist here. This one just did not get done.
- **FR-49** — Lint adopts **`ruff`**, replacing `pylint` and the 17KB `.pylintrc` (both
  deleted). `ruff`'s `BLE001` (blind except) is enabled as a CI **error**, which makes NFR-2
  mechanically enforced rather than a prose promise. `AGENTS.md` was refreshed accordingly.
  > Minor divergence: invoked as `uv run ruff check --output-format=github` rather than via
  > `astral-sh/ruff-action`. One fewer pinned action, and the same command runs locally through
  > `make lint`, which is what keeps local and CI from diverging.

## 8. Non-functional requirements

- **NFR-1 — Security.** No credential or secret **value** appears in logs, traces, exception
  messages or repr output. Identifiers reaching SQL are validated, quoted and escaped, and a
  grant target additionally has its `LIKE` wildcards escaped (AD-28). Grants are
  least-privilege and database-scoped.
  > **Corrected: secret *identifiers* are deliberately exempt.** The original also banned
  > them, which the edge-case review showed makes an actionable error impossible to write —
  > "a secret could not be read" without naming which one is not actionable. A test pins the
  > asymmetry in both directions so it is not tidied either way.
- **NFR-2 — Correctness over silence.** No bare `except Exception` that converts a defect
  into a benign-looking result. This single anti-pattern is the root cause of three separate
  observed defects. **Enforced mechanically** by `ruff BLE001` as a CI error per FR-49, not
  by reviewer memory.
- **NFR-3 — Supportability.** A failure states what was attempted, against what target, and
  what to do next. Every error path is reachable in tests.
  > **Unfalsifiable as written** and knowingly left so. "States what to do next" has no
  > mechanical check, and "every error path is reachable in tests" was never measured —
  > coverage is collected in CI but no floor is enforced. What *is* mechanical is narrower and
  > real: distinct CLI exit codes per failure class, a `MissingDependencyError` that names the
  > extra to install, and `ConnectionState` making the six outcomes distinguishable. Treat the
  > prose as intent and those three as the enforcement.
- **NFR-4 — Compatibility matrix.** MySQL 8.x, MySQL 9.x, MariaDB, each exercised in CI.
  **Corrected: the MariaDB floor is 10.2, not 10.1** — re-verified 2026-10-12 against real
  servers: 10.1.48 fails 6 of 13 integration tests on `ALTER USER` (`ERROR 1064`), 10.2.44
  passes all 13. 10.2 is now a CI leg. `CREATE USER ... IF NOT EXISTS` works
  on 10.1.48 but `ALTER USER` fails there with `ERROR 1064`, and the FR-8 sequence needs
  both — the original floor was derived from one statement of four.
  > Shipped CI matrix: `mysql:8.0`, `mysql:8.4`, `mariadb:11.4` × Python 3.11/3.12/3.13.
  > **8.0 is pinned deliberately** as a compatibility row: it is the only server where
  > `mysql_native_password` is still active, so an 8.4-only matrix would never exercise the
  > auth-plugin divergence the matrix exists to catch. Note `mysql:8` now resolves to 8.4.x
  > and `mysql:lts` to 9.7, so the tag must be exact.
- **NFR-5 — Install friction.** Base install requires no compiler and no system libraries.
  **Shipped as `PyMySQL[rsa]`** — the `rsa` extra is required, not optional: the
  `caching_sha2_password` full-auth path over a non-TLS connection needs it, and that path
  lands exactly on first provisioning. Driver is PyMySQL 1.2.0 — MIT, pure Python, universal
  wheel — over
  `mysql-connector-python` 26.7.0 (GPL with FOSS exception) and `mysqlclient` 2.3.0 (builds
  from source on Linux). MySQL 8 `caching_sha2_password` over a non-TLS connection needs
  PyMySQL's `[rsa]` extra; MariaDB's ed25519 plugin needs `[ed25519]`.
- **NFR-6 — Dependency policy.** Every dependency is a maintained, released package. Any
  hand-rolled implementation in a domain your rule #1 names requires an ADR — see FR-27.
- **NFR-7 — Licensing.** The package stays MIT. Any vendored code retains its notice and
  attribution; cariad's implementation is MIT, Copyright (c) 2018 Cariad Eccleston.
- **NFR-8 — Documented contract.** Every public name has a docstring that matches its actual
  behaviour, since this rewrite is defined against the documented contract and a wrong
  docstring is therefore a defect.

## 9. Success metrics and counter-metrics

`[ASSUMPTION]` All of section 9 — you have never stated how success is judged, so this stays
inferred. Reconciled 2026-09-26 for accuracy: the original table named the old distribution,
promised a server generation that is not tested, and measured a frozen surface that no longer
exists.

| Metric | Target | Status | Counter-metric |
|---|---|---|---|
| `pip install l3io-wp-database` works from a clean env | every release, CI-asserted | **base install asserted; extras not** (FR-36) | Not traded for a fatter base install — base stays driver + structlog + otel-api |
| Server matrix green | 8.0, 8.4, MariaDB 11.4 in CI | **met; 9.x absent** (G5) | Not achieved by weakening assertions or skipping tests |
| Docstrings match behaviour | every public name | met — `mypy --strict`, 22 files | Not achieved by deleting docstrings |
| Diagnosable failures | every error path names cause and next step | **unfalsifiable as written** (NFR-3) | Not traded for log volume that buries the signal |
| ~~Frozen surface intact~~ | ~~FR-6 suite green~~ | **retired** — freeze dropped (§7.1) | — |
| Namespace coexistence | siblings importable alongside | met — two-distribution test, AD-27 | Not achieved by testing the source tree instead of the wheel |
| No credential in logs, reprs or argv | mechanically asserted | met — `tests/test_secrets.py` | Not achieved by removing the logging |

## 10. Open questions

Reconciled 2026-09-26. Resolved items keep their number so earlier references still resolve.

1. ~~**FR-27 — the `wp-config.php` reader.**~~ **RESOLVED** — sibling package
   `l3io-wp-config`, pinned to tag `v1.5.0`. See FR-27.
2. ~~**Is OTel mandatory or an extra?**~~ **RESOLVED** — hard dependency. See FR-30.
3. ~~**Python floor.**~~ **RESOLVED** — 3.11+, tested on 3.11/3.12/3.13.
4. ~~**Is MySQL 5.7 truly out?**~~ **RESOLVED** — out. Matrix is 8.0/8.4/MariaDB 11.4.
5. ~~**Deprecation period.**~~ **RESOLVED** — none; clean break. See FR-31.
6. **Does "supportable" include published documentation** beyond a corrected README?
   **STILL OPEN.** `README.md` and `CHANGELOG.md` shipped; no docs site, no API reference.
7. ~~**Second credential provider.**~~ **STILL OPEN, and now a known gap** — FR-23 is
   deferred, not delivered. Recommendation changed from Azure Key Vault to a dependency-free
   env-var provider.
8. **Sections 6 and 9 are inferred.** **STILL OPEN** — usage scenarios and success metrics
   were never corrected by the product owner, so they keep their `[ASSUMPTION]` tags. Nothing
   downstream depends on them, which is why it never blocked.
9. ~~**pylint or ruff?**~~ **RESOLVED** — ruff, with `BLE001` as a CI error, which makes
   NFR-2 mechanical. `AGENTS.md` was refreshed accordingly.
10. ~~**Does the Gitea registry publish on every release or only on tags?**~~ **RESOLVED** —
    the mirror job fires on a `v*` tag or an explicit `mirror` dispatch; **PyPI is never
    tag-triggered** and needs a deliberate dispatch naming the target.
11. ~~**Keep the name `wpdatabase2`, or rename?**~~ **RESOLVED** — renamed to
    `l3io-wp-database`, clean break, no shim.

### New questions this work raised

12. **FR-51 trademark posture — STILL OPEN.** The package name uses only the `wp`
    abbreviation and claims no affiliation, which is low risk. The exposure such as it is
    sits with the **repository** name `py-wordpress-database`. Not legal advice; a decision
    for the owner.
13. **Class naming and CLI flag shape — OPEN.** The `Wp` prefix stutters inside an already
    namespaced package (`l3io.wp.database.WpDatabase`), and the CLI kept the predecessor's
    verbose flags. Both are mechanical to change and nothing depends on the current names,
    since there is no shim.
14. ~~**FR-50's scripted name-conflict gate.**~~ **RESOLVED 2026-10-12** — see FR-50.
15. **AD-15 resolvability — OPEN and gating any PyPI release.** `l3io-wp-config` is tagged,
    released and mirrored, but not on PyPI. Publication must go bottom-up.

## 11. Shipped state

> **Superseded in part, 2026-10-12 (at `13eb4c2`).** This table describes `945069bf`.
> Known to have changed since, each verified on the date above: the distribution is
> **`l3io-wordpress-database`** (renamed `3da6f38`) and the repository
> `ravensorb/l3io-wordpress-database`; the siblings are `l3io-wordpress-config` and
> `l3io-wordpress-backup`. **Releases exist**: `v0.0.1` (built as `l3io-wp-database`) and
> `v0.0.2` are GitHub Releases, and both are on the Gitea `liquidlogiclabs` index, published
> 2026-09-30; neither name is on PyPI or TestPyPI. Servers verified: add MySQL 9.0/9.7 and
> MariaDB 10.2. Tests: 128 unit/contract + 13 integration; `mypy --strict` over 27 files.
> CI: the engine matrix is five engines, plus a `security-audit` workflow. Rows below that
> contradict this note are stale; the rest were not re-checked.

What exists on `main` at `945069bf`, with the evidence. This section is the answer to "does
the spec match the code" — it is deliberately verifiable rather than descriptive.

| | |
|---|---|
| Distribution | `l3io-wp-database` 1.0.0, importing as `l3io.wp.database` |
| Namespace | PEP 420, shared with `l3io-wp-config` and `l3io-wp-backup`; no `__init__.py` above the area package, proven against the built wheel *and* against two real distributions in one interpreter |
| Public surface | 31 exported names; identifier helpers exported for cross-package reuse (family invariant AD-28) |
| Driver | `PyMySQL[rsa]` |
| Servers verified | MySQL 8.0, 8.4, MariaDB 11.4 — 13 integration tests each |
| Tests | 90 unit/contract + 13 integration |
| Gates | `ruff`, `ruff format`, `mypy --strict` (22 files), `uv sync --locked` |
| CI | 15 jobs green on real GitHub Actions; all five jobs also replay locally under `act` |
| Release | **none.** No tag for this version, no GitHub release, no registry upload — `l3io-wp-database` returns 404 from the Gitea index. Note `git tag` does print **`v1.0`**: a 2018 predecessor tag on `6b88f31`, pushed, unrelated to this version — and a live match for `publish.yml`'s `v*` trigger, so worth deleting or keeping deliberately rather than by accident |

**Security-relevant items delivered beyond the original draft**, both found during
implementation and both now family invariants:

- **AD-28** — a database-level `GRANT` matches its target as a `LIKE` pattern, so `_` is a
  wildcard: a grant on `wp_site` also covered `wpXsite`. Verified by reachability against a
  real server. Every underscore-containing WordPress database name over-granted. Fixed by
  escaping the grant pattern only, with a regression test that asserts the neighbour is
  *unreachable* rather than that the SQL looks escaped.
- **AD-29** — the authentication-ordering finding behind FR-16's correction above.

**A requirement received from upstream and rejected with evidence.** Handoff 02 required
removing a "silent privilege escalation" — that when no administrative credentials are
supplied, the code reuses the ordinary database credentials for `CREATE DATABASE` and `GRANT`.
No such path existed here: `ensure_database_setup` took administrative credentials as a
*required* parameter and passed them straight to the connection, and the CLI exited non-zero
when neither source was given. Passing `None` raised `AttributeError`, not a silent downgrade.
The defect was real but in a sibling package (`wpbackup2/classes/wpsite.py:40`); the upstream
session confirmed the misattribution and moved it. Recorded here because a future reader
comparing this PRD against that handoff would otherwise try to "fix" something that was never
broken — and because writing the changelog entry the handoff asked for would have invented
history.

**A gap the draft required and review discipline was silently carrying:** no credential in
log output, and no password in an argument vector. Both are now mechanical —
`tests/test_secrets.py` asserts structlog and stdlib records clean across `inspect()` and a
real `ensure()`, every `repr` clean, the exception raised to callers clean, and that no module
imports `subprocess` (which keeps the argv guarantee true the day something does shell out).
