---
title: Edge-case review — py-wordpress-database PRD
reviewed: prd.md (updated 2026-09-16) + addendum.md
against: wpdatabase2/ at e82e6aa
date: 2026-09-16
---

# Edge-case review

## Verdict

The PRD's **defect list is accurate and its direction is right**. What it does not yet have is a
**state model**. Its central omission is structural and recurs in every area below:

> `ensure()` is specified as converging a *database*, but the thing it actually has to converge is
> a **triple** — (database exists, user exists with the config's password, user is granted on that
> database) — whose three members can each be independently present, absent or wrong. FR-14/FR-15
> model existence as a property of the database alone, and FR-16 then makes its decision from that
> single bit.

Findings 1.1, 2.4 and 6.3/6.4 are that one omission seen from three sides, and together they mean
the PRD as written **fails the package's own headline use case** (section 3: a database pre-created
by `wp db create` or the Docker image's `MYSQL_DATABASE`, needing only the user and grants) and
**cannot recover from its own partial failure**.

The second structural omission is that **concurrency does not appear in the document at all** — no
FR, no NFR, no open question — while two of the four named scenarios (S1 ephemeral test databases,
S2 multi-tenant control plane) are concurrent by construction.

Severity counts: **8 Critical, 30 High, 21 Medium, 2 Low (61 findings).**

Severity means: **Critical** — as written, the requirement produces a wrong or unrecoverable
outcome in a mainstream case. **High** — a reachable real-world state with no specified behaviour,
where the two plausible implementations differ materially. **Medium** — a gap an implementer will
have to resolve by guessing. **Low** — worth a sentence so the next reader does not have to
rediscover it.

---

## 1. Idempotence boundaries (FR-7, FR-8, FR-12, FR-13, FR-16)

FR-7 is one sentence: *"`ensure()` is idempotent: running it against an already-correct database
and user succeeds and changes nothing."* It defines behaviour for exactly one state — "already
correct" — and says nothing about the partial states, which are the common ones.

### EC-1.1 — Database exists, user does not. **CRITICAL** — FR-7, FR-14, FR-15, FR-16

This is the **primary use case named in section 3** of the PRD: `wp db create` and the official
WordPress Docker image both create the database and explicitly do not create the user, and the
whole stated gap this package fills is the user plus grants.

FR-16 says *"a missing database triggers setup; an authentication or connectivity failure is
reported rather than treated as a reason to create things with admin credentials."* The existence
check connects **as the WordPress user** (`test_config()` uses `self._wp_connection.credentials`).
When the database exists but the user does not, the check yields *authentication failed* — and
FR-16 then mandates **reporting it rather than provisioning**. The PRD therefore specifies that
`ensure()` fails on the exact input it exists to handle.

FR-16 needs to name the triple explicitly: which of the three members is missing, which credential
set observed that, and which missing members justify the admin path.

### EC-1.2 — 1045 cannot distinguish "no such user" from "wrong password". **HIGH** — FR-14, FR-16

MySQL returns `ER_ACCESS_DENIED_ERROR` (1045) for both, deliberately, to prevent account
enumeration. FR-16 requires a decision that depends on telling them apart (a missing user should
provision; a wrong password is a different situation — see EC-1.12), and FR-14's four outcomes
collapse them into one. The distinction is **not obtainable from the WordPress user's connection at
all**; it requires probing `mysql.user` with the *admin* credentials.

Nothing in the PRD says admin credentials may be used for **inspection**. FR-11 ("used only for the
operations that require them") is ambiguous about whether inspection is such an operation, and the
decision matters for FR-28/NFR-1 too, because an inspection connection is another place credentials
travel.

### EC-1.3 — Mandatory `ALTER USER` silently resets an account the library may not own. **HIGH** — FR-8, FR-13

FR-8 mandates `ALTER USER ... IDENTIFIED BY` unconditionally, correctly noting `IF NOT EXISTS` will
not update an existing password. The uncovered consequence: if `'wpuser'@'%'` already exists and is
used by **something else** — a second WordPress install with its own wp-config.php, a backup job, a
monitoring agent — `ensure()` resets its password to whatever this config carries and breaks the
other consumer, with no ownership check and no warning. In S2 (multi-tenant) a `DB_USER` collision
between tenants is a plausible operator error with a blast radius the PRD never bounds.

No FR requires establishing that the existing account is "ours" (e.g. that it already has the
expected grant on the target database and nothing else) before mutating it.

### EC-1.4 — `ALTER USER` on every run contradicts "changes nothing". **MEDIUM** — FR-7

FR-8's unconditional `ALTER USER` is a **write on every invocation**. The server observes it:
`mysql.user.password_last_changed` advances, the audit log records a credential change, and any
monitoring on account modification fires. So `ensure()` is *convergent* but not "changes nothing" in
any sense an operator can verify. FR-7 does not define whether a no-op-equivalent write counts, and
it needs to, because the natural alternative — skip `ALTER USER` when the config's credentials
already authenticate — is a different algorithm with different failure modes (EC-1.7).

### EC-1.5 — A password-reuse policy makes the *second* run fail. **HIGH** — FR-7, FR-8

On MySQL 8.0+ with `password_history` or `password_reuse_interval` set (globally or per account),
re-setting the same password raises `ER_CREDENTIALS_CONTRADICT_TO_HISTORY` — "Cannot use these
credentials for '…' because they contradict the password history policy." FR-8's unconditional
`ALTER USER` therefore makes `ensure()` **non-idempotent by failing on re-run** on any server with a
reuse policy. That is FR-7 being violated *by* FR-8, inside the PRD, with no note of the
interaction.

### EC-1.6 — User exists with grants on a different database. **MEDIUM** — FR-7, FR-13

`GRANT` is additive. Running `ensure()` for tenant B against a user that already holds `tenantA.*`
leaves the user holding both. FR-13 ("scoped to the target database, never global") constrains what
`ensure()` *adds*, not what the account ends up with. Three defensible behaviours — leave unrelated
grants alone, revoke to converge on the declared state, or refuse and report the account as
over-privileged relative to this config — and the PRD picks none. "Already-correct" (FR-7) is
undefined for an account that is correct-plus-extra.

### EC-1.7 — Account identity is (user, host); `'u'@'localhost'` shadows `'u'@'%'`. **HIGH** — FR-8, FR-13

Addendum B hardcodes `'u'@'%'`. If `'wpuser'@'localhost'` already exists, MySQL's most-specific-host
matching means a connection **from localhost still matches the `localhost` account with its old
password**. `CREATE USER IF NOT EXISTS 'wpuser'@'%'` succeeds, `ALTER USER 'wpuser'@'%'` succeeds,
`GRANT` succeeds, `ensure()` reports success — and wp-config.php's credentials still fail, because
WordPress on the same host authenticates against the other account. The PRD treats an account as
named by its username; the server names it by the pair. Nothing in FR-8 or FR-13 addresses it.

### EC-1.8 — User exists and authenticates, but has no grant on the target database. **HIGH** — FR-7, FR-14, FR-15

An account with zero schema privileges connects fine. If the existence check is an auth check, this
state reads as "all correct". If the check is `SHOW DATABASES`/`information_schema`, it reads as
"database absent" (EC-2.5), and `CREATE DATABASE IF NOT EXISTS` then no-ops while the real
problem — the missing grant — is never fixed. This is the state EC-6.3's partial failure leaves, so
it is not hypothetical. FR-7's "already-correct … user" is never defined as including a grant check.

### EC-1.9 — `force=True` has no stated destructive scope. **HIGH** — FR-12

FR-12: *"`force=True` continues to skip the existence check and re-run setup."* It says what `force`
skips; it never says what `force` **does not do**. "Re-run setup" against a **populated** production
database is readable as including `DROP DATABASE` / re-create — and `force` is the one flag with
data-loss potential, reachable from `ensure(..., force=True)` on the frozen public surface. A
non-destructiveness guarantee ("`force` never drops, truncates or deletes; it only re-applies
create/alter/grant") belongs in the FR, together with a test that plants a table and asserts it
survives.

### EC-1.10 — Empty vs populated is never distinguished. **MEDIUM** — FR-7, FR-15

The empty/populated distinction is exactly what separates "safe to provision" from "a live site",
and nothing in the PRD requires `ensure()` to notice it. Three sub-cases with no specified
behaviour: the target database is empty (normal pre-install state); it holds a WordPress install
under the **configured** prefix (already provisioned — arguably success); it holds tables under a
**different** prefix or a non-WordPress schema entirely (the operator has almost certainly pointed
this config at the wrong database, and `ensure()` will cheerfully grant a new user full privileges
over someone else's data).

### EC-1.11 — `CREATE DATABASE` ignores `DB_CHARSET`/`DB_COLLATE`, and a mismatch reads as "correct". **HIGH** — FR-7, FR-8

wp-config.php declares `DB_CHARSET` (conventionally `utf8mb4`) and `DB_COLLATE`. Addendum B's
`CREATE DATABASE IF NOT EXISTS` carries **no `CHARACTER SET` / `COLLATE` clause**, so the database
is created with the server default — `latin1` on plenty of older and self-hosted servers. Two
uncovered scenarios: (a) creation silently diverges from the declared config; (b) the database
**already exists** with a conflicting character set, and FR-7 reports "already correct" for a
database that will mojibake every post WordPress writes. This is effectively unfixable once tables
exist, which makes it worth catching at provision time — and it is precisely the class of
"already-correct" that FR-7's one sentence cannot express.

### EC-1.12 — No declared direction of authority between wp-config.php and the server. **CRITICAL** — FR-7, FR-8, FR-16

The scenario "the WordPress user's password in wp-config.php has been rotated since the user was
created" has **no answer in the PRD**, and the reason is that the PRD never states whether
wp-config.php is:

- **declarative** — the server converges to the file, so a rotated password means `ALTER USER`
  (which then also means EC-1.3: `ensure()` will overwrite any account whose name matches); or
- **descriptive** — the server is truth, so a mismatch is an error to report (which then means
  FR-16 fails the rotation case, EC-1.1, and rotation cannot be converged at all).

Every finding in this section resolves differently depending on the answer. FR-7's phrase
"already-correct" hides the choice; it should be lifted into an explicit statement of authority
direction, with the mismatch behaviour enumerated per triple member. **This is the single highest-
value edit to the PRD.**

### EC-1.13 — FR-7 has no mechanical enforcement. **MEDIUM** — FR-7, FR-6, FR-38 (global rule #3)

FR-6 gives the frozen surface a compatibility suite; FR-38 gives the SQL divergences container
integration tests. FR-7 — the document's central behavioural claim — gets prose only. The check it
needs: run `ensure()` twice against each server in the FR-38 matrix and assert the second run
performs **no observable write** (no `password_last_changed` advance, no grant delta, no schema
delta). Note that writing that check forces EC-1.4's definition to be settled, which is the point.

---

## 2. Existence-check states (FR-14, FR-15, FR-16)

FR-14 enumerates exactly four outcomes: present-and-reachable, absent, authentication failed, host
unreachable. Every state below is reachable and fits none of them.

### EC-2.1 — TLS handshake and certificate-verification failure. **HIGH** — FR-14, NFR-1

A TLS failure (`OperationalError` 2026, "SSL connection error") or an identity-verification failure
under `ssl_verify_identity` maps, under FR-14's four buckets, to "host unreachable" — which is false
(the host answered) and sends the operator to the wrong remedy, defeating NFR-3.

Worse, **the PRD never says whether the connection uses TLS at all.** No FR mentions
`DB_HOST`-adjacent TLS configuration, wp-config.php's `MYSQL_CLIENT_FLAGS` / `MYSQL_SSL_*`
constants, or a CA bundle. NFR-5 notes that `caching_sha2_password` needs PyMySQL's `[rsa]` extra
*"over a non-TLS connection"* — so the PRD's own baseline is **admin credentials in plaintext over
the wire**, while NFR-1 restricts credential exposure only in logs, traces, exceptions and repr. An
NFR-1 clause on credentials *in transit* is missing.

### EC-2.2 — DNS failure, connection refused and filtered are three different problems. **MEDIUM** — FR-14, NFR-3

All three land in "host unreachable" with different causes and opposite remedies:
`socket.gaierror` (the name does not resolve — a typo in `DB_HOST`, service discovery not up yet),
`ECONNREFUSED` (name resolves, nothing listening — server not started, wrong port), and
`ETIMEDOUT`/`EHOSTUNREACH` (a security group or firewall is dropping it). In S1 and S3 these are
the three most common first-run failures. NFR-3 demands the failure say "what to do next"; under one
bucket it cannot.

### EC-2.3 — IPv6 literals and unix-socket `DB_HOST` are mis-parsed by the frozen setter. **MEDIUM** — FR-1, FR-14

Addendum F preserves `WpConnection.db_host`'s `value.split(':')` behaviour verbatim. Therefore:

- `DB_HOST = '::1'` → three parts, so host becomes `''` and the port is dropped;
- `DB_HOST = '[::1]:3307'` → host `'[',` port `':1]:3307'`-adjacent garbage;
- `DB_HOST = '/var/run/mysqld/mysqld.sock'` — **a legal WordPress `DB_HOST` and the default on many
  distro installs** — has no TCP host at all and no `unix_socket` parameter is ever passed.

Freezing the setter (FR-1 + addendum F) guarantees these stay broken; the PRD should either state
that socket and IPv6 hosts are unsupported (and raise a clear error) or carve them out of the freeze.

### EC-2.4 — Connect permitted, `USE` denied. **CRITICAL** — FR-14, FR-15, FR-16

An authenticated account with no privilege on the schema gets `ER_DBACCESS_DENIED_ERROR` (1044) on
`USE db`. This fits **none** of FR-14's four outcomes: the database is not absent, authentication
did not fail, and the host is reachable. An implementer must therefore pick one, and **both choices
are wrong**:

- "present and reachable" → `ensure()` returns success for a database WordPress cannot use;
- "absent" → `ensure()` runs setup, `CREATE DATABASE IF NOT EXISTS` no-ops, and the actual
  problem — the missing grant — is invisible in the result.

This is the most likely real-world state after a partial provision (EC-6.3) or a hand-rolled
`GRANT` with a typo'd database name, and FR-14 has no bucket for it.

### EC-2.5 — "Database existence specifically" (FR-15) is not obtainable as the WordPress user. **HIGH** — FR-15

FR-15 requires `does_database_exist()` to report *database existence specifically* rather than a
connection test. But both ways of asking — `SHOW DATABASES` and
`SELECT SCHEMA_NAME FROM information_schema.SCHEMATA` — are **filtered by privilege**: a schema the
connecting account has no privilege on is simply not returned, and is therefore reported **absent**.
So with the WordPress user's credentials, "absent" and "exists but not granted to me" are
indistinguishable — the privilege model does not permit the distinction FR-15 asserts.

FR-15 also never says **which credential set** the check runs under. That single unstated choice
determines whether FR-15 is implementable, whether EC-1.2's distinction is available, and whether
FR-11's "admin credentials only for operations that require them" is being honoured.

### EC-2.6 — Schema reachable, table not readable. **MEDIUM** — FR-14, FR-17, FR-20

`USE db` succeeds when the account has **any** privilege on the schema; `SELECT ... FROM
{prefix}options` then fails with `ER_TABLEACCESS_DENIED_ERROR` (1142). This is a distinct state from
EC-2.4 and a distinct `get_database_version()` failure from FR-20's two outcomes ("unrecognized or
newer" vs "no version found"). A read denial is not "no version found"; it is "I could not look".

### EC-2.7 — Server in read-only mode. **HIGH** — FR-14, FR-16, NFR-3

`super_read_only=ON`, an RDS/Aurora **reader endpoint**, `innodb_read_only`, or a Galera node in a
non-primary state: connection and authentication succeed, the existence check passes, and then
**every DDL in FR-8 fails** with `ER_OPTION_PREVENTS_STATEMENT` (1290). Pointing a provisioner at a
reader endpoint is an easy and common misconfiguration — and exactly the topology S2's control plane
would have. FR-14's state model has no notion of **write-capability**, so the failure arrives deep
inside provisioning as a driver-level message instead of at the gate, and NFR-3's "what to do next"
has nothing to work from. (Also unaddressed: `offline_mode=ON`, and a server started with
`--skip-grant-tables`, where authentication is bypassed entirely and every grant statement fails.)

### EC-2.8 — Admin credentials valid but insufficiently privileged. **HIGH** — FR-14, FR-16, FR-8

An admin account can authenticate and still lack `CREATE USER`, `GRANT OPTION` on the target, or
`RELOAD` (which FR-8's `FLUSH PRIVILEGES` requires — see EC-6.8). FR-14's "authentication failed" is
a different state from "authenticated, not authorised", and the PRD has no outcome for the latter
and **no requirement for a pre-flight privilege check** on the admin credentials before the first
DDL. Without one, insufficient admin privilege is discovered mid-sequence and lands in EC-6.3's
half-provisioned state rather than failing cleanly before any change.

### EC-2.9 — Connection succeeds, then times out mid-query; no timeout or retry policy exists. **HIGH** — FR-14, FR-16, NFR-6 (global rule #1)

Two sub-cases, neither covered:

- **Idle timeout between statements.** The sequence holds one connection across `CREATE DATABASE` →
  `USE` → `CREATE USER` → `ALTER USER` → `GRANT` → `FLUSH`. A stall (a metadata-lock wait, a paused
  container) can trip `wait_timeout` and produce "MySQL server has gone away" (2006) or "Lost
  connection during query" (2013) **mid-sequence** — EC-6.3 again.
- **Client gives up while the server is still working.** A `CREATE USER` that times out on the
  client may well have **committed** on the server. So neither retrying nor reporting failure is
  obviously correct, and the PRD says nothing about which.

Compounding this: **no FR sets connect or read timeouts at all**, no NFR gives a latency budget, and
no FR states whether any operation may be retried. Retry/backoff is explicitly named in global rule
#1 as a domain not to hand-roll, yet neither FR-33's extras nor NFR-6 names a retry library — so an
implementer will write one inline, exactly the pattern the rule exists to prevent. Finally, a 2013
raised by FR-14's *check* is indistinguishable under the four buckets from "unreachable", which
routes `ensure()` to "report and stop" when the right action may be "retry once".

### EC-2.10 — FR-14 requires distinguishing but specifies no representation; FR-15's bool throws it away. **HIGH** — FR-14, FR-15, FR-1, NFR-3

FR-14 says the check "distinguishes, as separate outcomes" — and never says **how the caller sees
the distinction**. FR-15 then requires `test_config()` to return a truthful **boolean**, which
discards it. The memlog records a decision — *"define a wpdatabase2 exception hierarchy and never
leak driver exception types"* — but **no FR states it**, and FR-1 freezes only three exception names
with no requirement that the new states be representable. Result: FR-14's distinctions exist inside
the implementation and are unavailable to a caller who wants to switch on them, and to the release
notes' compatibility story. The exception hierarchy (or a result enum) needs to be an FR.

### EC-2.11 — No terminal "unknown" bucket, colliding with NFR-2. **MEDIUM** — FR-14, NFR-2

NFR-2 bans bare `except Exception` that converts a defect into a benign result — correctly, it is
the root cause of three observed defects. But FR-14's four buckets are **closed**, so an
unanticipated driver error has nowhere to go: the implementer either violates NFR-2 or lets a driver
exception type escape (violating the unstated decision in EC-2.10). FR-14 needs a fifth, explicitly
non-benign terminal outcome — "unexpected failure, cause preserved, never interpreted as absent".

---

## 3. Identifier validation (FR-10)

FR-10 requires that identifiers "are validated before reaching SQL" and that identifiers which
"cannot be parameterized are quoted and escaped rather than interpolated raw." **It never states the
rule.** That absence is the finding; here is what the rule has to answer.

### EC-3.1 — No legal set stated, and the three relevant grammars differ. **HIGH** — FR-10

There are three different rules in play and the PRD treats them as one:

- **Unquoted identifier**: `[0-9a-zA-Z$_]` plus U+0080–U+FFFF.
- **Backtick-quoted identifier**: any character except U+0000 — *but* a MySQL schema is a filesystem
  directory, so a **database** name additionally may not contain `/`, `\` or `.` and may not end in
  whitespace, even quoted (`ER_WRONG_DB_NAME`, 1102).
- **User name**: a string literal, with none of the database-name restrictions.

So `` CREATE DATABASE `a.b` `` fails while `CREATE USER 'a.b'@'%'` succeeds. Which set FR-10
validates against is unspecified, and `InvalidDatabaseNameError(name)` carries **no reason field**,
so the error cannot say which rule was broken — NFR-3 unsatisfiable by construction.

### EC-3.2 — Length limits differ by server and are not 64. **HIGH** — FR-10, NFR-4, FR-38

Schema identifiers are 64 characters. **User names are not**: MySQL allows 32 (raised from 16 in
5.7.8); MariaDB allows 80 (verify the exact version floor before encoding it). So a 40-character
`DB_USER` succeeds on MariaDB and fails on MySQL with `ER_WRONG_STRING_LENGTH` (1470). FR-10, NFR-4
and FR-38 are all silent on length, meaning the validator's rule is **server-dependent** and the
PRD's matrix requirement does not mention it.

Two related subtleties also unaddressed: the limit is in *characters*, while a database name is
stored on disk in a mangled encoding, so 64 multi-byte characters can exceed the filename limit; and
`$table_prefix` + a WordPress table name must also fit in 64, which bounds the legal prefix length
(FR-17).

### EC-3.3 — Identifier context and string-literal context are conflated. **HIGH** — FR-10, NFR-1

FR-10 speaks of "identifiers" uniformly, but addendum B's SQL puts the **database name in identifier
context** (backtick-quoted; an embedded backtick is escaped by **doubling**) and the **user name and
password in string-literal context** (single-quoted; escaping depends on backslashes and on whether
`NO_BACKSLASH_ESCAPES` is in the session's `sql_mode`). Applying the wrong escaping to either
position **is** the injection. Nothing in FR-10 or NFR-1 distinguishes the two contexts, and nothing
requires a test that plants a backtick, a single quote and a backslash in *each* position.

### EC-3.4 — `GRANT ... ON db.*` treats the database name as a LIKE pattern, so `wp_`-named databases are over-granted. **CRITICAL** — FR-13, FR-10, NFR-1

In MySQL, the database part of a `GRANT` is matched as a **pattern**: `_` and `%` are wildcards. So

```sql
GRANT ALL PRIVILEGES ON `wp_myblog`.* TO 'u'@'%';
```

grants on every schema matching `wp_myblog` **as a pattern** — `wpXmyblog`, `wp1myblog`, and so on.
Any database whose name contains an underscore — i.e. **every database following the conventional
`wp_` naming** — is silently granted more broadly than FR-13 promises and than NFR-1's
least-privilege claim asserts. Scoping to exactly one schema requires escaping the wildcard
(`` ON `wp\_myblog`.* ``), which is **not** what identifier quoting does, so FR-10's "quote and
escape" does not catch it. The same wildcard semantics apply to the **host** part of an account, so
a host containing `_` or `%` is a pattern too (EC-3.5).

### EC-3.5 — The `%` host is hardcoded and unconfigurable. **MEDIUM** — FR-13, NFR-1

Addendum B fixes the account at `'u'@'%'` — **any host**, the least restrictive option available —
while NFR-1 claims "grants are least-privilege and database-scoped". The least-privilege claim
covers only the *privilege* axis; on the *host* axis the PRD specifies the maximum. S2's
multi-tenant host would want `'u'@'10.%'` or a specific application host, and no FR makes the host a
parameter (nor is it on the frozen surface, so adding it is compatible). Note also that `%` as a
literal host is the only reason EC-1.7's shadowing is invisible.

### EC-3.6 — Trailing space: illegal in a database name, legal *and significant* in a user name. **MEDIUM** — FR-10

A trailing space makes a database name invalid (`ER_WRONG_DB_NAME`). For a **user** name it is legal
and significant: `'wp '@'%'` and `'wp'@'%'` are two distinct accounts. So a stray trailing space in
wp-config.php's `DB_USER` provisions a **second account**, leaves two near-identical rows in
`mysql.user`, and — because WordPress will send the same trailing space when it connects — actually
*works*, which makes it far harder to spot later.

FR-10 does not say whether identifiers are trimmed, rejected, or passed through. Passing through is
the only choice faithful to what WordPress itself sends; rejecting is probably the right product
answer; **normalising silently is the one clearly wrong answer** and is what an unguided implementer
will do. The PRD expresses no preference.

### EC-3.7 — `lower_case_table_names` makes FR-7's idempotence server-configuration-dependent. **MEDIUM** — FR-7, FR-10

Database names are compared according to `lower_case_table_names` (0 on Linux, 1 on Windows, 2 on
macOS). On a case-insensitive server `WpSite` and `wpsite` are the **same** database, so "already
exists" is true for a differently-cased name; on Linux they are two databases. So whether `ensure()`
is idempotent across a case change depends on the server's platform, and no FR mentions it. (User
names are separately case-**sensitive** always, because `mysql.user` uses a binary collation — a
third rule.)

### EC-3.8 — Unicode: BMP limits and normalisation. **LOW** — FR-10 (global rule #1)

Unquoted identifiers permit U+0080–U+FFFF only, so an astral-plane character (an emoji) is not a
legal unquoted identifier. More consequentially, two visually identical names in different
normalisation forms (NFC vs NFD) are **different identifiers** — so `ensure()` can create a second
database the operator believes already exists. Global rule #1 names Unicode normalisation as a
do-not-hand-roll domain: if FR-10's validator normalises it needs a library and the rule's ADR; if
it does not, the PRD should say so explicitly so the next reader stops looking.

### EC-3.9 — Empty string, `None`, and missing-vs-empty config keys. **MEDIUM** — FR-10, FR-26, FR-17

`DB_NAME` absent from wp-config.php yields `None`; `define('DB_NAME', '')` yields `''`.
`WpConnection`'s setter is a bare assignment and accepts both (only `db_host=None` is special-cased),
and `InvalidDatabaseNameError('')` renders as `"" is not a valid database name.` FR-10 never names
empty or `None` as invalid. And since FR-26/FR-27 make config reading a **provider**, "the key was
missing" and "the key was present and empty" are different *provider* outcomes needing different
errors — neither specified. The same gap covers the case addendum D flags: the reader may be unable
to find `$table_prefix` **at all**, because it is a variable rather than a `define()`, and FR-17
depends on it.

### EC-3.10 — Reserved words are legal when quoted, which turns FR-10 into a *scope* problem. **HIGH** — FR-10, FR-6, FR-38 (global rule #4)

`` CREATE DATABASE `select` `` is valid, so a validator that rejects reserved words rejects what
MySQL accepts — and a validator that *allows* them must guarantee correct quoting at **every** site
that names the database: `CREATE DATABASE`, `USE`, `GRANT ... ON x.*`, the existence probe, and any
`information_schema` lookup — where the name is a **string**, not an identifier, needing string
escaping again (a third context after EC-3.3's two).

FR-10 states the rule but requires no per-path guarantee, and per global rule #4 the test that
matters attacks the **scope**: plant a reserved-word, backtick-bearing, underscore-bearing name and
assert that *every* SQL construction site handles it, with the site list derived from the code rather
than hand-enumerated. Nothing in FR-6 or FR-38 does this.

### EC-3.11 — System schemas are not forbidden as `DB_NAME`. **MEDIUM** — FR-10, FR-13, NFR-1

`ensure()` pointed at `DB_NAME = mysql` would run `GRANT ALL PRIVILEGES ON mysql.*` to the WordPress
user — an instant privilege escalation to full server control, from a one-word typo in a config
file. `information_schema`, `performance_schema` and `sys` are similar. No FR excludes them, and this
is the cheapest possible validation rule to add.

---

## 4. Version reporting (FR-17 – FR-20)

### EC-4.1 — `$table_prefix` is concatenated into an identifier but falls outside FR-10's stated scope. **HIGH** — FR-17, FR-10, NFR-1

FR-10 covers *"Database and user identifiers."* FR-17 introduces a **third** value that reaches SQL:
`$table_prefix`, concatenated into a table identifier (`` `{prefix}options` ``). A prefix from a
hand-edited wp-config.php can contain a backtick, a quote, a `;`, or — most insidiously — a **dot**
(`othersite.wp_`), which redirects the query to a different schema entirely. The prefix is read by
the regex-based config provider FR-26/FR-27 discuss, so it is attacker- or typo-reachable from a
file.

WordPress itself enforces `^[a-zA-Z0-9_]+$` on the prefix (`wp-settings.php` dies with "`$table_prefix`
in `wp-config.php` can only contain numbers, letters, and underscores"). That is an authoritative
rule available for free, and the PRD cites none. FR-10's scope should be widened to name the prefix.

### EC-4.2 — Multisite keeps the network's `db_version` somewhere else entirely. **HIGH** — FR-17, FR-18, FR-19, FR-20

In a multisite network the **network** `db_version` (and `initial_db_version`) live in
`{prefix}sitemeta`, written by the network upgrade path — not in `{prefix}options`. Meanwhile blog 1
uses `{prefix}options` and every subsite uses `{prefix}{blog_id}_options`, which carry **no**
`db_version` row at all.

So FR-17's "honour `$table_prefix`" reads blog 1's options table and can report a version that
disagrees with the network's actual schema state. The PRD never mentions multisite, `sitemeta`,
`MULTISITE`/`SUBDOMAIN_INSTALL`, or `$blog_id`, and "the WordPress version in this database" is not
even a single-valued question on a network install.

### EC-4.3 — "No version found" is doing triple duty. **HIGH** — FR-20, FR-17

FR-20 distinguishes "unrecognized or newer `db_version`" from "no version found". The second bucket
hides three states with three different operator meanings:

1. **The options table does not exist** (`ER_NO_SUCH_TABLE`, 1146) — the normal state of a freshly
   created, empty database: *WordPress is not installed yet.* (Today this raises rather than
   returning "not found", and FR-20 does not say it shouldn't.)
2. **The table exists, the `db_version` row does not** — a partial import, a deleted row, or an
   options table belonging to a *different* prefix: *the install is broken.*
3. **The row exists but its value is unusable** — `option_value` is `LONGTEXT`, so `''`, `'0'` or
   arbitrary text are all storable: *data corruption.*

Add EC-2.6's fourth: *the table exists and I was not allowed to read it.*

There is also a representation problem on the frozen surface: `get_database_version()` returns
**`None`** when the row is missing, while FR-20 talks about `WpDatabaseVersion.wp_version` returning
`None` for an unknown value. Two different `None`s at two different levels, and a caller cannot tell
"no row" from "row present, release unknown" without inspecting which object came back.

### EC-4.4 — `db_version` typing, and FR-19's comparison. **HIGH** — FR-19, FR-20, FR-18

`option_value` arrives as text (`str`, or `bytes` depending on driver and charset), and the current
map is keyed by **strings** (`"38590"`). FR-19 requires *"the highest release whose `db_version` is
less than or equal to the observed value"* — an **ordering** comparison, which on strings
mis-orders: `"9872" > "58975"` lexicographically, so a WordPress 2.7 database would resolve above a
6.8 one. Nothing in FR-19 or FR-20 states that the observed value is coerced to an integer, or what
happens when it cannot be (EC-4.3 case 3).

### EC-4.5 — A `db_version` below the map's floor has no answer, and the map declares no bounds. **MEDIUM** — FR-19, FR-20, FR-18 (global rule #4)

FR-19 defines only the upper direction. If the observed value is **below** the lowest entry in the
shipped table, the candidate set is empty and FR-19's rule yields nothing — and addendum C says
outright that *"how far back tags carry a parseable `$wp_db_version`"* is unverified, so *"the
derivation has a floor still to establish."* FR-20 covers "unrecognized or newer", not
"older than anything known", which is a distinguishable and actionable answer ("your install
predates this library's map; it is at least this old").

Relatedly, nothing requires the shipped data to **declare its own floor and ceiling** so the runtime
can say which edge it fell off, and nothing checks that the shipped table still covers what
`stable-check` currently lists. FR-18 correctly forbids hand-enumeration and names a refresh
command, but per global rule #4 the generator's **scope** (which tags, from which floor) is exactly
the thing that will drift silently, and no check examines it.

### EC-4.6 — The connection-only constructor has no `$table_prefix` at all. **HIGH** — FR-17, FR-26, FR-1

`WpDatabase(wp_connection=...)` is on the frozen surface (addendum F) and is precisely the
**dependency-free core path** FR-26 exists to unblock — no wp-config.php, therefore **no prefix**.
FR-17 says version lookup honours `$table_prefix`; on this path there is none. Three behaviours are
available — default to `wp_`, raise, or discover prefixes by scanning `information_schema.TABLES`
for `%options` — and the PRD specifies none. If it scans, EC-4.7 follows.

### EC-4.7 — Multiple installs sharing one database, with different prefixes. **MEDIUM** — FR-17, FR-19

This is a **supported, documented WordPress deployment** — the entire reason `$table_prefix` is
configurable — and each install has its own `{prefix}options.db_version`, potentially different.
FR-17 resolves it implicitly by reading *the* config's prefix, which works only when a config was
supplied (EC-4.6). Under discovery, multiple matching prefixes make the answer ambiguous with no
specified tie-break, and "the WordPress version of this database" is the wrong shape of question —
the honest return is a per-prefix mapping, which the frozen `WpDatabaseVersion` cannot express.

### EC-4.8 — `CUSTOM_USER_TABLE` and a non-default `$blog_id`. **LOW** — FR-17

wp-config.php may define `CUSTOM_USER_TABLE`/`CUSTOM_USER_META_TABLE`, and a non-default `$blog_id`
changes which options table is authoritative. Neither affects `db_version` directly, but both signal
that "prefix + fixed table name" is an incomplete model of where WordPress state lives, and FR-17
asserts it as complete.

---

## 5. Credentials and providers (FR-21 – FR-25, with NFR-1)

### EC-5.1 — "Malformed" flattens six distinct cases, and FR-25's word "exactly" rejects the most likely real input. **HIGH** — FR-25, FR-24

FR-25 makes the AWS secret's shape explicit and validated "with a clear error when it is not met."
One requirement, six situations:

1. **Not JSON at all** — a plain password string, which AWS Secrets Manager fully supports and which
   many operators store; `json.loads` raises `JSONDecodeError`.
2. **Valid JSON but not an object** — a bare JSON string or array.
3. **Object missing `username` or `password`.**
4. **Right keys, non-string values** — `"password": 12345`, produced constantly by console users;
   note `WpCredentials`'s `(not username) != (not password)` check also mis-handles falsy-but-present
   values like `0` and `""`.
5. **Extra keys** — an **RDS-managed** secret carries `engine`, `host`, `port`, `dbname`,
   `dbInstanceIdentifier` alongside `username`/`password`. FR-25 describes the contract as the secret
   containing *"exactly `username` and `password`"*, which would **reject the single most likely real
   input in AWS**. Whether extra keys are tolerated (and whether `host`/`port`/`dbname` should be
   *used*) is a product decision the PRD frames as a validation detail.
6. **`SecretBinary` rather than `SecretString`** — see EC-5.2.

### EC-5.2 — `SecretBinary` produces a `KeyError`, not a clear error. **MEDIUM** — FR-25, NFR-2, NFR-3

`Secret.as_string` does `response['SecretString']` unconditionally. A secret stored as binary raises
`KeyError: 'SecretString'` from inside a property getter — the opposite of FR-25's "clear error" and
NFR-3's "what to do next", and reached through EC-5.6's misleading call path.

### EC-5.3 — NFR-1 forbids naming the secret, so FR-25's actionable error cannot say which secret failed. **HIGH** — NFR-1, FR-25, NFR-3

NFR-1 states that **no secret *identifier*** appears in logs, traces, exception messages or repr.
FR-25 requires a clear error when the shape is wrong, and NFR-3 requires the failure to say what was
attempted against what target. Under NFR-1 the error may name neither the value nor the secret — so
the best available message is "a required key was missing", with no way to tell the operator **which
secret to fix**. In a control plane handling many tenants' secrets (S2) that is not diagnosable.

This is a genuine, unresolved conflict inside the PRD. NFR-1's inclusion of *identifiers* (not just
values) is unusually strict and is not justified anywhere; it needs either a rationale plus a safe
alternative (a stable hash, or a caller-supplied opaque label) or relaxation to values only.

### EC-5.4 — Credentials are cached for the object's lifetime with no invalidation. **HIGH** — FR-21, FR-22, FR-14

`Secret.as_string` memoises (`if self._secret_string: return …`), and `_resolve_secret()` copies into
`_username`/`_password` then drops the `Secret`. There is **no TTL, no refetch, no invalidation**.
Concretely: a long-lived process (S2) holding a `WpCredentials` across an AWS rotation authenticates
with the stale password, gets 1045, and FR-14 reports "authentication failed" — with **no indication
that the cause is a stale cache** rather than a wrong secret. The operator's remedy (restart the
process) is not derivable from the error.

No FR says whether a provider result may be cached, for how long, or whether an authentication
failure should trigger a single refetch-and-retry. This is the "secret rotated between fetch and
use" case, and it has no requirement.

### EC-5.5 — FR-11's guarantee stops at the instance boundary. **MEDIUM** — FR-11, NFR-1

FR-11: admin credentials "are not retained on the instance after `ensure()` completes." True and
cheap — the frozen `ensure_database_setup(admin_credentials, …)` takes them per call. But the
plaintext lives on in **the caller's `WpCredentials`** (`_username`/`_password`) and in the
`Secret`'s `_secret_string`, neither of which is required to be scrubbed or zeroizable, and both of
which outlive `ensure()`. NFR-1 covers logs, traces, messages and repr — not memory lifetime. So
FR-11 reads like a credential-lifetime guarantee and delivers only an attribute-cleanup one; the
distinction should be stated rather than left for a reader to assume the stronger claim.

### EC-5.6 — Lazy resolution on property access routes provider failures into FR-14's *connection* outcomes. **CRITICAL** — FR-21 – FR-25, FR-14, FR-16, FR-24, FR-28

The design the task names is real and its consequences reach FR-14's state machine.
`credentials.username` triggers `_resolve_secret()` → `Secret.as_dict` → `boto3.client(...)` →
`get_secret_value`. The access site is inside `_connect()`:

```python
connector.connect(host=…, user=credentials.username, password=credentials.password)
```

So a `RegionNotKnownError`, a botocore `NoCredentialsError` or `ClientError`
(`AccessDeniedException`, `ResourceNotFoundException`, throttling), a `JSONDecodeError` (EC-5.1) or a
`KeyError` (EC-5.2) is raised from inside what both the caller and FR-14 believe is a **connection
attempt**. Five specific gaps:

- **FR-14 has no "credentials could not be obtained" outcome**, so a provider failure is classified
  as one of its four *connection* outcomes — most plausibly "host unreachable" or "authentication
  failed". FR-16 then makes a **provisioning decision** from a misclassified failure: either
  reporting a connectivity problem that does not exist, or taking the admin path in response to a
  secrets-manager outage.
- **FR-24's actionable error has no place to be raised.** FR-24 forbids a bare `ImportError`/
  `ModuleNotFoundError` when a provider's extra is missing — but on the frozen surface the import is
  triggered by a **property getter** reached from inside `connect()`. An `ImportError` from
  `credentials.username` is exactly what FR-24 prohibits, and no FR says where the import is
  attempted or when the extra's presence is checked.
- **Two properties, one fetch.** `_resolve_secret()` is called from both getters, so the network call
  lands mid-expression in an argument list, and if the memo were ever invalidated (EC-5.4) the two
  properties could observe **different secret versions**.
- **FR-28/FR-29 cannot instrument it.** A structured event or span for "fetch credentials" cannot
  bracket an operation whose timing is decided by attribute access.
- **No eager-validation seam.** No FR requires credentials to be resolvable on demand *but validated
  eagerly*, and the frozen surface offers no `resolve()`/`validate()` entry point. Since FR-1 freezes
  the lazy properties, the fix has to be an additive seam plus an FR that says `ensure()` resolves
  and validates credentials **before** the first connection attempt.

### EC-5.7 — No thread-safety contract anywhere, and `_resolve_secret()` can tear. **HIGH** — FR-21, FR-29, S2

`_resolve_secret()` is an unsynchronised check-then-act across three fields. Concretely:

- Two threads both see `self._secret` truthy and both call `get_secret_value` — double request,
  double audit entry, and two concurrent `boto3.client`/`boto3.session.Session()` constructions,
  which are not documented as safe to perform concurrently in older botocore.
- **Torn credentials:** thread A sets `_username` and is preempted before `_password`; thread B,
  refetching mid-rotation, sets `_password` from a **newer** secret. The object ends up with A's
  username and B's password and authenticates as neither.
- `Secret._client` and `Secret._secret_string` have the same unsynchronised memo.

**No FR or NFR states a thread-safety contract for anything in the package** — not `WpCredentials`,
not `Secret`, not `WpDatabase`/`WpConnection`, whose setters are plain assignments and whose
`db_host` setter mutates `_db_port` as a documented side effect (a race with an ordering-dependent
outcome). S2 is a concurrent service by definition. Stating "these objects are not thread-safe; use
one per operation" would be a legitimate answer — but it has to be stated.

### EC-5.8 — FR-29's correlation ID has no propagation mechanism and no seam. **MEDIUM** — FR-29, FR-1

FR-29 requires a correlation identifier "propagated across the calls it fans out into" and never
says **through what**: an explicit parameter (impossible — the frozen signatures in addendum F have
nowhere to put it), a thread-local (breaks across async and thread pools), or a `contextvar` (the
right answer, and the one that survives EC-5.7's concurrency). Since FR-1 freezes the signatures,
the mechanism is a real constraint on the design and belongs in the FR.

### EC-5.9 — FR-23's second provider proves the interface only along the axis AWS already covers. **HIGH** — FR-21, FR-23, FR-24, FR-25 (global rule #4)

FR-23 exists to "prove the interface is not AWS-shaped", and Azure Key Vault has **the same shape**
as AWS Secrets Manager: a named secret in a cloud service, fetched with ambient credentials,
returning an opaque string. Adding it exercises none of the axes where the interface is most likely
still AWS-shaped:

- a secret that needs a **version or label pin** (Key Vault versions, AWS `VersionStage`) — the PRD
  has no notion of secret versioning, which is also EC-5.4's missing lever;
- a provider whose own credentials **expire and need refresh** (Vault leases, STS session tokens);
- a provider returning a **natively structured** secret rather than JSON-in-a-string, which is where
  FR-25's shape validation would have to generalise;
- a **local, dependency-free** provider — environment variables, a file, or the existing
  `--admin-username/--admin-password` path. This is the one every S1/S3 user actually wants, it needs
  no extra at all, and FR-21's "the base install carries none of them" appears to exclude it from the
  base install on principle.

Per global rule #4: the guard proves the rule but not its reach. Adding a second cloud-secret-manager
provider leaves version pinning, expiry/refresh and non-JSON shapes untested, and FR-21 + FR-23 can
both be marked done with the interface still AWS-shaped.

---

## 6. Concurrency and partial failure

**Concurrency appears nowhere in the PRD** — not in section 7, not in section 8's NFRs, not in
section 10's open questions. That is itself the top-level finding for this area.

### EC-6.1 — Two `ensure()` calls racing can report success to a caller whose credentials were just overwritten. **CRITICAL** — FR-7, FR-8

Two concurrent `ensure()` calls for the same database both see it absent, both connect as admin, and
both run FR-8's sequence. `CREATE DATABASE IF NOT EXISTS` is benign; `ALTER USER ... IDENTIFIED BY`
is not. If the two callers hold **different passwords for the same `DB_USER`** — two wp-config.php
files, or a rotation in flight — the **last writer wins**, and the other caller's `ensure()` returns
success having left a system in which its own credentials no longer work. `ensure()` would report
success for a state its own closing validation would reject.

FR-7's idempotence is about repetition **in time**; this is repetition **in parallel**, and the
PRD never draws the distinction. For S1 (parallel test sessions — `pytest-xdist` is the normal way
to run a suite) and S2 (a control plane serving concurrent provisioning requests), concurrent
`ensure()` is the **default condition**, not an edge case.

Nothing specifies whether `ensure()` should serialise (e.g. `SELECT GET_LOCK('wpdatabase2:<db>', n)`),
nor what it should do when it cannot acquire the lock.

### EC-6.2 — Concurrent DDL error modes are unspecified, and no retry is permitted. **HIGH** — FR-8, FR-14, NFR-6

Under concurrent DDL, MySQL 8 can return `ER_LOCK_DEADLOCK` (1213) or
`ER_LOCK_WAIT_TIMEOUT` (1205) from data-dictionary operations, and concurrent `CREATE USER` can
surface as `ER_CANNOT_USER` or a duplicate-key failure on `mysql.user` despite `IF NOT EXISTS`.
These are **transient and retryable** — which is exactly what EC-2.9 shows the PRD has no policy
for. Without a retry requirement (and a library, per global rule #1), a race produces a hard failure
that leaves EC-6.3's half-provisioned state.

### EC-6.3 — DDL auto-commits, so partial failure leaves a durable half-provisioned state, and no FR governs it. **CRITICAL** — FR-7, FR-8, NFR-3

The PRD requires **nothing** about partial failure. And the sequence is multi-statement DDL, which in
MySQL is **non-transactional and implicitly committing**: each of `CREATE DATABASE`, `CREATE USER`,
`ALTER USER`, `GRANT` and `FLUSH PRIVILEGES` commits, no rollback is available, and the current
implementation's `conn.commit()` after the DDL is decorative.

So any failure between statements — EC-2.7's read-only server, EC-2.8's under-privileged admin,
EC-2.9's mid-sequence timeout, a `max_connections`/`max_user_connections` refusal, or the process
being killed — leaves a **durable, inconsistent state**: a database with no user, or a user with no
grant, or a grant applied but `FLUSH` not run.

The PRD says nothing about whether that state is acceptable, whether `ensure()` must attempt
cleanup (it largely **cannot** safely — dropping a database it may not have created is destructive,
and it keeps no record of what *this run* created), or whether it must at minimum report **precisely
how far it got**. NFR-3 requires a failure to state "what was attempted, against what target, and
what to do next" — and for a half-provision, "what to do next" depends entirely on which step
failed, so NFR-3 needs **step-level attribution** that no FR requires (EC-6.5).

### EC-6.4 — The specified state machine cannot recover from its own partial failure. **CRITICAL** — FR-16, FR-12, FR-14

This is EC-6.3's consequence and the review's sharpest finding. Re-running `ensure()` after a
"database created, user missing" failure hits **EC-1.1 exactly**: the existence check sees the
database present, and FR-16 therefore does not take the setup path. The normal remedy for a failed
idempotent operation — *run it again* — is specified not to work.

`force=True` (FR-12) is the only escape, and it is nowhere documented as the remedy for this, while
being the one flag whose destructive scope is unstated (EC-1.9). A PRD whose recovery path is an
undocumented use of its most dangerous flag needs the triple-based state model from EC-1.1 instead.

### EC-6.5 — No step-level attribution in failures. **HIGH** — NFR-3, FR-28

FR-28 requires structured events carrying "the operation, target database, outcome and timing", which
reads as per-`ensure()` granularity. NFR-3's "what to do next" for a half-provision requires
per-**statement** granularity: which of create-database / create-user / set-password / grant / flush
succeeded, and which failed. FR-30's spans would naturally carry this, but FR-30 is an assumption
behind an extra (and open question 2), so the diagnosis NFR-3 promises would be available only to
callers who installed the tracing extra. Step attribution needs to be in the **error**, not only in
the telemetry.

### EC-6.6 — No FR fixes the order of operations, though the order decides which ambiguous state a failure leaves. **MEDIUM** — FR-8

Addendum B lists the SQL in an order; no FR makes it normative. The order matters for failure
quality: creating the **user first** leaves, on failure, an unprivileged orphan account — harmless,
obvious, trivially revocable. Creating the **database first** leaves an ungranted database, which is
invisible to the WordPress user and indistinguishable from absent (EC-2.4/EC-2.5) — the worst
available residue. "Order operations so that a partial failure leaves the least ambiguous state" is
a cheap, checkable requirement the PRD does not make.

### EC-6.7 — No read-back verification of the achieved triple; FR-15 makes the closing check weaker than it is today. **HIGH** — FR-15, FR-7, FR-16

Today `ensure()` ends with `test_config(throw=True)` — a vestigial read-back. FR-15 narrows
`test_config()` to a truthful connection test, so the closing validation would verify **less** than
the current (broken) one intended. Nothing in the PRD requires `ensure()` to finish by confirming the
**achieved state** rather than inferring success from statements not having raised: that the
WordPress user can connect, *and* `USE` the database, *and* see it in `SHOW DATABASES`, *and* (given
EC-3.4) hold a grant scoped to that database alone. Every finding in areas 1, 2 and 6 would be caught
by that one read-back, which makes its absence the highest-leverage omission after EC-1.12.

### EC-6.8 — `FLUSH PRIVILEGES` is unnecessary here, adds an unstated privilege requirement, and hides the case it appears to handle. **MEDIUM** — FR-8, FR-11

`GRANT`, `CREATE USER` and `ALTER USER` update the in-memory privilege cache automatically; `FLUSH
PRIVILEGES` is needed only after **direct modification of the `mysql` grant tables**. FR-8 mandates
it anyway. Three uncovered consequences:

- It requires the **`RELOAD`** privilege, so FR-8 silently adds a requirement to the admin account
  that no FR states — and an admin with `CREATE USER` + `GRANT OPTION` but no `RELOAD` fails at the
  last step of an otherwise complete provision (EC-6.3 again, for no benefit).
- It creates a false impression of handling **live sessions**, and does not: an already-open
  WordPress connection keeps the privileges it had at connect time, so a password change (EC-1.3,
  EC-1.12) does not disturb live connections and a revoked grant does not take effect until the
  session reconnects. If `ensure()` is expected to converge a **running** site, that needs saying.
- On MariaDB and MySQL it is a per-server cost on a path FR-7 claims changes nothing.

### EC-6.9 — The admin connection is not required to be closed on the failure path. **MEDIUM** — FR-11, NFR-1

FR-11 governs whether admin credentials are *retained as attributes*. It says nothing about the
**admin session**, which the current code closes only on the success path. A leaked connection holds
an authenticated admin session — with its privileges — for as long as the process lives or
`wait_timeout` allows. That is a credential-lifetime concern of the same kind FR-11 addresses, on a
path FR-11 does not reach, and it is reached by every failure in EC-6.3.

---

## Recommended edits, in order of leverage

1. **EC-1.12 + EC-1.1** — State the direction of authority (wp-config.php declarative vs
   descriptive), then rewrite FR-14/FR-15/FR-16 around the **triple** (database, user, grant), with a
   decision table: for each combination of present/absent/wrong, what `ensure()` does and with which
   credential set it observed it. This single edit closes or reframes roughly a third of the findings
   here.
2. **EC-6.3 + EC-6.4 + EC-6.7** — Add an FR stating that DDL is non-transactional, that partial
   failure leaves a durable state, that `ensure()` reports step-level progress on failure, and that
   re-running `ensure()` **must** recover from any partial state it can itself produce — with a
   closing read-back of the achieved triple.
3. **EC-3.4 + EC-3.10** — Fix FR-13 to require wildcard escaping in `GRANT` database patterns, and
   widen FR-10 to state the actual rule per **context** (identifier / string literal / LIKE pattern /
   `information_schema` string), with the enforcing test deriving the site list from the code.
4. **EC-5.6 + EC-2.10** — Add a "credentials could not be obtained" state to FR-14, require eager
   credential resolution and validation before the first connection attempt, and promote the memlog's
   exception-hierarchy decision into an FR so FR-14's distinctions are representable.
5. **EC-6.1 + EC-5.7 + EC-2.9** — Add a concurrency NFR (thread-safety contract, concurrent-`ensure()`
   behaviour, serialisation), a timeout budget, and a retry policy that names a library per global
   rule #1.
