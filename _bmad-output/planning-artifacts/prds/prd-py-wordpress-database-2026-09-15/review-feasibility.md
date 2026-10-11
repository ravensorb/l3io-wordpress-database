---
title: Technical feasibility review — py-wordpress-database PRD
date: 2026-09-16
reviewer: technical feasibility pass (adversarial; claims verified, not taken on trust)
subject: prd.md + addendum.md @ 2026-09-16
verdict: FEASIBLE — build it. Two claims are WRONG, one inventory is INCOMPLETE.
---

# Technical feasibility review

## Method

Every technical assertion below was checked against a primary source: real database
servers in Docker (MySQL 8.0.46, 8.4.11, 9.7.2, MariaDB 10.0.38, 10.1.48, 11.4.13,
13.0.2), the live PyPI and WordPress.org APIs, `raw.githubusercontent.com` at 884
WordPress tags, and runtime introspection of the package itself. Commands and outputs
are quoted inline. Where I could not establish a claim, it is marked UNVERIFIABLE
rather than assumed.

**Overall: the PRD is unusually well-grounded.** Its two headline diagnoses (uninstallable
from PyPI; `test_config()` always `False`) both reproduce. The rewrite it specifies is
achievable with the stack it names. The problems are narrow: one wrong version floor, one
wrong driver license, an incomplete frozen-surface inventory, and two `[ASSUMPTION]`s that
the evidence argues against.

---

## Summary table

| Item | Verdict |
|---|---|
| FR-1..FR-6 frozen surface (addendum F) | **INCOMPLETE** — 13 categories of public surface missing |
| FR-8 portable SQL sequence | **VERIFIED** on 8.0 / 8.4 / 9.7 / MariaDB 11.4 + 13.0 |
| FR-8 "`ALTER USER` required" | **VERIFIED** by login test on all four servers |
| FR-9 `mysql_native_password` removed in 9.0 | **VERIFIED** — absent from 9.7.2 |
| FR-9 off by default in 8.4 | **VERIFIED** — `DISABLED` on 8.4.11 |
| FR-9 deprecated in 8.0.34 | **VERIFIED** — 8.0.34 release notes |
| FR-9 MariaDB has no `caching_sha2_password` | **VERIFIED** |
| NFR-4 MariaDB floor 10.1 | **WRONG** — real floor for the FR-8 sequence is **10.2** |
| NFR-5 PyMySQL viable for MySQL 9 + MariaDB | **VERIFIED** — right driver, but declare `PyMySQL[rsa]` |
| NFR-5 `[rsa]` needed for `caching_sha2_password` | **OVERSTATED** — only non-TLS full auth |
| NFR-5 mysqlclient "GPL with FOSS exception" | **WRONG** — `GPL-2.0-or-later`, no exception |
| FR-18 derivation from `version.php` | **VERIFIED** — 876 of 884 tags parse |
| FR-18 `stable-check` tag roster | **VERIFIED** — HTTP 200, exactly 884 entries |
| FR-18 build-time generation | **SOUND** — with four caveats below |
| FR-19 many-to-one | **VERIFIED** — one `db_version` spans up to 99 releases |
| FR-30 OTel optional + no-op | **MECHANISM VERIFIED**, but the assumption is the wrong default |
| FR-40 `uv build` / `uv publish` with extras | **VERIFIED** empirically |
| FR-41 `uv.lock` inert for consumers | **VERIFIED** — but it *is* shipped in the sdist |
| §2 `pip install` → `ResolutionImpossible` | **VERIFIED** verbatim |
| §2 `test_config()` always `False` | **outcome VERIFIED, stated mechanism WRONG for MySQL 8+** |
| FR-39 README example raises `InvalidArgumentsError` | **WRONG** — it raises `NameError` first |
| FR-27 ↔ FR-17 coupling | **NEW BLOCKER** — `wpconfigger` cannot read `$table_prefix` |

---

## 1. FR-1..FR-6 — the frozen surface: INCOMPLETE

Addendum section F is accurate as far as it goes. Every signature it lists matches the
code. But it is an inventory of *classes*, not of the *importable surface*, and FR-6 is
specified against it — so an incomplete inventory makes the compatibility suite
incomplete, exactly as the task suspected.

Established by runtime introspection (third-party imports stubbed so the package loads):

```
PYTHONPATH=stubs:. python3 -c "import wpdatabase2 as w; print(sorted(n for n in dir(w) if not n.startswith('__')))"
```

### Gap 1 — seven names are re-exported at the `wpdatabase2` top level

`wpdatabase2/__init__.py` lines 14-21 import them, so all of these work **today**:

```python
from wpdatabase2 import Secret, WpConnection, WpCredentials, WpDatabase
from wpdatabase2 import InvalidArgumentsError, InvalidDatabaseNameError, RegionNotKnownError
```

FR-1 names only `wpdatabase2.ensure` at the top level and places the classes under
`wpdatabase2.classes`. A caller who wrote `from wpdatabase2 import WpDatabase` is inside
the current surface and outside FR-1's freeze. FR-6 would pass while breaking them.

### Gap 2 — five third-party / stdlib names leak at the top level

`wpdatabase2.WpConfigFile`, `wpdatabase2.boto3`, `wpdatabase2.connector`,
`wpdatabase2.json`, `wpdatabase2.logging` are all importable. FR-26 deliberately removes
the unconditional `boto3` / `wpconfigr` / `mysql.connector` imports, which removes three of
these. That is almost certainly the right call, but it is an unenumerated FR-4 correction
and belongs in the release notes FR-4 requires. Note also there is **no `__all__`
anywhere**, so `from wpdatabase2 import *` currently exports `json`, `logging` and `boto3`
into the caller's namespace.

### Gap 3 — `WpDatabaseVersion` is asymmetric

It is importable from `wpdatabase2.classes` but **not** from `wpdatabase2` (verified:
`hasattr(w, 'WpDatabaseVersion')` → `False`), unlike the other four classes. F does not
record the asymmetry, so a rewrite could "helpfully" add it and quietly widen the surface.

### Gap 4 — module paths are part of the surface

These all import today and F lists none of them:

```
wpdatabase2.classes.connection / .credentials / .database / .secret
wpdatabase2.exceptions.invalid_arguments / .invalid_database_name / .region_not_known
```

The package's own `__init__.py` uses the deep exception paths (`from
wpdatabase2.exceptions.invalid_arguments import InvalidArgumentsError`), which is evidence
that consumers may too. `WpDatabaseVersion` additionally lives at
`wpdatabase2.classes.database.WpDatabaseVersion`.

### Gap 5 — exception constructor signatures are *not* the `Exception` shape

The task asked specifically. Both custom exceptions reject the normal calling convention:

```
InvalidArgumentsError()          -> OK
InvalidArgumentsError('m')       -> OK
InvalidDatabaseNameError()       -> TypeError: missing 1 required positional argument: 'name'
InvalidDatabaseNameError('n')    -> OK
RegionNotKnownError()            -> OK
RegionNotKnownError('m')         -> TypeError: takes 1 positional argument but 2 were given
```

`InvalidDatabaseNameError` *requires* one positional arg and formats it into
`'"{}" is not a valid database name.'`; `RegionNotKnownError` accepts **zero** and hardcodes
its message. F lists these as bare names. FR-6 must assert both arities, and FR-10 (which
starts actually raising `InvalidDatabaseNameError`) must pass the name positionally.

### Gap 6 — read-only-ness is part of the contract

F says `WpConnection`'s properties are "all with setters" — correct, verified all four
(`db_host`, `db_port`, `db_name`, `credentials`) have `fset`. But it is silent on the rest,
and all of these are **getter-only** today:

| Class | Property | setter |
|---|---|---|
| `WpDatabase` | `connection` | none |
| `WpCredentials` | `username`, `password` | none |
| `Secret` | `region`, `as_string`, `as_dict` | none |
| `WpDatabaseVersion` | `db_version`, `wp_version` | none |

Adding a setter is a surface widening; FR-6 should pin the absence.

### Gap 7 — `WpDatabaseVersion._wordPressVersions`

A 56-entry class attribute (`dict`), reachable as
`WpDatabaseVersion._wordPressVersions`. Single-underscore, so nominally private, but F
does not say whether it is frozen and FR-18 replaces it wholesale. Two further properties
of it that FR-18/FR-19 must preserve or deliberately change:

- **Its keys are strings**, and the lookup is `in`-based, so it is type-sensitive:
  ```
  WpDatabaseVersion('38590').wp_version = '4.9.9'
  WpDatabaseVersion(38590).wp_version   = None
  ```
  FR-19's `<=` comparison requires numeric coercion, which changes the `int` case from
  `None` to a hit. That is an improvement, but it is an FR-4 correction, unenumerated.
- **It is stale to the point of being inert** — see §4 below.

### Gap 8 — `__version__` is a module, not a string

`wpdatabase2/__version__.py` is a submodule whose contents are `__version__ = "0.0.15"`.
So `wpdatabase2.__version__` is a *module object*, not `"0.0.15"`, and the string is at
`wpdatabase2.__version__.__version__`. FR-35 moves to `1.0.0` and FR-32 to PEP 621; both
touch this. Whatever the rewrite does, FR-6 should assert the shape a consumer sees.

### Gap 9 — the CLI entry point

F says "CLI: `python -m wpdatabase2`" — correct, and there is **no `console_scripts`
entry point** in `setup.py`, so no `wpdatabase2` command exists. `run_from_cli()` is a
public function in `wpdatabase2.__main__`. FR-2 lists all seven flags correctly and
completely (verified against `__main__.py`); two notes on its "mutual-exclusion rules":

- They are implemented with `arg_parser.error()`, not `argparse.add_mutually_exclusive_group`.
  `error()` always exits **2**, so the `exit(1)` / `exit(2)` / `exit(3)` calls on lines
  62, 71 and 77 are **dead code**. If FR-2 freezes "semantics", freeze exit code 2 — do
  not accidentally implement the three distinct codes the dead lines imply.
- `--wp-config` is `required=True`.

### Gap 10 — no `py.typed`, no type hints

FR-34 adds both. Not a compatibility risk, noted for completeness.

### FR-5 — VERIFIED, and there is a third dependent test

The claim that `from_username_and_password()` returns `None` on partial input:

```
(user, None) -> None
(None, pass) -> None
(None, None) -> raises InvalidArgumentsError: Must specify the username or the secret identifier.
```

So FR-5 is right for partial input. **Two tests assert it directly** — exactly as claimed:
`tests/classes/test_credentials.py:43` and `:54`. But a **third** test depends on it
transitively: `tests/classes/test_connection.py:42-46` builds its fixture with
`WpCredentials.from_username_and_password(None, 'password')` and then asserts
`self.assertIsNone(instance.credentials)`. Under FR-5 that test raises during setup, not at
its assertion. Worth naming in FR-5 so the migration is not surprised.

Separately: the `(None, None)` path already raises today, but with the **wrong message** —
"Must specify the username or the secret identifier" when the real problem is that neither
was given. NFR-3 and NFR-8 cover this; it is a live instance.

---

## 2. FR-8 / FR-9 — portable SQL: VERIFIED, except the MariaDB floor

Tested against real servers, not documentation.

### The sequence works, and is idempotent — VERIFIED

```sql
CREATE DATABASE IF NOT EXISTS `wpdb`;
CREATE USER IF NOT EXISTS 'u'@'%' IDENTIFIED BY 'pw';
ALTER USER 'u'@'%' IDENTIFIED BY 'pw';
GRANT ALL PRIVILEGES ON `wpdb`.* TO 'u'@'%';
FLUSH PRIVILEGES;
```

| Server | version | FR-8 sequence | re-run |
|---|---|---|---|
| MySQL 8.0 | 8.0.46 | OK | OK |
| MySQL 8.4 | 8.4.11 | OK | OK |
| MySQL 9.x | 9.7.2 | OK | OK |
| MariaDB 11.4 | 11.4.13 | OK | OK |
| MariaDB latest | 13.0.2 | OK | OK |

`SHOW GRANTS` confirms FR-13 (database-scoped, not global) on every server:

```
GRANT USAGE ON *.* TO `pwtest`@`%`
GRANT ALL PRIVILEGES ON `wpdb`.* TO `pwtest`@`%`
```

### `ALTER USER` is genuinely required — VERIFIED

This is the claim most worth checking, because comparing `authentication_string` proves
nothing (`caching_sha2_password` re-salts on every write). I tested by **logging in**:

```
[1] CREATE USER IF NOT EXISTS 'pwtest' IDENTIFIED BY 'pwA'; ALTER USER ... 'pwA'
    login with 'pwA' => OK
[2] CREATE USER IF NOT EXISTS 'pwtest' IDENTIFIED BY 'pwB'    (no ALTER)
    login with 'pwB' => FAILED
    login with 'pwA' => OK          <- old password retained
[3] ALTER USER 'pwtest' IDENTIFIED BY 'pwB'
    login with 'pwB' => OK
    login with 'pwA' => FAILED
```

Identical on MySQL 8.0.46, 8.4.11, 9.7.2 and MariaDB 13.0.2. `IF NOT EXISTS` silently
skips the whole statement including the password. FR-8's parenthetical is correct and the
`ALTER USER` is load-bearing, not belt-and-braces.

### `mysql_native_password` lifecycle — VERIFIED at every stage

```sql
SELECT plugin_name, plugin_status FROM information_schema.plugins
 WHERE plugin_name IN ('mysql_native_password','caching_sha2_password','sha256_password');
```

| Server | `mysql_native_password` | `caching_sha2_password` | `default_authentication_plugin` |
|---|---|---|---|
| MySQL 8.0.46 | `ACTIVE` | `ACTIVE` | `caching_sha2_password` |
| MySQL 8.4.11 | `DISABLED` | `ACTIVE` | **variable removed** (`authentication_policy = *,,`) |
| MySQL 9.7.2 | **absent entirely** | `ACTIVE` | **variable removed** |
| MariaDB 13.0.2 | `ACTIVE` | **absent** | — |

- **Removed in 9.0: VERIFIED.** Not merely disabled — the plugin is not in
  `information_schema.plugins` at all on 9.7.2, and
  `CREATE USER ... IDENTIFIED WITH mysql_native_password BY 'x'` → `ERROR 1524 (HY000):
  Plugin 'mysql_native_password' is not loaded`.
- **Off by default in 8.4: VERIFIED.** Present but `DISABLED`; same `ERROR 1524`.
- **Deprecated in 8.0.34: VERIFIED** from the 8.0.34 release notes: *"The
  mysql_native_password authentication plugin now is deprecated and subject to removal in a
  future version of MySQL. CREATE USER, ALTER USER, and SET PASSWORD operations now insert
  a deprecation warning into the server error log…"* (Bug #35336317, WL #15460).
- **A second, unrelated reason not to hardcode.** `default_authentication_plugin` is itself
  **gone** from 8.4 and 9.x, replaced by `authentication_policy`. Any code that reads the
  old variable to discover the server default gets nothing on 8.4+. FR-9's "the server's own
  default is used" is best implemented by *saying nothing* — omit `IDENTIFIED WITH`
  entirely, as FR-8 already does — rather than by querying for the default.

### MariaDB has no `caching_sha2_password` — VERIFIED, with a trap

`information_schema.plugins` on 13.0.2 lists only `mysql_native_password`. The plugin
directory is misleading:

```
$ ls /usr/lib/mysql/plugin/ | grep -iE 'ed25519|sha2'
auth_ed25519.so
auth_mysql_sha2.so
caching_sha2_password.so
client_ed25519.so
sha256_password.so
```

`caching_sha2_password.so` looks like server support but is a **client-side** plugin:

```
mariadb> INSTALL SONAME 'caching_sha2_password';
ERROR 1127 (HY000): Can't find symbol '_mysql_plugin_interface_version_'
                    in library '/usr/lib/mysql/plugin/caching_sha2_password.so'
```

So the addendum is right, and anyone "correcting" it from a directory listing would be
wrong. MariaDB's default remains `mysql_native_password` — every account on a fresh 13.0.2
(`mariadb.sys`, `root`, `healthcheck`) uses it.

### NFR-4's MariaDB floor of 10.1 is WRONG

The addendum derived the floor from `CREATE USER ... IF NOT EXISTS` alone. FR-8 needs
**four** statements, and `ALTER USER` has a later floor. Per-statement, on real servers:

| Statement | MariaDB 10.0.38 | MariaDB 10.1.48 | MariaDB 11.4.13 |
|---|---|---|---|
| `CREATE USER IF NOT EXISTS` | `ERROR 1064` | **OK** | OK |
| `CREATE USER IF NOT EXISTS` (2nd, idempotent) | `ERROR 1064` | **OK** | OK |
| `ALTER USER ... IDENTIFIED BY` | `ERROR 1064` | **`ERROR 1064`** | OK |
| `SET PASSWORD FOR ... = PASSWORD()` | `ERROR 1133` | OK | OK |
| `GRANT` (no `IDENTIFIED BY`) | OK | OK | OK |
| `FLUSH PRIVILEGES` | OK | OK | OK |
| `CREATE OR REPLACE USER` | `ERROR 1064` | OK | OK |

So the addendum's `IF NOT EXISTS` floor of 10.1 is itself **VERIFIED** — and irrelevant,
because `ALTER USER` (added in MariaDB 10.2) fails on 10.1.48. **The floor for the FR-8
sequence as specified is MariaDB 10.2.** Fix NFR-4.

This is a clean instance of the repo's own rule #4: the guard (the floor) was derived from
one member of the set rather than from the whole set it must cover. Whatever floor is
written down, **assert it in CI against that exact server version**, or it will drift again.

Practical note: since MariaDB 10.1 and 10.2 have both been EOL for years, the honest fix is
probably to raise the declared floor well above 10.2 to something still supported (10.11 or
11.4 LTS) and test that, rather than to document a floor nobody runs.

### Three further divergences the addendum should record

1. **`IDENTIFIED WITH <plugin> BY '<pw>'` is MySQL-only syntax, entirely.** On MariaDB
   13.0.2 it is a parse error *regardless of plugin* — even for `mysql_native_password`,
   which MariaDB fully supports:
   ```
   CREATE USER IF NOT EXISTS 'nattest'@'%' IDENTIFIED WITH mysql_native_password BY 'pwN';
   ERROR 1064 (42000): ... right syntax to use near 'BY 'pwN''
   ```
   MariaDB spells it `IDENTIFIED VIA <plugin> USING PASSWORD('pw')`. This strengthens FR-9
   considerably: naming a plugin at all is unportable, not just naming the *wrong* plugin.
2. **`GRANT ... IDENTIFIED BY` still works on MariaDB.** §2's claim that it is "a syntax
   error on MySQL 8" is VERIFIED (`ERROR 1064` on 8.0.46, 8.4.11 and 9.7.2) — but on
   MariaDB 13.0.2 it **succeeds** and creates the user. The current code is therefore
   broken only against MySQL 8+, not universally. Worth stating precisely so the
   regression test targets the right servers.
3. **`CREATE OR REPLACE USER` is MariaDB-only — VERIFIED.** `ERROR 1064` on all three MySQL
   servers, OK on MariaDB 10.1+. Correct in the addendum; do not reach for it.

### FR-38 — a CI matrix trap worth writing into the requirement

Docker tags do not mean what the PRD's matrix says:

```
mysql:8        -> Ver 8.4.11     <-- NOT 8.0.x
mysql:8.0      -> Ver 8.0.46
mysql:8.4      -> Ver 8.4.11
mysql:9        -> Ver 9.7.2
mysql:latest   -> Ver 26.7.0     <-- outside the declared matrix entirely
mariadb:latest -> 13.0.2-MariaDB
```

A matrix row written as `mysql:8` tests **8.4**, silently skipping 8.0 — the only version
in the set where `mysql_native_password` is still `ACTIVE`, i.e. precisely the divergence
FR-38 exists to cover. Pin `mysql:8.0` **and** `mysql:8.4` explicitly. Note also that
MySQL has moved to calendar versioning past 9.7 (`mysql:latest` is 26.7.0), so "MySQL 9.x"
is already not the newest server; decide deliberately whether 26.x is in scope.

---

## 3. NFR-5 — driver choice: PyMySQL is right, with two corrections

### PyMySQL metadata — VERIFIED (one imprecision)

`https://pypi.org/pypi/PyMySQL/json`:

```
LATEST: 1.2.0
requires_python: >=3.9
license: MIT
pymysql-1.2.0-py3-none-any.whl   2026-05-19
dependencies = []
```

Version, date, license, Python floor, pure-Python, zero dependencies: all correct.
**Imprecision:** the wheel is `py3-none-any` — platform-independent but py3-only, not a
"universal" (`py2.py3`) wheel. Cosmetic; say "pure-Python wheel".

### The `[rsa]` claim is OVERSTATED

NFR-5 says "MySQL 8 `caching_sha2_password` over a non-TLS connection needs PyMySQL's
`[rsa]` extra." Closer to the truth, from `pymysql/_auth.py` and `connections.py`:

- **empty password** → no crypto.
- **fast authentication** (server-side cache hit) → `hashlib.sha256` only. **Never** needs
  `cryptography`, TLS or not. Attempted inline in the initial handshake, so this is the
  common case.
- **full authentication** (first-ever auth for that account, or after a server restart /
  cache flush):
  - over TLS *or* a unix socket (`conn._secure`) → plaintext password over the encrypted
    channel. **No `cryptography`.**
  - otherwise → RSA, which raises `RuntimeError: 'cryptography' package is required for
    sha256_password or caching_sha2_password auth methods`.

And PyMySQL **1.2.0 changed the default**: *"PyMySQL uses TLS by default when server
supports it. Use `ssl_disabled=True` to prohibit SSL. (#1213)"* Since MySQL 8+/9 ship TLS
on by default with self-signed certs, a base no-extras install now normally authenticates
fine. (PyMySQL's README still states the old absolute requirement and was not updated.)

**But do not conclude the extra is unnecessary.** The residual failure needs all of:
MySQL 8/9 + non-empty password + server cache miss + non-secure socket. That combination is
**intermittent by construction** — it works after the first auth warms the cache and
reappears after a restart. For a provisioning library whose whole job is the *first* auth
against a *fresh* server, that is the worst possible failure shape.

Also note `server_public_key` does **not** avoid `cryptography`; it only skips the key-fetch
round trip.

**Recommendation: declare `PyMySQL[rsa]` in the base install, not bare `PyMySQL`.**
`cryptography` publishes manylinux/macOS/Windows wheels, so NFR-5's "no compiler, no system
libraries" still holds on every mainstream platform. Add `ed25519` (PyNaCl) only if MariaDB
ed25519 accounts are in scope — that one has **no** TLS escape hatch and is a hard PyNaCl
requirement. For reference, MariaDB 13.0.2 does not load ed25519 by default but it is one
`INSTALL SONAME 'auth_ed25519'` away, after which `IDENTIFIED VIA ed25519 USING
PASSWORD('x')` works — verified.

### No MySQL 9 blocker — VERIFIED

- PyMySQL negotiates whatever plugin the server names in the handshake, so
  `mysql_native_password`'s removal is a non-event; `caching_sha2_password` carries it.
- No open MySQL 9 defect in `PyMySQL/PyMySQL` (16 open issues, none is one).
- PyMySQL's own CI (`.github/workflows/test.yaml`) runs `mysql:9`, `mysql:8.4`, `mysql:8.0`,
  `mysql:5.7`, `mariadb:12`, `11.8`, `11.4`, `10.11`, `10.6` — the matrix this PRD needs,
  already green upstream. (Caveat: that CI installs `cryptography` and `PyNaCl`
  unconditionally, so it does not prove the no-extras path.)
- Two forward-looking gaps, neither a blocker today: MySQL's
  `authentication_openid_connect` is unsupported (PR #1221 still open), and MariaDB's
  **PARSEC** plugin has no handler at all — MariaDB documents it as *"intended to become the
  default authentication plugin in a future release"*. Put PARSEC on the watch list.

### The alternatives — one WRONG license claim

**`mysqlclient` — addendum license is WRONG.** PyPI metadata says
`license_expression: 'GPL-2.0-or-later'`. There is **no FOSS exception** (that clause
belongs to Oracle's connector, not to mysqlclient). The addendum's "GPL-2.0-or-later" in
the table is right; NFR-5's prose grouping is what to fix. The build-friction claim is
**VERIFIED**: latest 2.3.0 (2026-09-14) publishes 16 wheels, all `win_amd64` / `win_arm64`.
No manylinux, no macOS — Linux and macOS build from sdist. Correctly disqualified.

**`mysql-connector-python` — claims VERIFIED, plus a new reason to reject it.** 26.7.0
(2026-07-29), `GNU GPLv2 (with FOSS License Exception)`, `requires_python >=3.10`, ships
both C-extension wheels and one pure-Python `py2.py3-none-any` wheel. Calendar versioning
confirmed from MySQL's own notes: *"MySQL Server now uses calendar-based versioning… MySQL
26.7.0 is the first such calendar-version release"*, and 26.7.0 *"contains no functional
changes"* — so the addendum's "not a rewrite from 9.x" is right.

The new finding: its **pure-Python mode cannot do RSA at all**.
`mysql/connector/plugins/caching_sha2_password.py`: *"Note that encrypting using RSA is not
supported since the Python Standard Library does not provide this OpenSSL functionality."*
Full auth returns the cleartext password with no RSA branch. So pure-Python
Connector/Python is **strictly worse** than `PyMySQL[rsa]` on exactly the non-TLS full-auth
case discussed above. Also no `musllinux` wheels (Alpine builds from source), and pip
prefers the 21 MB C wheel unless forced.

### The currently pinned driver — VERIFIED broken

`mysql-connector` 2.2.9 against MySQL 8.0.46:

```
mysql.connector.errors.NotSupportedError: Authentication plugin 'caching_sha2_password' is not supported
```

Confirms §2's "fails against MySQL 8 authentication".

### Verdict

**PyMySQL is the right call.** It is the only candidate that installs with no compiler
anywhere, it is MIT, and its upstream CI already covers this PRD's exact server matrix.
Change NFR-5 to declare **`PyMySQL[rsa]`**, correct the mysqlclient license, soften
"universal wheel" to "pure-Python wheel", and record PARSEC as a known future gap.

---

## 4. FR-18 / FR-19 — version map derivation: VERIFIED, and the existing dict is inert

### Both sources work — VERIFIED

```
$ curl -sS -w '%{http_code}' https://api.wordpress.org/core/stable-check/1.0/
HTTP=200  bytes=20721
type: dict  count: 884
status values: Counter({'insecure': 859, 'outdated': 24, 'latest': 1})
latest: 7.1
```

Exactly the **884** the addendum claims. It is a flat `{version: status}` map — a usable
roster, though note it carries *security status*, not "is this a tag", which matters below.

`version.php` parses cleanly at tags:

```
tag=7.1    wp_version=7.1     wp_db_version=61833
tag=7.0    wp_version=7.0     wp_db_version=61833
tag=6.8    wp_version=6.8     wp_db_version=58975
tag=6.0    wp_version=6.0     wp_db_version=51917
tag=4.9    wp_version=4.9     wp_db_version=38590
tag=2.0    wp_version=2.0     wp_db_version=3308
master     7.2-alpha-63635    wp_db_version=61833
```

Every one of the addendum's spot-checks reproduces (4.9→38590, 6.8→58975, 7.1→61833,
trunk→61833). Note `trunk` 404s; the branch is `master`.

### The derivation floor — now ESTABLISHED (was the addendum's open item)

I fetched all 884 tags concurrently:

```
total stable-check tags:   884
  parseable $wp_db_version: 876
  git tag missing (404):      3  -> 1.0.2, 1.2.1, 1.2.2
  tag exists, no db_version:  5  -> 1.5.1, 1.5.1.1, 1.5.1.2, 1.5.1.3, 1.5.2
```

**The floor is WordPress 2.0 (`db_version` 3308).** `version.php` exists at 1.5.x but
contains no `$wp_db_version`; 1.0.2/1.2.1/1.2.2 have no git tag at all. 876 of 884 → the
derivation holds for **99.1%** of the roster and for every release anyone could plausibly
be running. Replace the addendum's vague "absent from 0.7 onward" with this.

### FR-19's many-to-one premise — VERIFIED, and it is severe

```
db=38590: 99 releases  4.7   .. 4.9.31
db=49752: 54 releases  5.6   .. 5.8.15
db=44719: 52 releases  5.1   .. 5.2.26
db=53496: 39 releases  6.0.1 .. 6.2.11
db=30135: 38 releases  4.1.5 .. 4.1.42
```

A single `db_version` can span **99** releases and cross **three** minor lines. FR-19's
rule is the right one, but the PRD should say plainly what it buys: `wp_version` can only
ever answer *"the newest release this could be"*, never *"the release this is"*. That is
worth one sentence in the docstring, given NFR-8.

### The shipped dict is worse than the PRD implies — strong support for FR-18

I built the full derived map and audited all 56 existing entries against FR-19's rule:

```
shipped entries:                  56
distinct db_versions derivable:   67
  match FR-19 rule:              29   (8 of these differ only cosmetically, e.g. "2.1.0" vs tag "2.1")
  substantive mismatch:          17
  not derivable at all:           2
db_versions missing from shipped: 13
```

Three findings that change how FR-18 should be written:

1. **Every current WordPress returns `None` today.** The dict tops out at `48748` (5.5.x).
   All 13 missing `db_version`s are newer: `49752` (5.6–5.8.15), `51917` (6.0), `53496`,
   `55853`, `56657`, `57155`, `58975`, `60421`, `60717`, `61833` (7.1). Verified:
   `WpDatabaseVersion('61833').wp_version` → `None`. So `get_database_version().wp_version`
   is `None` for **every** WordPress from 5.6 onward — i.e. for every supported version.
   This belongs in §2 alongside the other headline defects; it is the same class of bug.

2. **The mismatches are systematically stale, not random.** `38590` → shipped `"4.9.9"`,
   derived highest `"4.9.31"`. `26151` → `"3.7.9"` vs `"3.7.41"`. The dict was generated
   once, when those were the newest patch releases, and then froze. That is precisely the
   drift FR-18 exists to prevent, and it is worth citing in FR-18 as the evidence.

3. **Two entries are NOT derivable from the stated source** — `"2540": "1.2.2"` and
   `"2541": "1.5.2"`. Both sit below the 2.0 floor; no `version.php` at any tag yields
   them. They presumably came from WordPress.org's hand-maintained table. So switching to
   derivation **silently drops two keys from a public lookup** — a change to
   `WpDatabaseVersion.wp_version`'s observable behaviour that no FR currently enumerates.
   Either carry them as a documented hand-seeded prefix below the floor (with a comment
   saying why they cannot be derived), or enumerate the drop under FR-4. Do not let it
   happen by accident.

### Is build-time generation sound? YES — with four caveats

Sound, and the `[ASSUMPTION]` is correct: 876 HTTPS requests is fine as a maintenance task
and unacceptable at runtime. Four things the generator must handle, all observed:

1. **Tolerate 404s.** 3 roster entries have no git tag. A generator that treats any
   non-200 as fatal never finishes.
2. **Skip below the floor.** 5 tags return 200 with no `$wp_db_version`. Distinguish
   "fetched but absent" from "fetch failed" — silently coercing the first to the second
   hides real network problems.
3. **Sort by version tuple, not lexically.** `"4.9.31"` vs `"4.9.9"` is the exact mismatch
   the current dict already has; `max()` on strings picks `"4.9.9"`. Parse to
   `(4, 9, 31)`.
4. **Normalise tag spelling.** Tags are `2.1`, `3.0`, `4.2`; the current dict says
   `"2.1.0"`, `"3.0.0"`, `"4.2.0"`. Pick one convention and say which in the docstring, or
   8 of the 29 current "matches" silently change.

Also: pin the generated data's provenance (date generated, newest tag seen) in the shipped
artifact, and — per the repo's rule #3 — add a CI check that the artifact is not older than
some threshold, or the regeneration command will be exactly as forgotten as the dict it
replaces.

### FR-17 / FR-20 notes

- **FR-17 is blocked by FR-27.** See §7 — this is the finding I would act on first.
- **FR-20 is consistent with the code**: `wp_version` returns `None` for unknown keys today,
  so "continues to return `None`" is accurate. But FR-20 also wants "newer" distinguishable
  from "no version found", and those are currently the same `None`. That is a new
  capability on a frozen property, so it needs a *separate* accessor rather than a changed
  `wp_version` return — otherwise FR-20 and FR-1 contradict each other. Flagging as
  **UNCLEAR** in the PRD as written.

---

## 5. FR-30 — OpenTelemetry: mechanism VERIFIED, but the assumption is the wrong default

### Can a library emit spans with OTel optional and degrade to no-ops? YES

The mechanism has a name, and it is worth being precise because the PRD conflates two
different things.

**Mechanism:** `opentelemetry-api` ships the no-op layer itself.
`trace.get_tracer_provider()` → `ProxyTracerProvider` → `ProxyTracer` → spans are
`NonRecordingSpan`. Verified at runtime with `opentelemetry-api==1.44.0` installed and **no
SDK**:

```
tracer_provider: opentelemetry.trace.ProxyTracerProvider
tracer:          opentelemetry.trace.ProxyTracer
span:            opentelemetry.trace.span.NonRecordingSpan
span.is_recording(): False
set_attribute / add_event / record_exception: all succeeded silently
```

Spec: *"In general, in the absence of an installed SDK, the Trace API is a 'no-op' API.
This means that operations on a Tracer, or on Spans, should have no side effects and do
nothing."* Python API reference: `NonRecordingSpan` is *"The Span that is used when no Span
implementation is available. All operations are no-op except context propagation."*
(The *Proxy* provider, not a `DefaultTracerProvider` — the proxy exists so a later
`set_tracer_provider()` retroactively upgrades tracers already handed out.)

### The two cases FR-30 conflates

- **(a) API installed, SDK not configured** → no-ops are free. Zero library code.
- **(b) API not installed at all** → `ImportError: No module named 'opentelemetry'`. The
  library must write and maintain its own shim.

FR-30's `[ASSUMPTION]` ("declared as an extra… degrading to no-ops when absent") requires
**(b)**. It buys (a) for free and then obliges you to hand-write a second no-op
implementation duplicating `NonRecordingSpan` and `ProxyTracer`.

### Is it standard practice? Not for libraries

The standard pattern is the opposite of FR-30's assumption. All four
`opentelemetry-instrumentation-*` packages checked require `opentelemetry-api~=1.12`
**unconditionally** and put the *instrumented* library behind an extra:

| package | requires_dist |
|---|---|
| `opentelemetry-instrumentation-requests` 0.65b0 | `opentelemetry-api~=1.12`; `requests~=2.0; extra == "instruments"` |
| `opentelemetry-instrumentation-django` 0.65b0 | `opentelemetry-api~=1.12`; `django>=2.0; extra == "instruments"` |
| `opentelemetry-instrumentation-psycopg2` 0.65b0 | `opentelemetry-api~=1.12`; … |
| `opentelemetry-instrumentation-sqlalchemy` 0.65b0 | `opentelemetry-api~=1.12`; … |

OTel's own guidance: *"Libraries should only use the OpenTelemetry API"* and *"Unless your
application imports the OpenTelemetry SDK, your instrumentation does nothing and does not
impact application performance."* The API **is** the degradation mechanism. Mainstream
hard-dependers: `mcp`, `pydantic-ai-slim`, `dbt-core`, `chromadb`, and `prefect` (which
hard-depends on the API and puts only the *SDK/exporters* behind its `otel` extra).

### The weight argument does not survive contact

`opentelemetry-api` 1.44.0: `requires_dist: ['typing-extensions>=4.5.0']`. One transitive
dependency, which nearly everything already pulls. Wheel is **58 KB**, `py3-none-any`, no
compiled extensions; install measured at 2 packages / 39 ms. G6's "keep the base install
dependency-light" is not meaningfully served by excluding it.

### Precedent for the extra pattern does exist

So FR-30 is not unprecedented, and I would not call it WRONG — three real libraries do
exactly this: `google-cloud-storage` 3.14.1 (`opentelemetry-api; extra == "tracing"` plus a
`try/except ImportError` → `HAS_OPENTELEMETRY` flag in `_opentelemetry_tracing.py`),
`azure-core` 1.41.0 (`extra == "tracing"`, `_get_tracer_impl()` returning `None`), and
`redis-py` 8.1.0 (`extra == "otel"`, `OTEL_AVAILABLE` flag). A cheaper variant is
strawberry-graphql / temporalio / litestar's: a separate opt-in integration module with an
unconditional import and no shim at all.

### Recommendation — resolve open question #2 as "hard dependency"

Against the repo's own rule #1, writing a no-op shim is reimplementing something a
maintained library already ships, for a 58 KB saving. **Hard-depend on
`opentelemetry-api` (loosely pinned, e.g. `>=1.20,<2`), never on the SDK**, and let
absence-of-SDK do the degrading. That is what OTel documents, what its own contrib packages
do, and it makes FR-30's "first-class" literal rather than aspirational. If an extra is
still wanted, prefer the opt-in-module pattern over the shim.

**Two corrections regardless of which way this goes:**

- `opentelemetry-api` 1.44.0 requires **Python >=3.10**. Compatible with FR-34's assumed
  3.11 floor, but if open question #3 lowers the floor to 3.9 the resolver silently caps
  you at `opentelemetry-api 1.41.1`. Worth a note against FR-34.
- API/SDK are 1.x stable (`1.0.0` in March 2021, semver); the `opentelemetry-instrumentation-*`
  contrib packages are on a separate `0.xxbN` **beta** line. Do not depend on contrib and
  call it stable.

---

## 6. FR-40 / FR-41 — uv: VERIFIED, with one factual correction to FR-41

### `uv build` / `uv publish` are appropriate for a library — VERIFIED

Both exist in the locally installed uv 0.11.6. `uv build` **delegates to the project's own
PEP 517 backend** — proven by the wheel it produced:

```
Wheel-Version: 1.0
Generator: hatchling 1.32.0
```

Corroborated by the flag `--force-pep517  Always build through PEP 517, don't use the fast
path for the uv build backend` — the fast path applies only to uv's own `uv_build` backend;
hatchling / setuptools / flit / poetry-core always go through PEP 517. Nothing about `uv
build` is application-specific. `uv publish` is not preview-gated. uv's docs recommend
`uv build --no-sources` before publishing, to prove the package builds without
`tool.uv.sources` — worth adding to FR-40.

### PEP 621 extras survive into the built metadata — VERIFIED empirically

Throwaway project with `[project.optional-dependencies]`, `uv build`, then unzipped:

```
Metadata-Version: 2.5
Requires-Dist: packaging>=23
Provides-Extra: dev
Requires-Dist: pytest>=7; extra == 'dev'
Requires-Dist: ruff>=0.1; extra == 'dev'
Provides-Extra: otel
Requires-Dist: opentelemetry-api>=1.20; extra == 'otel'
```

Identical in the sdist's `PKG-INFO`. End-to-end with real pip:
`pip install "demolib[otel] @ file://…tar.gz"` pulled `opentelemetry-api`; installing the
wheel without the extra did not. **FR-33's extras contract is safe under `uv build`.**

### FR-41's "governs development only" — correct in effect, WRONG in one detail

The functional claim is **VERIFIED** by differential test: I locked `packaging==23.2`,
confirmed the shipped sdist's `uv.lock` contained `version = "23.2"`, then installed that
sdist as a consumer:

```
pip install lockdiff-0.1.0.tar.gz     -> packaging 26.3
uv pip install lockdiff-0.1.0.tar.gz  -> + packaging==26.3
```

Both ignored the lockfile entirely and resolved from `Requires-Dist: packaging>=23`.
FR-41's conclusion holds, and FR-36 is unaffected.

**The correction:** `uv.lock` **is** shipped inside the sdist by default (hatchling includes
root files that are not gitignored). It is absent from the wheel.

```
--- SDIST ---                  --- WHEEL ---
demolib-0.1.0/uv.lock          demolib/__init__.py
demolib-0.1.0/pyproject.toml   demolib-0.1.0.dist-info/METADATA
demolib-0.1.0/PKG-INFO         demolib-0.1.0.dist-info/RECORD
```

So reword FR-41 from "It governs development only" to "it is **inert** for consumers, who
resolve from the published metadata", and — if you want it gone from the artifact —
exclude it in the backend config (`[tool.hatch.build.targets.sdist] exclude = ["uv.lock"]`).
As written, FR-41 states something a reader could check and find false.

One more note: uv's docs say *"This file should be checked into version control"* with **no
carve-out for libraries**, and do not discuss consumers of a published package at all. So
"libraries should not commit `uv.lock`" is **UNVERIFIABLE as uv guidance** — it is community
convention. FR-41's choice to commit it is defensible and uv-endorsed.

### Mechanics worth folding into FR-40

- **`[build-system]` is not required** — verified: a `pyproject.toml` without one still
  built, via uv's setuptools-legacy fallback (visible `install_egg_info`,
  `top_level.txt`). uv *"strongly recommend[s]"* declaring one, and the fallback produces
  worse metadata. **Declare one explicitly.**
- **`tool.uv.package = false` does not block publishing.** It governs installation into the
  project environment; explicit `uv build` calls are still honoured. uv's own checklist says
  you want a package when *"Writing a library"* / *"Distributing to others"* / *"Using a
  `src` and `test` layout"* — so set `package = true` (or just declare the build system,
  which uv uses to detect a package).
- **`--package` on `uv build` is workspace selection**, not a library/app switch.
- **Publish auth, all confirmed in `uv publish --help`:** `--token` / `UV_PUBLISH_TOKEN`,
  `--trusted-publishing <automatic|always|never>` (no credentials needed from GitHub
  Actions), `--check-url` (*"Check an index URL for existing files to skip duplicate
  uploads"*), `--dry-run`, PEP 740 attestations on by default. Use trusted publishing for
  FR-40 rather than a long-lived token.
- **One operational caveat from uv's docs:** *"Even though `uv publish` retries failed
  uploads, it can happen that publishing fails in the middle, with some files uploaded and
  some files still missing."* `--check-url` is the mitigation.

**Verdict: FR-40 and FR-41 are sound.** uv is appropriate for a library, extras work, and
consumers are unaffected. Fix FR-41's sdist detail.

---

## 7. NEW BLOCKER — FR-27 and FR-17 are coupled, and one candidate is already eliminated

The addendum flagged this as an open item: *"`$table_prefix` is a variable rather than a
`define`, which FR-17 depends on reading — worth confirming the chosen option can read it
at all."* I confirmed it. It is decisive.

`$table_prefix` is a plain PHP variable in the real file (`wp-config-sample.php` at tag 7.1,
line 74): `$table_prefix = 'wp_';` — every `DB_*` value is a `define()`, this one is not.

**`wpconfigger` 1.0.0 cannot read it.** Installed from PyPI and run against that file:

```
get('DB_NAME')       = 'database_name_here'
get('DB_USER')       = 'username_here'
get('DB_HOST')       = 'localhost'
get('table_prefix')  = None
get('$table_prefix') = None
```

Its `wp_config_string.py` is `define`-only regex (`'define'` literals at lines 56 and 81
feeding `re.compile(expression, re.MULTILINE)`); 343 lines across the package, matching the
addendum's count of cariad's original. There is no variable handling to configure around.
Its public API is exactly `content`, `get`, `set`.

**`phply` 1.2.6 reads it correctly.** Same file, real parse:

```
phply parsed OK. defines found: 16
DB_NAME = database_name_here | DB_HOST = localhost
variables found: {'$table_prefix': 'wp_'}
=> $table_prefix = wp_
```

### Consequences for the PRD

1. **FR-27's option table needs a new column, and it changes the answer.** "Depend on
   `wpconfigger` 1.0.0" is marked *"Compliant — uses a released library"* with no
   functional objection recorded. It is now functionally **disqualified** for FR-17.
   Same objection applies to "vendor cariad's 343 lines", since that is the same
   regex implementation.
2. **FR-27 already blocks FR-26; it also blocks FR-17.** The PRD says only the former. Two
   requirements are behind one unmade decision.
3. **The ADR rule #1 demands is now easier to write honestly, and points at `phply`.**
   `phply` is a real PHP lexer/parser (PLY-based, BSD, 2023-01-06 — 3 years stale but
   functional, verified above), and it is the only listed candidate that satisfies FR-17.
   Choosing it means *not* writing a parser, which is what rule #1 asks for. The remaining
   honest alternative is publishing the `wpconfigr` 1.4 fork **with variable support added**
   — which is writing the parser, and needs the full ADR.
4. FR-18's data pipeline is unaffected; this is purely the config-reader decision.

Note that `wpconfigger` is *importable as* `wpconfigr` (verified — it installs the
`wpconfigr` package name), so it is drop-in for the current import and would make FR-36
pass immediately while leaving FR-17 impossible. That is a tempting and wrong shortcut;
worth saying so explicitly in FR-27.

---

## 8. Corrections to §2's diagnoses (both reproduce; one mechanism is misstated)

### "Uninstallable from PyPI" — VERIFIED verbatim

```
$ pip install wpdatabase2
ERROR: Cannot install wpdatabase2==0.0.1 … because these package versions have conflicting dependencies.
    wpdatabase2 0.0.15 depends on wpconfigr<=2.0.0 and >=1.0.0
    …
Additionally, some packages in these conflicts have no matching distributions available for your environment:
    wpconfigr
ERROR: ResolutionImpossible
```

Supporting facts, all checked:

```
https://pypi.org/pypi/wpconfigr/json        HTTP 404
https://pypi.org/pypi/wpdatabase/json       HTTP 404
https://pypi.org/pypi/wpconfigger/json      HTTP 200   (1.0.0, single release, 2022-09-07, MIT)
https://pypi.org/pypi/phply/json            HTTP 200   (1.2.6, BSD, 2023-01-06, deps: ply)
https://pypi.org/pypi/mysql-connector/json  HTTP 200
```

`pip install 'wpconfigr>=1.0.0,<=2.0.0'` → *"Could not find a version that satisfies the
requirement (from versions: none)"*. **Every** published `wpdatabase2` carries the pin —
`0.0.1`–`0.0.8` via `wpconfigr~=1.0.0`, `0.0.9`–`0.0.15` via the range. Incidental: PyPI
lists no `0.0.14` (0.0.13 → 0.0.15) despite the bump commit, so a release step has failed
silently before.

### "`test_config()` always returns `False`" — outcome VERIFIED, mechanism WRONG for MySQL 8+

The outcome reproduces against a live server:

```
test_config()         -> False
does_database_exist() -> False
```

And the quoted `TypeError` is exact. Connector 2.2.9 genuinely lacks the protocol, with no
server needed:

```
MySQLConnection: __enter__=False __exit__=False
MySQLCursor:     __enter__=False __exit__=False
```

Against MariaDB 13.0.2 (which uses `mysql_native_password`, so 2.2.9 *can* authenticate),
the failure is verbatim the PRD's:

```
connected OK to MariaDB with connector 2.2.9: MySQLConnection
  'with conn'          -> TypeError: 'MySQLConnection' object does not support the context manager protocol
  'with conn.cursor()' -> TypeError: 'MySQLCursor' object does not support the context manager protocol
```

**But against MySQL 8.0.46 the `with` is never reached.** `connector.connect()` itself
raises one step earlier:

```
mysql.connector.errors.NotSupportedError: Authentication plugin 'caching_sha2_password' is not supported
```

So §2's second and third bullets are not one defect with one cause; they are **two
independent failures behind the same swallow**, and which one you hit depends on the
server's default auth plugin. The `except Exception` hides both, which is why they were
indistinguishable. This matters for addendum E: it attributes three observed defects to one
root cause. The *swallow* is indeed the single highest-leverage fix (NFR-2 is right), but
removing it reveals **two** distinct driver failures, only one of which the driver swap
(NFR-5) fixes by itself. Reword §2's second bullet to name the server dependence, or the
regression test will be written against the wrong exception.

Note the second-order effect the PRD gets right: `cursor` is also not a context manager, so
even on a native-password server `test_config()` would fail at `with conn.cursor()`. Two
`with` statements, both broken.

### FR-39's README claim — WRONG in detail

FR-39 says the library example *"raises `InvalidArgumentsError`, because the constructor
requires a `WpConfigFile` instance."* Run verbatim from `README.md` lines 59-64:

```python
import wpdatabase2
wpdb = WpDatabase('path to wp-config.php')
```
```
NameError: name 'WpDatabase' is not defined
```

The snippet imports the *package* and then uses a bare class name. It never reaches the
constructor. With the import corrected it does raise what FR-39 claims:

```
InvalidArgumentsError: wp_config must be an instance of WpConfigFile
```

So the README has **two** bugs in four lines, not one, and FR-39 as written would have the
rewriter fix the wrong one. Also worth folding into FR-39: `pip install -e .[dev]`
(line 71) fails for the same `wpconfigr` reason as the headline install, and the
`--wp-config` CLI examples on lines 42 and 51 are missing the trailing `\` after
`python -m wpdatabase2`, so they execute as a bare invocation and error on the missing
required flag. FR-39 should say "every runnable snippet in the README is verified by CI"
rather than enumerating; per rule #3, that is the only version of this requirement that
will stay true.

### FR-37 — CircleCI claims VERIFIED

`.circleci/config.yml` uses `circleci/python:3.7.1` and installs via `pip install -e .[dev]`,
which cannot succeed (same `wpconfigr` resolution failure). `test.py` shells out to
`coverage run -m unittest discover` — worth noting against rule #1's test-harness clause
that this is a thin 16-line wrapper around the standard runner, not a bespoke harness, so
FR-37's move to `uv run pytest` (or keeping unittest) is a straightforward swap.

---

## 9. What I would change in the PRD

**Must fix (factually wrong):**

1. **NFR-4** — MariaDB floor is **10.2**, not 10.1 (`ALTER USER` is 10.2+). Consider raising
   it to a supported LTS and testing that.
2. **NFR-5** — `mysqlclient` is `GPL-2.0-or-later` with **no** FOSS exception.
3. **FR-41** — `uv.lock` **is** shipped in the sdist; it is *inert*, not *absent*.
4. **FR-39** — the README example raises `NameError`, not `InvalidArgumentsError`.
5. **§2 bullet 2** — the `TypeError` is reached only on native-password servers; against
   MySQL 8+ the failure is `NotSupportedError` at `connect()`. Two causes, one swallow.

**Must fix (incomplete, and it makes FR-6 incomplete):**

6. **Addendum F** — add the ten gap categories in §1: top-level re-exports, leaked
   third-party names, the `WpDatabaseVersion` asymmetry, module import paths, exception
   constructor arities, getter-only properties, `_wordPressVersions` and its string keys,
   `__version__`-as-module, the CLI's exit-code-2 reality and dead `exit()` calls, and the
   absence of `__all__`.
7. **FR-5** — name the third, transitively dependent test (`test_connection.py:42-46`).

**Should decide (open questions the evidence now answers):**

8. **Open question #2 → hard-depend on `opentelemetry-api`.** 58 KB, one dependency, already
   the no-op layer; an extra obliges a hand-rolled shim against the repo's own rule #1.
9. **FR-27 → `phply`, or a forked `wpconfigr` with variable support.** `wpconfigger` and
   vendoring are functionally eliminated by FR-17. Record that FR-27 blocks FR-17 as well
   as FR-26.
10. **NFR-5 → declare `PyMySQL[rsa]`.** The residual non-TLS full-auth gap is intermittent
    and lands exactly on first-provisioning.

**Should add:**

11. **FR-18** — floor is WordPress 2.0 / db 3308 (876 of 884 tags parse); the four generator
    caveats (tolerate 404s, distinguish absent-vs-failed, version-tuple sort, tag-spelling
    normalisation); the fate of the two un-derivable keys `2540`/`2541`; and a staleness
    check on the generated artifact per rule #3.
12. **§2** — add "`wp_version` is `None` for every WordPress from 5.6 onward" as a fourth
    headline defect. It is the same class as the other three and currently unlisted.
13. **FR-38** — pin `mysql:8.0` **and** `mysql:8.4` explicitly; `mysql:8` resolves to 8.4.11
    and would skip the only server where `mysql_native_password` is still active. Decide
    whether calendar-versioned MySQL 26.x is in scope.
14. **FR-9** — record that `IDENTIFIED WITH <plugin> BY` is MySQL-only syntax *entirely*
    (MariaDB uses `IDENTIFIED VIA … USING`), and that `default_authentication_plugin` no
    longer exists on 8.4+. Both argue for omitting the plugin clause rather than detecting
    a default.
15. **FR-20** — as written it contradicts FR-1: "newer" and "not found" are both `None`
    today. Add a separate accessor rather than changing `wp_version`.

**Bottom line: the PRD is buildable as specified, on the stack it names.** Fix the five
factual errors, complete the frozen-surface inventory before writing the FR-6 suite, and
settle FR-27 — which is blocking more than the PRD currently says.
