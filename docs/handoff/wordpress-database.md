# Handoff — wordpress-database

> **Resume line:** You are `wordpress-database`. Read `docs/handoff/wordpress-database.md` in
> this repo, then continue.

Current state as of 2026-10-14. Predecessor material, and this file's earlier history, are
on the `legacy/main` branch and in `git log`; nothing here narrates them.

## What this session owns

This repository only: `l3io-wordpress-database`, second in the `l3io.wp` family. The
siblings belong to other sessions: `wordpress-config` (`l3io-wordpress-config`, release
position 1) and `wordpress-backup` (`l3io-wordpress-backup`, position 3). Do not edit their
repositories; message them.

## Read first

1. `AGENTS.md`: the operating rules. The `__init__.py` prohibition is the one that breaks
   *other* packages if ignored.
2. The spec, `_bmad-output/planning-artifacts/spec/2026-10-12-l3io-wordpress-database-design.md`,
   and the three plans beside it in `plans/`.
3. `docs/adr/`: this package's decisions. The family's rules (AD-n) are in
   `l3io-wordpress-backup`'s architecture spine and are not copied here.

## Current state

- **Branches.** `main` is at `ddd5481` locally; `origin/main` is at `82b322d` (CI run
  `38643008470`, green). Plan 3 is on `feat/plan-3-release`, not merged and not pushed.
  `legacy/main` (local, not pushed) preserves every predecessor file.
- **Versions.** The last tag is `v0.0.2`; an untagged build derives `0.0.3.devN`. The next
  release is **0.1.0**. Tags on GitHub: `v0.0.0` (baseline), `v0.0.1`, `v0.0.2`, `v1.0`.
- **Supported.** Python 3.11–3.14; MySQL 8.0+ and MariaDB 10.2+. CI runs every test leg on
  all four Pythons against MySQL 8.0, 8.4, 9.7 and MariaDB 10.2, 11.4, and the transfer job
  on the same five engines.
- **Gates.** Every requirement has an upper bound; `wpconfig` takes
  `l3io-wordpress-config>=0.1.0,<0.2`, pinned for development to config's tag `v0.1.0`.
  The coverage floor is 87% (89% measured on MySQL 8.4 and MariaDB 11.4). Every verdict
  code is asserted by a test. The built wheel is installed bare and with each extra
  (`tools/verify_extras.sh`). `publish.yml` starts only on `v*.*.*` tags and its notes
  start from the previous release tag. The README's examples and the tree's
  present-tense wording are guarded by `tests/test_readme.py` and
  `tests/test_current_only.py`.
- **Tombstone.** `tombstone/wpdatabase2/` builds `wpdatabase2` 0.0.16: no dependencies, and
  its import raises an error naming `l3io-wordpress-database`.
- **Verified 2026-10-14 on `feat/plan-3-release`:** `make check`; `make verify-wheel` (bare,
  and `aws`, `encryption`, `wpconfig`); `make test-transfer` on all five engines (MySQL 21
  passed; MariaDB 20 passed, 1 MySQL-only skip); integration 40/40 on MySQL 8.4; `make ci`
  6/6 jobs, leaving no root-owned file; `make ci-dryrun`; family CI/CD alignment 0 findings.

## Remote housekeeping (plan 3, Task 13, run 2026-10-15)

1. Done: `legacy/main` is on GitHub.
2. Done: `main` at `1eaefcb` is on GitHub; CI run 38743973051 passed all 32 jobs (four
   Pythons by five engines, five transfer engines, build, four clean installs), with the
   87% coverage floor met on every leg. The security audit passed.
3. Done: `dev-1.0.1` is renamed `legacy/dev-1.0.1`.
4. Done: tag `v1.0` is deleted on GitHub and locally.
5. Done: the GitHub releases `v0.0.1` and `v0.0.2` are deleted; their tags stay. GitHub has
   no release until 0.1.0.
6. **Open (Shawn's):** delete two Gitea packages in the web UI; the agent's Gitea token
   lacks `write:package`, so the API refused both:
   - <https://git.ravenwolf.org/liquidlogiclabs/-/packages/pypi/l3io-wp-database/0.0.1>
   - <https://git.ravenwolf.org/liquidlogiclabs/-/packages/pypi/l3io-wordpress-database/0.0.2>

## Releasing 0.1.0 (Shawn's, in this order — AD-15)

1. `l3io-wordpress-config` reaches PyPI.
2. Here, delete `[tool.uv.sources]` from `pyproject.toml` and relock.
3. Register the PyPI and TestPyPI trusted publishers under `l3io-wordpress-database` for
   `publish.yml`.
4. `make release minor`: dispatches `release.yml`, which tags `v0.1.0`; `publish.yml` then
   builds, smoke-tests, mirrors to Gitea and creates the GitHub release.
5. `gh workflow run publish.yml --ref v0.1.0 -f target=testpypi`, then install from TestPyPI on every
   supported Python.
6. `gh workflow run publish.yml --ref v0.1.0 -f target=pypi`. Both upload jobs refuse
   any ref but a release tag.
7. `uv build tombstone/wpdatabase2 --out-dir /tmp/wpdatabase2-dist`, then
   `uv publish /tmp/wpdatabase2-dist/*` with a PyPI token scoped to `wpdatabase2`.

## Open decisions (Shawn's)

- A second built-in credential source. Recommendation: a dependency-free
  environment-variable source, which shows the interface is not AWS-shaped.
- Whether this repository gets floating `v<major>`/`v<major>.<minor>` tags. The tag
  filter and the notes lower bound are already in place for them.
- A `CLAUDE.md` agent block (`/l3io-doctor` check 24 reports it missing).
- Public visibility of the `liquidlogiclabs` Gitea org.

## Feature: streaming passphrase encryption (0.2.0) — dual backends 2026-10-26

Requested by `l3io-wordpress-backup` so it can supersede ADR-0006 and share one
`age` format (backup AD-26 / AD-21). Upstream `pyrage` declined passphrase
`encrypt_io` (woodruffw/pyrage#172); plan-4’s contribution path is abandoned.

**Decision:** `passphrase=` on `encrypt`/`decrypt`/`dump`/`load` (mutually
exclusive with recipients/identities) streams sole-scrypt age. Backends:

- **binder (preferred):** sibling package `l3io-age-passphrase` (PyO3 / maturin)
- **CLI fallback:** FiloSottile `age` ≥1.3 + `age-plugin-batchpass`, secret on
  `AGE_PASSPHRASE_FD` (never argv)
- Selection: `L3IO_AGE_PASSPHRASE_BACKEND=auto|binder|cli` (default `auto`)

Recipients stay on stock PyPI `pyrage`. Images we own install the binder wheel
and the official age tarball (includes the plugin). See ADR-0003.

**Status:** dual-backend landed; **released as v0.2.0** (2026-10-27 GitHub
Release + Gitea mirror; not PyPI). Binder:
https://github.com/ravensorb/l3io-age-passphrase/releases/tag/v0.1.0.
Dev pin still git-tags the binder; strip before a PyPI publish.

**For backup:** pin `l3io-wordpress-database[encryption]>=0.2.0,<0.3` (or the
v0.2.0 GitHub wheel) and install the binder manylinux wheel in images. Package
root: `encrypt` / `decrypt` / `check_passphrase` / `check_recipients` /
`generate_identity` with `passphrase=`. See ADR-0003 for
`L3IO_AGE_PASSPHRASE_BACKEND`.

## Feature: stored `siteurl` / `home` options (pending) — 2026-10-27

Requested by `l3io-wordpress-backup` (Shawn approved). Backup records the
source site's stored URLs in the archive Manifest (E002-S01-001) and needs
those exact values as the OLD side of `wp search-replace` on relocation
(E007-S01-003). A Dry Run loads no Dump; WP-CLI after a config rewrite returns
NEW values when `WP_HOME` / `WP_SITEURL` constants are set; backup must not
issue SQL itself (ADR-0015).

**Planned API** (sibling of `schema_version`, not fields on `Survey` — survey
is the admin overview; this is a targeted options read for backup/relocation):

```python
@dataclass(frozen=True, slots=True)
class SiteUrls:
    """Values from `{prefix}options`, never constant overrides."""

    siteurl: str | None   # None ⇒ option row absent (table present)
    home: str | None
    options_table_present: bool  # False ⇒ `{prefix}options` missing; both URLs None

def site_urls(
    connection: Connection,
    credentials: CredentialSource,
    table_prefix: str = "wp_",
) -> SiteUrls: ...
```

- Reads `option_name IN ('siteurl','home')` from the quoted `{prefix}options`
  table (same pattern as `_read_schema_version`).
- Distinguishes table absence (`options_table_present=False`) from a missing
  option row (`None` on that field) without raising for either case.
- Privilege / connect failures stay package errors (`AccessDeniedError` /
  `AuthenticationFailedError` / `DatabaseUnreachableError`), as
  `schema_version` does.
- Exported from the package root and `Database.site_urls(...)` on the facade.
- Not on `Survey`: keeps the survey stable and avoids forcing every survey
  caller to care about URL options.

**Status:** planned, not implemented. No urgency — backup Dry Run reports
planned pairs only until this lands; Manifest keys stay empty. Target a
minor after 0.2.0 (likely 0.3.0) or a 0.2.x patch if backup needs it sooner.

## Requests to the family (spec §15)

**`l3io-wordpress-backup`** — ready to consume passphrase streaming from this
package; still not yet delivered on the backup side:
- supersede ADR-0006 with `age` via this package’s `encryption` API (not raw pyrage);
- move ownership of AD-7 and ADR-0003 (credentials to a subprocess) to this package,
  whose mechanism is the pipe option file;
- Story 2.1 calls `dump`;
- Story 2.4's argument-vector and option-file criteria are met here;
- Story 3.4 uses `survey` and `EnsureResult`;
- Story 3.5 uses `ensure` for the staging database, `load(replace=)`, and
  `drop_database` for the database that loses the cutover;
- Story 5.1 composes `CredentialChain`;
- the spine's note that provisioning has exactly one implementation names this
  package and includes destruction;
- the `database` extra re-pins once 0.1.0 is on PyPI;
- the five document defects reported by the config session on 2026-10-12: AD-30 is
  undefined; AD-24 has no carve-out for AD-2; ADR-0007's script name; ADR-0012's
  version premise; ADR-0013's description of `make ci`;
- narrow `publish.yml`'s tag filter to `v*.*.*` and pass `from-tag` to the notes
  builder, as here and in config.

**`l3io-wordpress-config`** — delivered: `v0.1.0` carries the define-parser fix, and this
package pins it. Still open on config's side: reaching PyPI.

## Open deferred minors

- `Finding.fields` is a `MappingProxyType`: `Finding`/`Verdict`/`RefusedError` cannot be
  pickled, deep-copied or hashed. `TransferError` cannot be pickled either; its docstring
  states a caller duty as a guarantee.
- A more specific host account (`'u'@'localhost'`) can shadow `'%'` and break idempotence.
- Role-held admin privileges: grant rows may be invisible (`granted=True` every run);
  `PRIVILEGES_UNVERIFIED` is tested only with a fake cursor.
- Every non-auth connect failure is reported `UNREACHABLE` (TLS, too many connections);
  mid-session preflight errors map to `DatabaseUnreachableError`; `schema_version` maps
  every post-connect error to `AccessDeniedError`.
- `ensure` can leak the admin session when the user name is invalid (validated after the
  preflight); `check_ensure` does not validate `charset`/`collation`.
- `_looks_live` skips a table it cannot read, silently losing `LIVE_WORDPRESS_SITE`.
- `Connection.from_db_host` rejects `host:/path.sock` and `[::1]:3306` (loud, untested).
- An unknown `--log-level` silently becomes INFO.
- `tests/test_facade.py` lists operations by hand.
- Survey: validates the user name after connecting; a non-integer `db_version` raises
  `AccessDeniedError` and aborts survey; `table_count` counts views.
- Observability: a refusal marks the span ERROR while the log says "refused";
  `set_tracer_provider` at test-module import; `except BaseException` labels interrupts
  "failed".
- Transfer tests: the readiness loop falls through silently after 90 tries and hard-codes
  `root`/`root`; no `docker logs` on failure; apt debconf noise.
- `_client`: `option_pipe` leaks its read fd if `os.write` raises; allow-listed value options
  pass in bare form and can swallow the database positional (require `=`); MySQL 5.7-style
  version banners are not recognised; `ClientTool.label` (and `TransferResult.tool`) repeats
  the program name; a refused value stays in traceback frame locals.
- `encryption`: `read_identity` gives misleading messages for SSH keys and passphrase-wrapped
  files and returns only the first identity; recipients are not whitespace-stripped;
  `decrypt` should warn that a `CorruptDumpError` may leave an unauthenticated plaintext
  prefix in the writer; encrypt's caller-I/O `OSError` has `errno` `None`.
- Preflight messages say "the administrator" for dump and load credentials.
- `dump`: the span logs `succeeded` before the flush/fsync that can still fail; a target
  that is an existing directory runs the whole dump and fails at the rename; the directory is
  not fsynced after the rename; stderr is capped before redaction, so a password prefix can
  straddle byte 65536; a text-mode object not derived from `io.TextIOBase` still raises
  `TypeError` on write.
- `load`: `_prepare` checks an early decrypt error only when the head is empty; head-read
  failures omit the path; `_Decrypting.close` leaves a daemon thread holding a stalled caller
  stream after 10 s; `_IterReader` should `cast("B")` non-byte memoryviews.
- `check dump` cannot report a bad recipient or unwritable output (spec §7.3 makes those
  exceptions, not findings); a `recipients=` parameter emitting `MISSING_DEPENDENCY` would
  close it.
- CLI: a persistent stdout flush failure still exits 120 at shutdown; `_emit` is typed `Any`;
  `_restore_structlog` belongs in `conftest.py`.
- Test gaps: `Connection(host="")`, `from_db_host(":3307")`, bool port; `classify()`
  fallback; `_ensure_facts` error translation; `duration_ms` on refused/failed events;
  mutating a caller dict after `Finding` construction; the subprocess scope guard misses
  aliased imports, `os.system`, `posix_spawn` and asyncio; the stream-form dump is compared
  only by INSERT count; the sandbox test never asserts the 10.2 refusal fires first and keys
  on the exact tag; the views test creates no trigger; the truncated-dump test does not
  assert the target stayed empty; login-file controls skip by engine string rather than tool
  family; the memory test is weak; no `BrokenPipeError` passthrough test in `decrypt`; the
  password-option test should also match "passphrase".
- Leftover `# tests/<file>.py` header comments copied from plan briefs.
- `tools/verify_extras.sh`: the aws leg does not exercise the lazy `boto3` import; the
  forbidden-import check matches the module name anywhere in the output rather than only
  the "base install pulled" line.
- `publish.yml`: the `previous` step's comment says the tag is empty on the first release,
  but `v0.0.0` always matches; an empty value should fail or fall back explicitly.
- `'` is refused in user names but not checked in `user_host` or the admin's
  `CURRENT_USER()` (`server.py`).
- The README does not say that MySQL 8.0 and MariaDB 10.2 are refused as
  `END_OF_LIFE_SERVER`; `tests/test_readme.py` does not guard attribute names.

## Cautions

- Never publish: not PyPI, TestPyPI, the Gitea registry or the tombstone. Releases are
  Shawn's. Any remote change is confirmed by Shawn immediately before it runs.
- Never enumerate HTTP methods against a registry to find a delete endpoint.
- Prove every check by planting the failure it exists to catch; a check that has never
  failed proves nothing.
- Under act, services are on `127.0.0.1`, not the service label (act runs `--network host`).
- When pinging a database container for readiness, use `-h127.0.0.1`: over the Unix socket
  the image's temporary setup server answers first.
- Checking a wheel for a leaked development source means reading its `Requires-Dist` lines
  for `git+`, `@ git`, `file://` or `@ http(s)://`. Grepping `METADATA` for a hostname
  reports a leak on a clean artifact (`Project-URL` and the README legitimately contain
  `github.com`); `tools/check_dist_metadata.py` does it correctly.
- Secrets come from Infisical, project `home-lab`, path `/ci/act/l3io-wordpress-database`, `--env=prod` (without it
  `infisical secrets get` returns empty with exit 0). `make ci` needs it; never substitute
  placeholder secrets.
- [inference] `ubuntu-latest` moves to Ubuntu 26 from 2026-10-19. The name-claim gate runs on
  the runner's `python3` and needs 3.11+ for `tomllib`; not yet checked on Ubuntu 26.
