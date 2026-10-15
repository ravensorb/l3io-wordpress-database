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

## Remote housekeeping (plan 3, Task 13 — after the merge, each step confirmed by Shawn)

1. `git push origin legacy/main`
2. `git push origin main`, then watch CI to completion.
3. `gh api -X POST repos/ravensorb/l3io-wordpress-database/branches/dev-1.0.1/rename -f new_name=legacy/dev-1.0.1`
4. Delete tag `v1.0` on GitHub and locally.
5. `gh release delete v0.0.1 --repo ravensorb/l3io-wordpress-database --yes` (the tag stays).
6. Delete the Gitea package `l3io-wp-database` 0.0.1 in org `liquidlogiclabs`.

## Releasing 0.1.0 (Shawn's, in this order — AD-15)

1. `l3io-wordpress-config` reaches PyPI.
2. Here, delete `[tool.uv.sources]` from `pyproject.toml` and relock.
3. Register the PyPI and TestPyPI trusted publishers under `l3io-wordpress-database` for
   `publish.yml`.
4. `make release minor`: dispatches `release.yml`, which tags `v0.1.0`; `publish.yml` then
   builds, smoke-tests, mirrors to Gitea and creates the GitHub release.
5. `gh workflow run publish.yml -f target=testpypi`, then install from TestPyPI on every
   supported Python.
6. `gh workflow run publish.yml -f target=pypi`.
7. `uv build tombstone/wpdatabase2 --out-dir /tmp/wpdatabase2-dist`, then
   `uv publish /tmp/wpdatabase2-dist/*` with a PyPI token scoped to `wpdatabase2`.

## Open decisions (Shawn's)

- A second built-in credential source. Recommendation: a dependency-free
  environment-variable source, which shows the interface is not AWS-shaped.
- Whether this repository gets floating `v<major>`/`v<major>.<minor>` tags. The tag
  filter and the notes lower bound are already in place for them.
- A `CLAUDE.md` agent block (`/l3io-doctor` check 24 reports it missing).
- Public visibility of the `liquidlogiclabs` Gitea org.

## Requests to the family (spec §15)

**`l3io-wordpress-backup`** — not yet delivered:
- supersede ADR-0006 with `age` via `pyrage`;
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
- Secrets come from Infisical, project `home-lab-discovery`, `--env=prod` (without it
  `infisical secrets get` returns empty with exit 0). `make ci` needs it; never substitute
  placeholder secrets.
- [inference] `ubuntu-latest` moves to Ubuntu 26 from 2026-10-19. The name-claim gate runs on
  the runner's `python3` and needs 3.11+ for `tomllib`; not yet checked on Ubuntu 26.
