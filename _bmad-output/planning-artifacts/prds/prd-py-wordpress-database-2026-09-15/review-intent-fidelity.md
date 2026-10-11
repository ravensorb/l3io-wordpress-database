---
title: Intent-fidelity review — py-wordpress-database PRD
reviewer: intent-fidelity lens
date: 2026-09-16
subject: prd.md (2026-09-16), addendum.md (2026-09-16)
code baseline: wpdatabase2/ at e82e6aa
---

# Intent-fidelity review

The single question: do these requirements still serve the intent the PRD itself states, or
has the rewrite drifted into a different product?

## Verdict

**Mostly faithful, with one real drift and one overstatement.**

The intent statement in section 1 is *directionally* honest — it names the right verb
(`ensure()`), the right anchor (`wp-config.php` as the source of truth) and the right
security concern (admin-credential lifetime). Sections 7.1–7.3 are almost entirely
intent-serving and several of them are the intent's overdue repairs.

Two problems:

1. **The "load-bearing design idea" is overstated.** The two-credential-set separation exists
   in the code as exactly one thing: admin credentials are a *method parameter*, not instance
   state. That is a real and deliberate choice, and it is worth preserving. But it is not an
   organizing idea — it is not in the type system, not in naming, and its other half (creating
   and granting WordPress's own credentials) is commented out and syntactically invalid on every
   server the PRD targets. Calling it load-bearing is a flattering reading of a parameter
   position.

2. **Section 7.5 is a different product's requirements.** FR-29's correlation IDs and FR-30's
   "first-class" OpenTelemetry describe a distributed service. The fan-out that FR-29 proposes
   to correlate is four SQL statements on one connection inside one method. FR-28's *security*
   half is intent-serving; its structured-events half and all of FR-29/FR-30 are not, and the
   PRD's own G6 and FR-30's `[ASSUMPTION]` already argue against them.

A third, smaller drift: **FR-23** (a second cloud credential provider) is justified in the PRD
by what it proves about the *interface*, not by anything a user needs — and FR-18's
build-time-generated WordPress version map is a data pipeline with a maintenance cadence,
serving a feature the intent never mentions and no scenario S1–S4 uses.

The most serious *omission* is that **FR-11 requires nothing**. As worded it is already
satisfied by the code as it stands, while the actual place admin credentials persist —
`WpCredentials` itself — is exempted by its own phrasing.

---

## 1. Is the intent statement faithful to the code?

### What the code actually does

`wpdatabase2/__init__.py:23-51` — `ensure()`:

```python
wp_config = WpConfigFile(filename=wp_config_filename)
database = WpDatabase(wp_config=wp_config)
if database.test_config() and not force:
    return
database.ensure_database_setup(admin_credentials=credentials, force=force)
if database.test_config(throw=True):
    ...
```

`wpdatabase2/classes/database.py:145-195` — `ensure_database_setup()` takes
`admin_credentials`, passes it straight into `self._connect(admin_credentials)`, and never
assigns it to `self`. `WpDatabase`'s own credentials come from the config
(`database.py:42-44`).

### Faithful in shape

Three things in the intent statement check out against the code:

- **"the database a `wp-config.php` points at"** — accurate. `WpDatabase.__init__` derives the
  entire connection (host, port, name, credentials) from the config file. The config is the
  source of truth, not a parameter set.
- **"without the caller writing SQL"** — accurate and served. All SQL is internal.
- **"admin credentials ... used only to do the creating"** — accurate *of `WpDatabase`*. Admin
  credentials appear in exactly one parameter position, are used for exactly one connection, and
  are unreachable from the instance afterwards. This is the strongest evidence for the intent
  statement and it is genuinely deliberate: the author could easily have put them on the
  constructor and did not.

### Not faithful in behaviour — push back on three points

**(a) The half the intent calls load-bearing does not exist.** The intent says WordPress's
credentials "are the ones *created and granted*". `database.py:174` is the `CREATE USER` call,
commented out:

```python
#cur_exec('CREATE USER ''%s''@''*'' IDENTIFIED BY ''%s''', ...)
```

The only user creation is the implicit kind, via `GRANT ... IDENTIFIED BY`
(`database.py:180`), which is ERROR 1064 on MySQL 8 and later — removed, per addendum B. So on
every server in NFR-4's matrix, the WordPress credential set is never created. The separation
is a structure with one working side. That is a fair thing for a PRD to *aim* at; it is not a
fair thing to describe as an idea the code is organized around.

**(b) The separation is not expressed anywhere a reader or a compiler could see it.** Both
credential sets are the same class, `WpCredentials`, with the same shape and no marker
distinguishing admin from WordPress. There is no `AdminCredentials` type, no naming convention
beyond one parameter name, and nothing that prevents `test_config()` from being called with
admin credentials — it just happens not to be. If the separation were load-bearing, the freeze
(FR-1) would be freezing something that encodes it. It isn't: FR-1 freezes `WpCredentials`,
which is agnostic to the distinction.

**(c) "Idempotently" rests on SQL, not on the check the code appears to make.**
`does_database_exist()` is `return self.test_config(False)` (`database.py:107-115`) — a
connection test wearing an existence check's name. Independent of the swallowed `TypeError`
(addendum E), there is *no database-existence check in this codebase*. Whatever idempotence
`ensure()` has comes from `CREATE DATABASE IF NOT EXISTS` and `GRANT` being re-runnable, not
from the guard at `__init__.py:42`. That matters for how the PRD reads: FR-7 ("idempotent")
sounds like it preserves something, when in fact FR-14/FR-15/FR-16 are the requirements that
build the thing FR-7 describes. FR-7 should be read as new work, not preserved behaviour.

### Recommended rewrite of section 1

Keep the sentence about what the package is for. Replace the "load-bearing design idea"
paragraph with something the code can actually be held to:

> The design commitment being preserved is narrower than it looks: **admin credentials are a
> parameter to the one operation that needs them, never state on any object.** That is the one
> place the code expresses the two-credential-set separation, and it is the one place the
> rewrite must not lose. The other half — that WordPress's own credentials are *created and
> granted* rather than assumed — is stated in the current code and does not work (the
> `CREATE USER` call is commented out and the `GRANT` form is invalid on MySQL 8+). The rewrite
> implements it for the first time; it does not preserve it.

That version is checkable, does not flatter, and does not lose anything the current statement
buys.

---

## 2. Does every FR serve that intent?

### Serves the intent, keep as-is

FR-1..FR-6 (contract and its mechanical enforcement — FR-6 is exemplary: the rule and its check
land together), FR-7..FR-13 (provisioning, the product's core), FR-14..FR-16 (the existence-check
repair — the single most intent-serving group in the document), FR-26 (config reading as an
optional provider, which fixes a real import defect), FR-32, FR-36, FR-38, FR-39, NFR-1..NFR-5.

### FR-21..FR-25 — pluggable multi-cloud credential providers

**Partly serving, one requirement to cut.**

The intent's demand about admin credentials is about **lifetime**, not **provenance**. Where a
secret comes from is orthogonal to how long it lives. So the provider interface has to earn its
place on other grounds, and some of it does:

- **FR-21** ("base install carries none of them") and **FR-26** are the valuable part, and
  neither is really about providers. They are dependency hygiene: today `boto3` and `wpconfigr`
  are imported unconditionally at package level (`__init__.py:8-10`, `secret.py:7`), so the
  connection-only core is gated behind both. That is a live defect, it is recorded in AGENTS.md,
  and fixing it serves G6 directly. **Keep.**
- **FR-24** (actionable error naming the exact extra) and **FR-25** (declared, validated secret
  shape) are cheap and serve NFR-3 supportability. **Keep.**
- **FR-22** (AWS ships as an optional provider) is forced by FR-1 anyway. **Keep.**
- **FR-23** — "At least one additional provider is supported to prove the interface is not
  AWS-shaped" — **cut, or replace.** Read the justification: the requirement's stated purpose is
  a property of the *interface*, not a need of any user in S1–S4. It is architecture taste, and
  it is not cheap taste: an Azure Key Vault provider means an `azure-keyvault-secrets` +
  `azure-identity` dependency, CI credentials or a mock layer, documentation, and a maintenance
  obligation — for a package that section 3 documents as having **zero demonstrated users** and
  one star across its lineage in eight years.

  If the interface's non-AWS-shapedness needs proving (it does — a one-implementation interface
  is a guess), prove it with a second provider that costs nothing to maintain and that S1 and S3
  would actually use: **environment variables**, or a **local file / literal** provider. Those
  are in-tree, dependency-free, testable without cloud credentials, and they exercise exactly the
  interface properties at issue (no region concept, no client lifecycle, no JSON envelope). A
  cloud SDK proves nothing extra and costs a great deal more.

  Suggested replacement: *"FR-23 — A second provider ships in the base install with no
  dependency: credentials from environment variables. It exists to prove the interface is not
  AWS-shaped and to serve the ephemeral-test-database scenario (S1) without a cloud account.
  Azure Key Vault and other cloud providers are out of scope for 1.0 and are named as follow-on
  work."*

### FR-28..FR-30 — observability

**This is the drift.**

- **FR-28, first sentence half** — "Credentials, secret values and secret identifiers are never
  logged" — is squarely intent-serving. It is the same concern as the admin-credential-lifetime
  clause, expressed as a logging rule. It is also **duplicated verbatim by NFR-1**, which is
  where it belongs. Keep it in one place.
- **FR-28, structured events** — defensible but oversold. Emitting operation / target / outcome /
  timing as structured fields is cheap and serves NFR-3. State it as *"log records carry the
  operation, target database and outcome as structured fields"* and stop there. Do not make it
  an event schema.
- **FR-29 — correlation identifier "propagated across the calls it fans out into"** — **cut.**
  There is no fan-out. One `ensure()` opens at most two connections and issues at most five
  statements, synchronously, inside one call stack in one process. A correlation ID buys the
  caller nothing their own logging context does not already provide, and for a *library* it is
  actively unhelpful: the caller already owns request context and the library inventing a second
  identifier fragments it. What the intent actually wants from a failed `ensure()` is *"what was
  attempted, against what target, and what to do next"* — which is **NFR-3, already written**.
  FR-29 is NFR-3 wearing a distributed-systems costume.
- **FR-30 — "OpenTelemetry tracing is first-class ... a core capability, not an afterthought"** —
  **demote.** Three reasons, two of them the PRD's own:
  1. **The PRD already contradicts itself.** G4 makes observability a goal; G6 makes
     dependency-lightness a goal; FR-30's own `[ASSUMPTION]` resolves the conflict by making OTel
     an extra that degrades to no-ops. That resolution is correct and it is the opposite of
     "first-class". Open question 2 records the unresolved word. Settle it: OTel is an **opt-in
     extra with no-op fallbacks**, and the word "first-class" comes out of the requirement.
  2. **It inverts the priority order section 2 establishes.** Section 2's finding is that the
     package is unusable by anyone who finds it: uninstallable for six years, headline capability
     broken, cannot talk to a current server. A requirement that spans are core, in the same
     document, is a statement about which failure the author finds more interesting rather than
     which one users hit.
  3. **A library is the wrong layer to insist on tracing.** Spans for `ensure()` are genuinely
     nice for S2 (multi-tenant control plane) — that is a real use, and it is exactly the shape
     of use that arrives with its own tracer and wants the library to *participate*, not to own
     the decision. "Participate when a tracer is configured" is the requirement. That is what the
     `[ASSUMPTION]` already says.

  Suggested replacement: *"FR-30 — When the `otel` extra is installed and a tracer is configured,
  `ensure()` and each database operation it performs emit spans, with error status set on
  failure. Absent the extra, tracing degrades to no-ops and costs nothing at import or call
  time. Tracing is never required for correctness and never required for a diagnosable
  failure — NFR-3 owns that."*

### FR-17..FR-20 — WordPress version reporting

**Serves the frozen surface, not the intent. Flag the cost explicitly.**

The intent statement says nothing about reporting WordPress versions. No scenario S1–S4 uses it.
`get_database_version()` is in the frozen surface, so FR-1 obliges the *name* to keep working —
but FR-1 does not oblige FR-18's implementation, which is a build-time data pipeline derived from
884 release tags across two upstream sources, plus a documented refresh command and a standing
maintenance task. That is the largest piece of scope in this PRD that the intent does not justify,
and the PRD's own section 3 counterweight ("the defensible value here is being maintained,
installable and correct — not novel capability") argues against taking it on.

The PRD does not surface the cheap, contract-compliant alternative, and it should, because FR-20
already hands it over: *"`WpDatabaseVersion.wp_version` continues to return `None` for unknown
values per its current contract."* A conforming implementation therefore is: report `db_version`
faithfully (which is the useful number and requires no table at all), return `None` from
`wp_version`, and deprecate `wp_version` for removal in 2.0. That costs nothing, breaks no
documented contract, and removes a maintenance obligation from a one-maintainer package.

Whichever way this goes, it should be an *explicit* decision recorded against the section-3
counterweight, not an assumption. As written, FR-18 acquires a data pipeline by implication.

Two defects in FR-19/FR-20 regardless of which option is chosen:

- **FR-19's comparison is not type-safe against the frozen surface.** `WpDatabaseVersion(ver)`
  stores whatever it is handed (`database.py:203`) and `_wordPressVersions` is keyed by
  **strings** (`"48748"`, `"9872"`). FR-19 demands "the highest release whose `db_version` is less
  than or equal to the observed value". On strings that is wrong:
  `'9872' <= '48748'` is `False`, while `int('9872') <= int('48748')` is `True`. FR-19 needs an
  explicit requirement that `db_version` is coerced to an integer for comparison, and that
  non-integer input is an error rather than a silent miss.
- **FR-17 depends on something not yet known to be readable.** Honouring `$table_prefix` requires
  reading a PHP *variable*, not a `define()`. Addendum D flags that the candidate readers may not
  do this. FR-17 should state the dependency on FR-27 explicitly, the way FR-26 does.

### FR-35 — version 1.0.0

**Taste, and internally inconsistent.** 1.0.0 asserts a stable, intentional public contract. In
the same document, FR-27 is an **open, blocking** decision about a public-surface dependency, and
FR-31 starts a deprecation clock on FR-5. You cannot simultaneously declare the contract settled
and announce that part of it is deprecated as of the same release. Either:

- ship the FR-5 break immediately (open question 5 already suggests this is the honest option for
  a package nobody can install) and then 1.0.0 is coherent; or
- keep the deprecation period and ship **0.1.0**, with 1.0.0 following once FR-27 is resolved and
  the deprecation has expired.

The second is more honest. Neither choice affects the intent; the inconsistency does affect
whether FR-6's "frozen surface" claim means anything.

### FR-40, FR-41 — uv

Tooling taste, but self-justifying: it retires `build.sh`'s `sudo python3 setup.py install` and a
CI install step that cannot succeed. Cheap and intent-neutral. One note: FR-40's stated
justification is that uv "is already a hard requirement of this repo's tooling" — that is BMad's
requirement, not the product's, and it is a weaker argument than the one available (the existing
release scripts are actively dangerous). Use the stronger one.

---

## 3. Does anything essential go unrequired?

### FR-11 requires nothing — the review's most important finding

> **FR-11** — Admin credentials are used only for the operations that require them and are not
> retained on the instance after `ensure()` completes.

Three problems, in increasing severity.

**(a) It is already true, so it demands no work.** `WpDatabase` never assigns
`admin_credentials` to `self` (`database.py:145-195`). The requirement as worded is satisfied by
the code the PRD is replacing. A requirement that the current defective implementation passes is
not exerting force on the rewrite.

**(b) "on the instance" exempts the one object that does retain them.** The admin credentials
live in the caller's `WpCredentials` object for its entire lifetime, and the CLI holds exactly
such an object in a local across the `ensure()` call (`__main__.py:79-90`). Nothing in FR-11
touches that, because a `WpCredentials` is not "the instance".

**(c) "used only for the operations that require them" never says which operations those are.**
Nothing in the PRD states that the existence check runs with *WordPress's* credentials. Today it
does, by accident of `test_config()` reading `self._wp_connection.credentials`. A rewrite that
implemented FR-14's four-outcome check using admin credentials — which would be the *easier*
implementation, since admin creds are more likely to connect — would satisfy every FR in this
document while destroying the intent. That is the exact failure mode the intent exists to
prevent, and no requirement blocks it.

**Restate FR-11 as three checkable requirements:**

> **FR-11a** — The state-inspection path (FR-14/FR-15) connects using **WordPress's own
> credentials, as read from `wp-config.php`**, never administrative credentials. A test asserts
> this by passing a distinguishable admin credential object and asserting it is never used to
> open a connection.
>
> **FR-11b** — Administrative credentials are never assigned to an attribute of any
> `wpdatabase2` object. A test passes a sentinel credentials object into `ensure()` and asserts,
> after return, that no object reachable from the returned/constructed objects holds a reference
> to it (`vars()` walk plus `gc.get_referrers` on the sentinel), and that it appears in no
> `repr()` or `str()`.
>
> **FR-11c** — The administrative connection is opened only after state inspection has
> determined that setup is required, and is closed before `ensure()` returns, including on every
> error path. A test asserts close-on-exception.

FR-11c is the testable form of the intent's actual phrase, "no longer than the one operation
needs". FR-11 as written measures the wrong thing at the wrong scope.

### Yes — lazy credential resolution fights it, three ways

`credentials.py:55-60, 98-109`:

```python
def _resolve_secret(self):
    if not self._secret:
        return
    self._username = self._secret.as_dict['username']
    self._password = self._secret.as_dict['password']
    self._secret = None

@property
def username(self):
    self._resolve_secret()
    return self._username
```

1. **It makes the moment of exposure unpredictable.** Plaintext enters process memory at the
   first property read, wherever that happens to be. You cannot write a requirement about when a
   secret should leave memory when you cannot say when it arrived.
2. **The caching is irreversible, and there is no discard operation at all.** `self._secret =
   None` converts the object permanently from *a reference to a secret* into *the secret*. A
   `WpCredentials` built from a secret ID is initially the safer of the two shapes — it holds no
   plaintext — and resolution destroys that, one way, forever. The frozen public surface
   (addendum F) contains **no** `clear()`, no `close()`, no context manager, no invalidation.
   There is no API by which FR-11 could be honoured even if it demanded the right thing.
3. **Reading a property is a side effect, which NFR-1 cannot guard.** `username` and `password`
   look like accessors and are a network call plus a state mutation. Any log line, any `repr`
   helper, any debugger watch expression, any `assert` in a test materializes the plaintext. NFR-1
   says secret *identifiers* are never logged — but the trap is the opposite direction: touching
   the object to log something innocuous is what pulls the secret down.

**Recommended additional requirements:**

> **FR-11d** — `WpCredentials` gains an explicit scope for resolved secret material: a
> context-manager protocol (`__enter__`/`__exit__`) and an idempotent `clear()` that drops
> resolved plaintext and restores the object to holding only its unresolved reference where one
> exists. `ensure()` and the CLI use the scoped form. Both names are additive, so FR-1 is
> unaffected.
>
> **FR-11e** — Resolution is explicit, not incidental. `username`/`password` remain readable per
> FR-1, but a `resolve()` call is the documented path, and `__repr__`/`__str__` on
> `WpCredentials`, `Secret` and `WpConnection` never resolve and never render secret material —
> asserted by test.

FR-11e's `repr` half is worth calling out as the cheapest high-value requirement available: it is
three dunder methods and three assertions, and it closes the largest practical leak (exception
tracebacks rendering locals) that NFR-1 currently only promises in prose.

### FR-7 and FR-8 contradict each other

- **FR-7**: "running it against an already-correct database and user succeeds and **changes
  nothing**."
- **FR-8**: user creation is `CREATE USER IF NOT EXISTS`, **then `ALTER USER` to set the
  password** (correctly noted as required, since `IF NOT EXISTS` will not update an existing
  account), then `GRANT`, then `FLUSH PRIVILEGES`.

Against an already-correct database, FR-8's sequence resets the password and re-issues the grant.
That is a write. It is also the *right* behaviour under config-is-truth — if `wp-config.php` is
the source of truth, `ensure()` should converge the server to it — but it is not "changes
nothing", and the difference is observable (`mysql.user.password_last_changed` moves, binlog
entries appear, replicas see writes). Pick one and say so:

> **FR-7 (revised)** — `ensure()` is **convergent** and safe to re-run: running it against an
> already-correct database and user succeeds, leaves the database and its data untouched, and
> leaves the WordPress credentials working. It is not a no-op: per FR-8 it re-asserts the
> password and grants from `wp-config.php`, which is the source of truth. Callers who need a
> strict no-op use FR-15's inspection first.

This matters to the intent, not just to precision: a reader who believes FR-7 will not expect
`ensure()` to overwrite a password that was rotated on the server but not in the config file.

### The postcondition — the intent's real acceptance test — is unrequired

FR-7 says idempotent, FR-8 says which SQL, FR-13 says grants are scoped. **Nothing states the
outcome.** Given that the current code has `CREATE USER` commented out and still "succeeds"
through to its closing validation, the postcondition is precisely the requirement most worth
freezing:

> **FR-13a** — `ensure()` returns successfully only if, after setup, a **fresh connection using
> the `wp-config.php` credentials** can connect to the target host and use the target database.
> This formalizes the closing validation that `ensure()` performs today
> (`__init__.py:50`, `test_config(throw=True)`), which is the intent's acceptance test and is
> currently the only thing standing between "ran some SQL" and "the database WordPress points at
> exists".

### FR-14's four outcomes have nowhere to go in the frozen surface

FR-14 requires four distinguishable outcomes (present and reachable / absent / auth failed /
host unreachable). FR-15 keeps `test_config()` and `does_database_exist()` as booleans. Two
booleans cannot carry four outcomes, so FR-14 necessarily requires a **new public name** — and
the PRD never says what it is or what it returns. That is a gap in a requirement group that is
otherwise the best in the document. Name it (an enum-returning `inspect()` / `check_state()`, or
distinct exception types for the two failure cases) and state that the booleans become thin
wrappers over it.

### `force=True` is the one flag that lengthens admin-credential exposure

FR-12 preserves `force=True` skipping the existence check. Under FR-11c that means: open an admin
connection without having established that one is needed. Worth one sentence stating that
`force=True` changes *whether* the check runs, not the scoping, closing or non-retention rules —
otherwise `force` is a documented bypass of the intent's central constraint.

### FR-5 is not the only observable break

FR-5 is "called out explicitly" as *the* breaking change to observable behaviour. At least two
others exist, and FR-4's release-notes enumeration needs to cover them:

- **FR-26 changes what `import wpdatabase2` requires.** Today `boto3` and `wpconfigr` are
  imported at package level; both become optional. That is an improvement, but anything relying
  on the transitive import (or on `wpdatabase2.boto3` resolving) changes.
- **FR-15 changes what `does_database_exist()` means.** It currently returns whether a connection
  test passed; it will return whether the database exists. Same signature, same name, different
  answer in the auth-failure and unreachable-host cases. This one deserves FR-5's treatment.

Also worth noting as *support* for FR-5: `database.py:42-44` calls
`WpCredentials.from_username_and_password(...)` on config values and does not check for `None`. A
`wp-config.php` with `DB_USER` but no `DB_PASSWORD` therefore yields `credentials=None` and a
later `AttributeError` at a distance. FR-5's change from `None` to `InvalidArgumentsError` fixes
a live defect on the intent's primary path, not just a docstring mismatch. Say so — it makes FR-5
much easier to justify.

### NFR-2 is the document's most valuable rule and has no check

Addendum E establishes that one bare `except Exception` is the shared root cause of three
observed defects, and calls fixing it "the highest-leverage single change in the rewrite". NFR-2
states the rule in prose, in the non-functional section, where it reads as an aspiration. Per the
mechanical-enforcement principle the PRD applies so well to FR-6, NFR-2 should land with its
check in the same change: `ruff` **BLE001** (`blind-except`) or pylint **W0703**, enabled as an
error, not a warning, and run in the FR-37 CI gate. One line of lint configuration converts the
document's most important rule from memory into enforcement.

And per the scope principle: the check's scope should be derived, not enumerated — lint the whole
package, with no per-file ignores, so a new module cannot be added outside the rule's reach.

---

## 4. Has the frozen surface preserved the intent, or an accident?

Inventory from addendum F, sorted by what it actually preserves.

### Expresses the intent — freeze deliberately

| Surface | What it encodes |
|---|---|
| `ensure(wp_config_filename, credentials, force=False)` | The verb, and the two-credential-set separation *at the API boundary*: the config path (WordPress's creds, implicitly) and the admin creds are separate arguments. This signature is the single best artifact of the intent in the whole package. |
| `ensure_database_setup(admin_credentials, force=False)` | Admin credentials as a parameter, not constructor state. The one place the "discarded afterwards" half is structurally true. |
| `WpDatabase(wp_config=...)` | Config-as-source-of-truth. |
| `WpConnection(db_host, db_name, credentials)` | The WordPress credential set travelling with the connection it belongs to. Coherent. |

### Historical accident that the freeze makes permanent

**(a) `WpCredentials(username, password, aws_secret_id, region)` — the sharpest problem.** FR-1
freezes a **vendor-specific constructor on the core credential type**, while FR-21 requires
credential sources to be a vendor-neutral pluggable interface. Those cannot both hold. You cannot
have a provider-neutral `WpCredentials` and also permanently accept `aws_secret_id=` and
`region=` keyword arguments on it. The PRD does not acknowledge the tension anywhere.

The resolution is available and should be stated: the AWS kwargs remain **accepted and
deprecated** — a thin adapter that constructs the AWS provider and delegates — while the neutral
path (a provider object, or `from_provider(...)`) becomes the documented one. Add it to FR-22 and
to FR-31's deprecation list. Left unaddressed, FR-21 is decorative: the frozen surface keeps AWS
privileged in the core type forever.

Note also that the constructor's validation is two double-negation XOR checks
(`credentials.py:38-44`) whose accepted argument combinations are not derivable from reading them.
That is shape, not intent; FR-1 freezes the *accepted combinations*, and a rewrite is free to
implement them with a readable dispatch.

**(b) `Secret(identifier, region=None)` with `.region`, `.as_string`, `.as_dict`.** An AWS
Secrets Manager client in the public surface of a WordPress database library. Pure accident of
the original author's deployment. FR-22 keeps it working "when that provider is installed" —
which means a permanently public name whose import succeeds only with an extra present. That is a
reasonable compromise but it is currently presented as compatibility rather than as the
compromise it is. State it: *`Secret` is retained for compatibility only, is AWS-specific by
accident of history, and is not the model for other providers.* Otherwise the next provider
author copies it.

**(c) `WpConnection.db_host` setter that re-parses `host:port` and overwrites `db_port`.** This is
a defect — assignment order changes the result, silently
(`connection.py:40-54`). Addendum F preserves it deliberately and AGENTS.md documents the ordering
rule. That converts a bug into a contract, and the freeze makes it permanent. Worse, it is
unreachable from the intent: nothing in the intent needs *mutable public setters* on connection
details at all. `ensure()` builds a `WpConnection` from config and uses it.

Recommended: freeze the *constructor* and the *getters*; make the setters deprecated on the
grounds that the ordering hazard cannot be fixed while they exist, and state that `db_port`
assignment after `db_host` remains the supported order during deprecation. If the setters must
stay forever, then at minimum require that setting `db_host` **without** a port no longer clears
an explicitly-set `db_port` — the current behaviour (`connection.py:54`) is the trap, and
silently clearing a port is not something any documented contract promises.

**(d) `test_config()` / `does_database_exist()` as a boolean pair.** The *names* are the accident:
the original author made them the same function (`database.py:115`), which is why one of them
means the wrong thing. FR-15 splits them correctly. But freezing two booleans while FR-14
requires four outcomes means the frozen surface cannot express the model the rewrite is built on
(see section 3). The booleans are legacy convenience wrappers; the PRD should say so and name
their replacement.

**(e) `WpDatabaseVersion(ver)` accepting an untyped value, over a string-keyed map.** Freezing
`db_version` as "whatever was passed in" fights FR-19's ordered comparison (see section 2). Also
`WpDatabaseVersion` is defined in `classes/database.py` and exported from `wpdatabase2.classes` —
harmless, but it is shape, not design, and FR-1 freezes the export path.

**(f) What FR-1 correctly does *not* freeze.** `wpdatabase2/__init__.py:5-21` currently makes
`wpdatabase2.json`, `wpdatabase2.boto3`, `wpdatabase2.connector`, `wpdatabase2.Secret`,
`wpdatabase2.WpCredentials` and `wpdatabase2.WpConnection` importable, almost all of them unused
by the module. FR-1 is phrased as a **floor** ("the following remain importable"), not a ceiling,
which is the right call and lets FR-26 remove the eager imports. Worth one sentence making the
floor/ceiling distinction explicit, so nobody later reads FR-1 as freezing the incidental
re-exports.

### Summary of the freeze

Roughly a third of the frozen surface expresses the intent — `ensure()`, `ensure_database_setup()`
and config-derived construction. The rest is the shape one deployment happened to need in 2018:
AWS in the core credential type, an AWS client class as a public name, mutable connection setters
with an ordering hazard, and a boolean pair that cannot express the state model the rewrite
requires. FR-1 freezing all of it uniformly, with no annotation of which is which, is the
document's quietest fidelity problem: it gives the accidents the same permanence as the design,
and a future maintainer reading FR-1 has no way to tell them apart.

**Recommendation:** annotate addendum F's inventory with a third column — *intent-expressing* /
*compatibility-only, deprecated path documented*. That is a one-pass edit, it changes no
requirement, and it is the difference between a freeze that protects the intent and a freeze that
embalms 2018.

---

## Requirement-level disposition

| FR/NFR | Disposition |
|---|---|
| FR-1..FR-4, FR-6 | Serves intent. Keep. Add the floor/ceiling note to FR-1 and the annotation to addendum F. |
| FR-5 | Serves intent. Strengthen the justification with the `database.py:42-44` `None`-credentials defect. |
| FR-7 | **Contradicts FR-8.** Revise to "convergent", not "changes nothing". |
| FR-8..FR-10, FR-12, FR-13 | Serves intent. Keep. Add the `force` scoping sentence to FR-12. |
| — | **Missing: FR-13a**, the postcondition (wp-config credentials can connect after setup). |
| FR-11 | **Requires nothing as written.** Split into FR-11a..FR-11e. |
| FR-14..FR-16 | Best group in the document. Keep, and **name** the four-outcome API. |
| FR-17 | Keep; state the FR-27 dependency (`$table_prefix` is a variable, not a define). |
| FR-18 | Scope the intent does not justify. Record the decision explicitly against section 3; surface the FR-20-compliant zero-maintenance alternative. |
| FR-19 | Add integer coercion — string comparison is wrong (`'9872' <= '48748'` is `False`). |
| FR-20 | Keep. |
| FR-21, FR-22, FR-24, FR-25, FR-26 | Keep — dependency hygiene, which is real. Add the frozen-AWS-kwargs resolution to FR-22. |
| FR-23 | **Cut the cloud provider.** Replace with a dependency-free env-var provider. |
| FR-27 | Correctly left open and correctly blocking. No change. |
| FR-28 | Move the security clause to NFR-1 (dedupe); keep structured fields, drop the event-schema ambition. |
| FR-29 | **Cut.** Duplicates NFR-3 for a system with no fan-out. |
| FR-30 | **Demote.** Settle open question 2 as "extra with no-op fallback"; delete "first-class". |
| FR-31 | Keep, but reconcile with FR-35. |
| FR-32, FR-33, FR-34, FR-36..FR-39 | Serves intent or serves G3/G5. Keep. |
| FR-35 | Inconsistent with FR-27 and FR-31. Ship 0.1.0, or drop the deprecation period. |
| FR-40, FR-41 | Keep; use the stronger justification (the release scripts are dangerous). |
| NFR-1 | Keep; absorb FR-28's security clause; add the `repr` assertion from FR-11e. |
| NFR-2 | Highest-value rule in the document, **with no check**. Land `BLE001`/`W0703` as an error in CI in the same change. |
| NFR-3..NFR-8 | Keep. NFR-3 subsumes what FR-29 was reaching for. |

## Answers to the PRD's open questions, from the intent lens only

- **Q2 (OTel mandatory or extra)** — Extra. "First-class" is not a fidelity requirement; a
  diagnosable failure (NFR-3) is.
- **Q5 (deprecation period)** — Immediate clean break. A deprecation period protects users who
  cannot exist, because the package has been uninstallable for six years. Taking it forces the
  FR-35 inconsistency.
- **Q7 (second credential provider)** — Not Azure. An env-var provider proves the same interface
  property at zero cost and serves S1 and S3.
- **Q6 (documentation beyond the README)** — Out of the intent's scope. FR-39 plus NFR-8 is
  sufficient for 1.0.
