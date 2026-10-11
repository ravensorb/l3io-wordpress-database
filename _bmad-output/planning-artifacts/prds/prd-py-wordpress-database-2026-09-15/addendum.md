# Addendum — depth that belongs downstream

> **Reconciled 2026-09-26.** Sections D and F are now historical: D's decision was made, and
> F's inventory described a frozen surface that no longer exists. They are kept because the
> evaluation and the inventory are the reusable parts. Section H is new.

Technical mechanism, rejected alternatives and options-considered detail. Feeds
`bmad-architecture` and solution design; deliberately kept out of the PRD narrative.

## A. Driver evaluation (feeds NFR-5)

| Package | Version | Released | License | Build toolchain | Python | Notes |
|---|---|---|---|---|---|---|
| PyMySQL | 1.2.0 | 2026-05-19 | MIT | none, pure Python | >=3.9, CPython + PyPy | universal wheel; `[rsa]` extra for `caching_sha2_password` over non-TLS; `[ed25519]` for MariaDB |
| mysql-connector-python | 26.7.0 | 2026-07-29 | GPLv2 + FOSS exception | none (pure-Python wheel alongside C ext) | >=3.10 | Oracle official; calendar versioning (YY.M), not a rewrite from 9.x |
| mysqlclient | 2.3.0 | 2026-09-14 | GPL-2.0-or-later | **yes** on Linux/macOS — only Windows wheels published | >=3.10 | fastest; source build is the install friction to avoid |
| mysql-connector (legacy) | 2.2.9 | 2019-04-01 | — | sdist only | classifiers stop at 3.3 | **currently pinned.** Its own PyPI page: "Deprecated, go for official version" |

Recommendation PyMySQL: MIT avoids GPL entanglement for a library, pure Python means no
compiler, universal wheel means no platform gaps.

## B. Portable user creation (feeds FR-8, FR-9)

```sql
CREATE USER IF NOT EXISTS 'u'@'%' IDENTIFIED BY 'pw';
ALTER USER 'u'@'%' IDENTIFIED BY 'pw';      -- IF NOT EXISTS will not update an existing password
GRANT ALL PRIVILEGES ON `db`.* TO 'u'@'%';  -- no IDENTIFIED BY
FLUSH PRIVILEGES;
```

- `CREATE USER ... IF NOT EXISTS` landed in MySQL **5.7.8**, but was broken until **5.7.12**
  (Bug #78374: produced an error rather than a warning for an existing user).
- GRANT-creates-user was deprecated in **5.7.6** and removed in **8.0** — the source of the
  observed `ERROR 1064`.
- `mysql_native_password`: deprecated 8.0.34, disabled by default 8.4, **removed 9.0**. Do not
  hardcode it.
- MariaDB: default plugin is still `mysql_native_password`; `caching_sha2_password` is not
  supported; `CREATE OR REPLACE USER` is MariaDB-only; floor for `IF NOT EXISTS` alone is
  **10.1** — but **the floor for the full sequence is 10.2**, because `ALTER USER` fails on
  10.1.48 with `ERROR 1064` and the sequence needs both. Deriving a version floor from one
  statement of four is how the wrong number got into NFR-4 in the first place.
  (`IF NOT EXISTS` verified against the 10.1 branch grammar in `sql/sql_yacc.yy`; the commonly cited 10.1.3
  patch level could not be confirmed from an authoritative page).

## C. Version map derivation (feeds FR-18, FR-19)

No authoritative machine-readable `db_version` → release mapping exists:

- `api.wordpress.org/core/version-check/1.7/` contains no `db_version` field.
- The WordPress.org versions page has a "DB Version" column but it is hand-maintained and
  sparsely populated — 7.1 shows 61833 while 7.0, 7.0.1–7.0.4 and 6.9.x are blank.

Derivation that works:

```
https://raw.githubusercontent.com/WordPress/WordPress/<tag>/wp-includes/version.php   -> $wp_db_version
https://api.wordpress.org/core/stable-check/1.0/                                      -> 884 release tags
```

Spot-verified: 4.9 → 38590, 6.8 → 58975, 7.1 → 61833, trunk (7.2-alpha) → 61833. Mapping is
many-to-one, hence FR-19's "highest release whose db_version <= observed". Unverified: how far
back tags carry a parseable `$wp_db_version` (absent from 0.7 onward), so the derivation has a
floor still to establish.

**Settled by the support decision, 2026-09-26.** The floor is a *support* choice rather than a
derivation limit: WordPress **5.0**. Of the 884 releases in the roster, **328 are at or above
5.0 and all 328 parse**, so the shipped map has no gaps in its supported range — 15 distinct
`db_version` values, floor 43764 → 5.0, ceiling 61833 → 7.0. The 1.x series remains
underivable (`$wp_db_version` did not exist), which no longer matters because it is below the
floor. `$wp_db_version` is readable back to 2.0 if the floor is ever lowered.

## D. FR-27 options-considered — the wp-config.php reader

> **RESOLVED — sibling package `l3io-wp-config`, pinned to tag `v1.5.0`.** None of the rows
> below was chosen: the family architecture supplied a fifth option the table did not
> anticipate, in which the reader is a maintained package under the same namespace rather
> than anything absorbed here. One row acquired disqualifying evidence after the table was
> written — `wpconfigger` cannot read `$table_prefix` at all, because its regex is
> `define()`-only, which would have made FR-17 unimplementable. `phply` remains the fallback
> if the sibling is ever abandoned.

| Option | Cost accepted | Rule #1 posture |
|---|---|---|
| Depend on `wpconfigger` 1.0.0 | External dep you don't control; single release, 2022, unmaintained, 2 stars | Compliant — uses a released library |
| Publish your `wpconfigr` 1.4 fork | Maintaining a second published package | Compliant — you own a real library |
| Vendor cariad's 343 lines (MIT) | You own 204 lines of regex PHP extraction forever | **Requires ADR.** Closest to the YAML-parser precedent in your rule |
| Use `phply` 1.2.6 (BSD, 2023-01-06) | A PLY-based parser dep, itself ~3 years stale | Compliant — a real parser, properly delegated |
| Config reading as a pluggable provider | Interface design work | Neutral — orthogonal, and combines with any of the above |

The last option was framed as composing with FR-21's provider interface — **but that interface
was never built** (FR-21/FR-23 are deferred: `WpCredentials` has two factory classmethods, not
a provider abstraction). What shipped achieves the substance without it: config reading lives
behind the `wpconfig` extra, lazy-imported at point of use, so the connection-only core never
parses PHP and the reader remains swappable by replacing one adapter class.

Note on the vendoring option specifically: the existing reader is regex-based, so it does not
handle conditional `define()`s, heredocs, commented-out defines, or `define()` with a computed
value. `$table_prefix` is a variable rather than a `define`, which FR-17 depends on reading —
worth confirming the chosen option can read it at all.

## E. Defect root-cause note (feeds NFR-2)

Three separately observed defects share one cause — `test_config()`'s bare `except Exception`:

1. The context-manager `TypeError` under connector 2.2.9 is swallowed, so the method always
   returns `False`.
2. Authentication failure and unreachable host are indistinguishable from "database absent"
   (made deliberate in commit `bffe225`).
3. `ensure()` therefore always runs the admin path and always raises from its closing
   validation.

Fixing the swallow is the highest-leverage single change in the rewrite.

## F. Frozen-surface inventory (feeds FR-1, FR-6) — HISTORICAL

> **The freeze was dropped; nothing below is preserved.** Kept for two reasons: it records
> what the predecessor's public surface actually was, which no other document does, and the
> feasibility review found this inventory was **incomplete in ten categories** — seven names
> were re-exported at the top level, so `from wpdatabase2 import WpDatabase` worked and sat
> outside the freeze entirely, and both exception constructors rejected the normal `Exception`
> shape. FR-6's compatibility suite would have passed while breaking callers. That is the
> durable lesson: an inventory assembled by hand is the weak point of any freeze.

`ensure(wp_config_filename, credentials, force=False)`

`WpDatabase(wp_config=None, wp_connection=None)` — `.connection`, `.test_config(throw=False)`,
`.does_database_exist()`, `.get_database_version()`,
`.ensure_database_setup(admin_credentials, force=False)`

`WpConnection(db_host, db_name, credentials)` — `.db_host`, `.db_port`, `.db_name`,
`.credentials`, all with setters. Note the host setter re-parses `host:port` and overwrites
the port, so assignment order matters — preserved behaviour, documented in `AGENTS.md`.

`WpCredentials(username=None, password=None, aws_secret_id=None, region=None)` —
`.from_aws_secrets_manager(secret_id, region)`, `.from_username_and_password(username, password)`,
`.username`, `.password`

`Secret(identifier, region=None)` — `.region`, `.as_string`, `.as_dict`

`WpDatabaseVersion(ver)` — `.db_version`, `.wp_version`

Exceptions: `InvalidArgumentsError`, `InvalidDatabaseNameError`, `RegionNotKnownError`

CLI: `python -m wpdatabase2` with the FR-2 flag set.

## G. Market context (feeds section 3's counterweight)

- Nearest maintained competitor: Cyberfusion's `python3-cyberfusion-database-support` 3.6.1
  and `python3-cyberfusion-wordpress-support` 2.10.1, both released 2026-09-15. Actively
  maintained, but Debian/platform-shaped, documented as "Usage: See code," and undiscoverable
  under any "wordpress database" search.
- The whole cariad lineage is delisted or dormant: `wpconfigr` 404 on PyPI, `wpdatabase` 404
  on PyPI (last release 2018-12-11, 1 star), `py-wordpress-backup` last pushed 2022-11-01.
- Managed hosting (Kinsta, WP Engine, Pressable) exposes no seam for this; cPanel UAPI is the
  exception, exposing `Mysql create_database` / `create_user` / `set_privileges_on_database`.
- Unverified: WP Engine and Cloudways provisioning APIs were not reached directly; PyPI no
  longer serves download counts, so real `wpdatabase2` usage could not be quantified.

## H. CI and local-execution mechanism (feeds FR-42..FR-49)

Verified against act 0.2.89 rather than assumed. These are the reasons the workflows look the
way they do.

- **Service containers are on `127.0.0.1` under act too**, not at the service label. act runs
  the job container with `--network host` by default, so a label fails DNS outright. Leaving
  `DB_HOST` unset — letting the workflow's own default apply — is correct in both
  environments.
- **The test matrix collapses to one leg under `vars.LOCAL_ACT`.** act creates every leg's
  service container up front, before any job runs, so nine legs all try to bind host port 3306
  and eight fail with `port is already allocated`. `--concurrent-jobs 1` does not help,
  because allocation precedes execution. Containers that fail to *start* are not removed by
  `--rm` and strand the port until removed by hand.
- **No `include:` block in the matrix.** An include entry whose keys match no existing
  combination *adds* a leg rather than extending one, so collapsing a dimension silently
  manufactured legs with an empty Python value. The engine is an object carrying its own image
  and health probe, which makes that failure unrepresentable.
- **`setup-uv` is pinned to an exact version, `v10.1.0`.** astral-sh publishes no floating
  major past v7, so `setup-uv@v10` resolves nowhere — on GitHub Actions or under act.
- **`verify-install` builds its own wheel** rather than consuming an uploaded artifact. act's
  artifact server rejects `upload-artifact@v7` outright, and `v4` round-trips under act but
  loses Node 20 support on the runner images, so no artifact version can serve a gate required
  in both places. The invariant being protected is "a built artifact installs clean, not the
  working tree" — a freshly built wheel satisfies it identically.
- **Publishing is a separate workflow file**, and act is pinned to `ci.yml`. act has no OIDC
  and ignores `job.permissions`, so an `if:` guard cannot protect a publish job from local
  execution; file separation is the only reliable boundary.
- **`uv build --no-sources` keeps development sources out of dependency metadata** — verified
  on both wheel and sdist — but does **not** strip `[tool.uv.sources]` from the pyproject
  shipped inside the sdist. Inert today because uv honours it only for the project being
  developed and pip ignores it, so the safety rests on installer behaviour rather than a clean
  artifact.
- **Verify that with a `Requires-Dist` line check, never a hostname grep.** `Project-URL`
  entries and the README in the long description legitimately contain `github.com`, so a
  file-wide search reports a leak on a clean artifact — and a check that cries wolf gets
  switched off.
