# Adversarial review — py-wordpress-database PRD

Reviewed: `prd.md` (295 lines, 41 FRs, 8 NFRs) and `addendum.md`, against the code at
`wpdatabase2/` (752 lines) and `AGENTS.md`, at `e82e6aa`.

Posture: hostile. The job is to find where the reasoning fails, not to confirm it.

**Verdict: reject in current form.** The document is unusually well-evidenced — and it uses
that evidence to justify a plan the evidence does not support. Section 3 assembles a complete
case that the demand does not exist, records it as a "counterweight," and then changes nothing:
41 functional requirements, a plugin framework, two cloud SDK integrations, a distributed-tracing
surface and a generated WordPress version map follow it unaltered. Separately, the central
compatibility device — "frozen outward surface" — is not implementable as specified, and at
least three FR pairs are mutually unsatisfiable. The intent in section 1 is right and the defect
evidence in section 2 is good work. The scope and the freeze both need to be rebuilt.

Severity counts: **5 Critical, 10 High, 12 Medium, 6 Low** (33 findings).

---

## Critical

### C1 — Section 3's counterweight is decorative. Nothing downstream moves because of it.
`prd.md` §3, lines 59–64.

The counterweight is as strong a self-refutation as a PRD can contain: the hole is ~15 lines of
SQL; Ansible `community.mysql` already fills it idempotently and is broadly maintained; the
ancestor earned one star in eight years; this package sat uninstallable for six years with no bug
report. The paragraph closes: "Scope decisions in this document should be read against that."

That sentence is a hedge, not a decision. Trace its effect through the rest of the document:
there is none. Sections 7–9 contain no requirement that was cut, deferred, or downsized because
of §3. The PRD then adds a pluggable multi-cloud credential framework (FR-21..FR-25), first-class
OpenTelemetry (FR-28..FR-30), a build-time version-map generator sourced from 884 git tags
(FR-18), a three-server container matrix (FR-38), and a 1.0.0 stability promise (FR-35). Recording
a counter-argument and then ignoring it is worse than not recording it, because the record creates
the appearance of having weighed it.

Three specific failures follow:

**(a) The minimal alternative is never evaluated.** §3 names the defensible value precisely:
"being maintained, installable and correct — a bar the incumbents fail — not novel capability."
Take that at face value and derive scope from it. Installable = fix the `wpconfigr` pin + move to
`pyproject.toml` (FR-32, FR-36). Correct = fix the context-manager swallow (FR-14), the SQL
(FR-8/FR-9), the table prefix (FR-17), and validate identifiers (FR-10). That is roughly eight
FRs against a 752-line library — plausibly a few hundred lines of diff. Every remaining
requirement is orthogonal to the stated value. The PRD never states this option, never states the
"deprecate and point at `community.mysql`" option, and never states the "archive it" option. A
document that assembles the case for those three options and then presents only a full rewrite has
not done the comparison it appears to have done.

**(b) There is no cost estimate anywhere.** Not an hour figure, not a t-shirt size, not a
sequencing plan. The reader is invited to "read scope against" the counterweight while being
given no number to read against it. That makes the central scope judgement of the document
unfalsifiable by construction.

**(c) The scope attacks the value proposition directly.** The differentiator claimed is
*maintenance*. The evidence for maintenance risk is in the document: one author, six years
dormant, no fix shipped. The plan then adds recurring obligations — an AWS provider, an Azure
provider, an OTel surface, three server versions in CI, a version map that needs regenerating on
every WordPress release (FR-18), and a published 1.0.0 that forecloses cheap correction. Each one
raises the probability that "maintained" stops being true. The more of this PRD is built, the
weaker its own justification becomes.

**Required:** either produce the option comparison (minimal fix / rewrite / deprecate / archive)
with costs, and pick on merit; or state plainly that this is a personal-infrastructure and
craft project (scenario S4 is the only non-inferred one) and size it accordingly. What is not
acceptable is the current posture, which quotes the demand evidence and then spends as if the
evidence said the opposite.

Note also the §2/§3 collision. §2 is titled "Why now" and its answer is "the package is currently
unusable by anyone who finds it" (line 27). §3 establishes that essentially nobody finds it. "Why
now" is a demand question; §2 answers a defect question. Six years of silence is evidence that
there is no *now* — the PRD's own §3 says so — and §2 never engages with that.

### C2 — FR-15 and FR-16 are not implementable under the freeze, and FR-16 breaks the package's primary use case.
`prd.md` FR-15, FR-16 (lines 149–154), FR-11 (140–142), FR-1 (103–107); `database.py:107-115`.

`does_database_exist()` is `return self.test_config(False)`, and `test_config` connects with
`self._wp_connection.credentials` — the **WordPress** credentials, read from `wp-config.php`. On a
first run those credentials name a user that does not exist yet.

FR-15 requires `does_database_exist()` to "report database existence specifically." With a
zero-argument signature frozen by FR-1, using a credential set that cannot authenticate before
provisioning, and with FR-11 forbidding the instance from retaining admin credentials, there is no
credential available that can answer the question. FR-1 + FR-11 + FR-15 are mutually
unsatisfiable. The only resolutions are to add a parameter (breaks FR-1) or to retain admin
credentials on the instance (breaks FR-11). The PRD picks neither and does not notice the clash.

FR-16 is worse. It says an "authentication or connectivity failure is reported rather than treated
as a reason to create things with admin credentials." But on the first run — the entire purpose of
this package — the WordPress user does not exist, so the correct and expected FR-14 outcome is
*authentication failed*. FR-16 therefore instructs `ensure()` to report an error in precisely the
state it exists to fix. As written, FR-16 makes the package non-functional for new provisioning.

**Required:** specify the routing table explicitly, with the credential set used for each probe.
Something like: probe with admin credentials for existence (`SHOW DATABASES LIKE` /
`information_schema.schemata`), probe with WordPress credentials only to *validate* after setup,
and enumerate the (probe, outcome) → action matrix. Then state which frozen signature has to give.

### C3 — "The documented contract" is circularly defined, so G2 cannot be enforced and FR-6 overstates its own coverage.
`prd.md` FR-4 (110–114), NFR-8 (266–268), FR-6 (120–122), G2 (line 69).

FR-4: where behaviour contradicts the documented contract, the documented contract wins.
NFR-8: every public name must have a docstring that matches its actual behaviour, and a wrong
docstring is a defect.

Read together these are circular. The compatibility baseline is the docstrings; the rewrite is
mandated to change the docstrings. Any behaviour change can be legalised by correcting its
docstring, and any behaviour can be broken by citing its docstring. Nothing in the PRD freezes the
docstrings as-of a named commit, and nothing names the artifact the compatibility suite compares
against. G2 is the document's one hard constraint and it currently rests on a moving baseline.

This is not theoretical — the current docstrings cannot bear the weight:

- `WpDatabase.__init__` docstring: `"Constructor for Wpdatabase.ArithmeticError"` and
  `"Note: Only wp_config OR wp_connection is required"` (`database.py:24-25`). The code accepts
  both and silently ignores `wp_connection` when `wp_config` is given (`database.py:37-49`, an
  `elif`). Which does FR-4 pick?
- `WpConnection`'s class docstring promises `Raises: InvalidArgumentsError`
  (`connection.py:16-19`); the constructor performs no validation and its imports are commented
  out (`connection.py:4-6`). Under FR-4 the documented contract wins, so `WpConnection` must
  *newly start raising* — a second breaking change of exactly FR-5's class, unenumerated.
- `test_config`'s docstring documents no `throw` parameter (`database.py:82-88`), while FR-1
  freezes `test_config(throw=False)`. The documented contract and the frozen signature disagree.
- The `db_host` setter's docstring says `"Gets the database host"` (`connection.py:41`) and says
  nothing about clobbering the port — see M5.

**Required:** commit a frozen baseline artifact (the public docstrings and signature inventory at
`e82e6aa`, i.e. Addendum F made machine-readable), have FR-6's suite diff against *that*, and
state that FR-4 corrections are recorded as diffs to the baseline artifact rather than silent
rewrites. This is the single highest-value addition to the document, and it is the only thing that
converts G2 from prose into the mechanical enforcement FR-6 claims to be.

### C4 — The frozen surface is already broken by NFR-5, FR-5 is not the only called-out break, and FR-6 cannot detect it.
`prd.md` FR-5 (115–119), FR-4, NFR-5 (257–261), FR-6; `database.py:101-103, 140-142`.

The current public surface leaks driver exceptions outward at three points: `test_config(throw=True)`
re-raises the raw driver exception (`database.py:101-103`), `get_database_version()` re-raises
`connector.errors.ProgrammingError` (`database.py:140-142`), and `ensure_database_setup` propagates
them through `cur_exec` (`database.py:158-160`). NFR-5 swaps `mysql-connector` for PyMySQL. Every
caller with `except mysql.connector.errors.*` breaks. That is a breaking change to the observable
public surface, forced by a requirement in the same document, and it appears nowhere in FR-4's
enumeration or FR-5's list.

The planning memlog records the decision — "define a wpdatabase2 exception hierarchy and never
leak driver exception types. Accepted as an outward change" (`.memlog.md` line 21). **That decision
did not make it into the PRD.** FR-1 enumerates only the three existing exceptions. So the PRD
neither freezes the exception surface nor specifies replacing it; it just omits the question.

FR-5 compounds this by presenting itself as the exception that proves the rule: "This is a
**breaking change to observable behaviour**, called out explicitly." It is not the only one. FR-4
authorises an unbounded set of the same class, C3 shows the set cannot even be enumerated without
a frozen baseline, and this exception-type break is a fourth.

And FR-6 — billed as "the mechanical enforcement of G2, not a prose promise" — tests that names
import, that signatures accept documented arguments, and that the CLI parses flags. It cannot
detect a changed exception type, a changed return value, a changed exit code, or a changed log
format. The guard's scope excludes the entire category of break this rewrite actually produces.
(User rule #4: a guard proves a rule, not the rule's reach. User rule #3: prose that overstates
its own coverage is worse than no prose.)

**Required:** add an FR specifying the exception hierarchy and the driver-exception wrapping
contract, enumerate it as a breaking change, and extend FR-6 to assert raised types, return
types, and CLI exit codes — or stop calling FR-6 mechanical enforcement of G2.

### C5 — FR-8 makes FR-7 false, and nothing in the PRD checks user or grant state.
`prd.md` FR-7 (126–127), FR-8 (128–131), FR-14/FR-15; `addendum.md` §B.

FR-7: `ensure()` is idempotent — "running it against an already-correct database and user succeeds
and **changes nothing**."

FR-8 mandates, unconditionally: `CREATE USER IF NOT EXISTS`, **then `ALTER USER` to set the
password**, then `GRANT`, then `FLUSH PRIVILEGES`. `ALTER USER ... IDENTIFIED BY` rewrites the
authentication string on every invocation. That is a write. It bumps `password_last_changed`, and
on servers with `password_reuse_interval` or `password_history` policies it can fail outright on a
re-run — i.e. FR-8 can make FR-7's "succeeds" false as well as its "changes nothing." FR-7 and
FR-8 contradict each other directly.

Second half, and it is the larger hole: **no requirement inspects user or grant state.** FR-14 and
FR-15 specify database-existence outcomes only. `ensure()`'s routing (per FR-16) is therefore
driven by database existence alone. The state "database exists, WordPress user missing or has the
wrong password" — the single most common real-world broken state, and the one the whole package
exists to fix — routes to "already exists, return success" without touching the user. The
documented contract already promises otherwise: `README.md:13-15` says it will "Create the
WordPress user, if it doesn't exist already" and is "idempotent; if the database **and the user**
already exist then it will return successfully." Under FR-4 the documented contract wins, so this
is a required behaviour with no requirement covering it.

Related uncovered case: the grant host part. Both the current code (`database.py:180`) and
Addendum B hardcode `'%'`. A user that already exists as `'u'@'localhost'` will not be matched, so
`CREATE USER IF NOT EXISTS 'u'@'%'` creates a *second* account and FR-7's idempotency claim is
false for that state too. No FR addresses the host part at all.

**Required:** restate FR-7 as convergence to a desired state with a named observable, not "changes
nothing"; make `ALTER USER` conditional or explicitly accept the re-write with its policy risk;
add FRs for user existence, grant-set verification, and the grant host part.

---

## High

### H1 — FR-21..FR-25: a plugin framework for a function that returns two strings.
`prd.md` lines 171–196.

What the library needs from a credential source is a `(username, password)` pair. That is already
expressible today: `WpCredentials.from_username_and_password()`.

What FR-21..FR-25 buy: a provider ABC, a discovery/registration mechanism, per-provider shape
declaration and validation (FR-25), per-provider missing-dependency error mapping (FR-24), two
optional dependency extras (FR-33), two cloud SDKs in the dev environment, and CI matrix cells for
each. For a 752-line library whose entire runtime is one connect and five statements.

FR-23 is the tell: "At least one additional provider is supported **to prove the interface is not
AWS-shaped**." That is a requirement whose stated justification is the validation of another
requirement. Check it against §6: S1 is a local throwaway test database (no vault), S2 is a
control plane that by definition already has its own secret plumbing, S3 is an operator with the
password in hand, S4 is the author's own stacks. **Zero of four scenarios motivates Azure Key
Vault.** Open question 7 concedes FR-23 is inferred from a passing mention of Azure.

There is also a cheaper answer the PRD never considers, and it is the answer the user's own rule #1
points at — don't build a framework, use the language's function type:

```python
credentials: WpCredentials | Callable[[], tuple[str, str]]
```

Five lines. Covers AWS, Azure, GCP, Vault, 1Password, a file, an env var, and anything invented
later, forever, with no extras, no ABC, no registry, and no CI cells. Building a plugin interface
when a callable suffices is the same category of error rule #1 exists to prevent.

**Required:** cut FR-23. Downgrade FR-21 to the callable. Keep FR-24's actionable-error rule (cheap,
real value) and FR-26's lazy-import fix (a genuine defect — `AGENTS.md:62-64`). Reduce FR-25 to
"validate the AWS secret dict and error clearly," which is three lines. FR-22 is redundant with
FR-1 and can be deleted outright.

### H2 — FR-28..FR-30: distributed tracing for a linear, single-process, six-statement operation.
`prd.md` lines 198–209, G4 (line 71).

Read what `ensure()` actually does (`__init__.py:38-51` → `database.py:145-195`): one connect, up
to five statements, a commit, a second connect to validate. One process, one thread, no
concurrency, no subprocesses, no network calls other than to the database.

FR-29 requires a correlation identifier "propagated across the calls it fans out into." **There is
no fan-out.** For a strictly linear sequence in one call stack, a correlation ID is `logging`'s
`extra=` on five log lines — which is FR-28, already. FR-29 adds nothing FR-28 does not.

FR-30 is worse for a *library*. A library does not own the tracer provider. "First-class" therefore
resolves to one of two things: (a) the library configures global OTel state, which is hostile to
every importer and is a well-known anti-pattern, or (b) it emits spans into whatever the host
application configured and no-ops when OTel is absent — which is exactly FR-30's own
`[ASSUMPTION]`, and which makes "first-class" an empty word. FR-30 admits the ambiguity in its own
text: "your answer could be read either way." A capability elevated to one of six project goals
(G4) cannot rest on an unresolved reading of one sentence.

Most damning: G4 ("make correctness observable ... as first-class features") serves none of the
three values §3 says are actually defensible — maintained, installable, correct. It is a sixth of
the goal list and a seventh of the FR count, justified by nothing in §3 and nothing in §6.

**Required:** demote G4. Keep FR-28 (structured events with fields, and the NFR-1 redaction rule) —
that is cheap and genuinely aids supportability. Cut FR-29 into FR-28 as a log field. Reduce FR-30
to a negative requirement: "the library creates no global OTel state and does not interfere with a
host application's tracing." If real spans are still wanted later, they are a ten-line addition
once someone asks.

### H3 — FR-2 and FR-33 conflict: the frozen CLI cannot run on the base install.
`prd.md` FR-2 (108–110), FR-26 (185–187), FR-33 (216–218), FR-36 (223–224).

FR-2 freezes `--wp-config` with its current semantics, and it is `required=True`
(`__main__.py:41-44`). FR-26 makes reading `wp-config.php` an optional provider. FR-33 gives the
base install "only the database driver."

So on the base install, the frozen CLI cannot execute a single successful invocation: its one
mandatory flag needs the `wpconfig` extra, and its AWS flags need the `aws` extra. FR-33's extras
list — `aws`, `azure`, `wpconfig`, `otel`, `all` — contains no `cli`. Meanwhile FR-36 asserts
`pip install wpdatabase2` succeeds from a clean environment, which is true and useless: the
installed artifact's CLI cannot run.

The same clash hits the library surface. FR-1 freezes `WpDatabase(wp_config=None, wp_connection=None)`,
and on a base install one of those two frozen construction paths raises. FR-24 makes the error
actionable, which is the right mitigation, but it does not change the fact that a *frozen* public
path stops working out of the box — and FR-6's suite, which must prove "every signature accepts its
documented arguments," has to run with the `wpconfig` extra installed. So the compatibility suite
never exercises the base install, which is the configuration this PRD changes most.

**Required:** decide whether the config reader is in the base install or add a `cli` extra and state
that `python -m wpdatabase2` requires it. Then split FR-6's suite into base-install and
all-extras runs, so the guard's scope covers both.

### H4 — §2's evidence is overclaimed, and the PRD misses a fourth defect that makes provisioning impossible on every server version.
`prd.md` §2 lines 38–43; `addendum.md` §E line 30; `database.py:154-181`.

§2 closes with "Each of these was reproduced directly, not inferred," and asserts that the
package's user-creation SQL "is a **syntax error** on MySQL 8." Addendum E calls ERROR 1064 "the
source of the observed" failure. The claim about the SQL in the abstract is correct. The claim that
this package produced it is not reachable through this code path.

The statement is issued as (`database.py:180-181`):

```python
cur_exec('GRANT ALL PRIVILEGES ON {n}.* TO %s@\'%\' IDENTIFIED BY %s;',
         (username, password))
```

`mysql-connector`'s `cursor.execute` substitutes parameters with Python `%`-formatting
(`operation % params`). The literal `'%'` host, followed by `'`, is an invalid conversion
specifier. Verified directly:

```
ValueError: unsupported format character ''' (0x27) at index 37
```

The statement therefore **never reaches any server**, on any version. You cannot have observed
ERROR 1064 through this package; you observed it by running the SQL by hand, which is fine as
verification of the SQL but is not what §2 says. On MySQL 8 you would not even get that far — per
`AGENTS.md:47-49` the pinned driver cannot authenticate to 8 at all, so `_connect(admin)` fails
first.

This matters for two reasons. First, the PRD's authority rests on that sentence; one overclaim in
the evidence section devalues the three findings that *are* reproduced. Second, it conceals a
fourth defect the PRD never lists: **`ensure_database_setup` has never worked on any server
version**, because the statement is malformed before transmission. Note also that `cur_exec`
catches only `connector.errors.ProgrammingError` (`database.py:158`), so the `ValueError`
propagates raw and the diagnostic log line never fires.

**Required:** correct §2 to say what was observed where. Add the paramstyle defect to the defect
list. Add a requirement that literal `%` never appears in a parameterised statement — FR-10 covers
identifier quoting only, and this is a distinct failure mode in the same code.

### H5 — FR-31's deprecation period cannot be served to anyone, and it forces FR-35's 1.0.0 to ship a known-wrong behaviour.
`prd.md` FR-5 (115–119), FR-31 (213–214), FR-35 (221–222), §2 (27–31).

FR-31: behaviour-breaking corrections "emit a deprecation warning for at least one minor release
before the change lands."

§2: no version of this package has been installable for six years. There is no installed base to
warn. The deprecation window would be served to an audience of zero.

Mechanically it is worse. To satisfy FR-31 and FR-35 together you must ship **1.0.0 with the known
defect intact** (`from_username_and_password` returning `None`) plus a warning, then correct it in
1.1.0. So FR-35's "stable, intentional public contract" deliberately ships a behaviour the same
document calls a defect, in order to honour a deprecation policy protecting nobody. FR-31, FR-35
and §2 cannot all hold.

Open question 5 half-notices this ("an immediate clean break may be more honest") but FR-5 and
FR-31 remain normative text. An open question does not neutralise a contradiction sitting in the
requirements.

**Required:** delete FR-31, break cleanly at 1.0.0, and enumerate the breaks in the release notes
per FR-4. Reintroduce a deprecation policy *after* 1.0.0, when there is an installed base for it to
protect.

### H6 — FR-19 and FR-20 contradict each other; FR-20 contradicts FR-1; and FR-1 is what forces FR-18's entire machine.
`prd.md` FR-18 (157–162), FR-19 (163–164), FR-20 (165–167), FR-1; `addendum.md` §C.

**FR-19 vs FR-20.** FR-19: resolve to the highest release whose `db_version` is `<=` the observed
value. FR-20: an unrecognised or **newer** `db_version` must be "reported as such." FR-19 always
produces an answer, including for a `db_version` above everything in the table — where it will
confidently return the newest known release. FR-20 demands that same input be reported as unknown.
There is no ceiling rule. As written they specify opposite behaviours for the same input.

**FR-20 vs FR-1.** FR-20 also requires "unrecognized" to be distinguishable from "no version
found," while simultaneously requiring `WpDatabaseVersion.wp_version` to keep returning `None`
"per its current contract." Both states return `None` on the frozen surface. The distinction FR-20
requires has nowhere to surface. FR-20 mandates an observable difference and forbids the only place
to observe it.

**Implementation trap the freeze walks into.** `db_version` comes back from MySQL as a string, and
the current map is keyed by strings (`database.py:218-275`). FR-19's `<=` must be numeric; a string
comparison orders `"9872"` above `"48748"`. Verified: `sorted(["9872","48748","38590"])` →
`['38590', '48748', '9872']`. Nothing in FR-19 says the comparison is numeric.

**And the structural point.** `wp_version` — a convenience string with no relationship to §1's
intent — is frozen by FR-1. That freeze is what obligates FR-18: a build-time generator that
fetches `wp-includes/version.php` across 884 release tags, a shipped data artifact, a documented
refresh command, and (Addendum C) an unresolved floor on how far back tags parse. **The freeze is
manufacturing scope.** Without FR-1's freeze, the honest requirement is "return the raw
`db_version` integer" and FR-18 evaporates. This is the clearest instance in the document of the
frozen surface making the rewrite more expensive rather than cheaper, and the PRD never weighs it.

FR-18 also has no freshness check, which is a user-rule-#4 problem: the runtime reads a shipped
table, i.e. a hand-kept list as far as the running code is concerned, and nothing requires CI to
assert the table still matches the source of truth. "Derived from a source of truth, never
hand-enumerated" is satisfied at generation time and unenforced thereafter.

### H7 — FR-27 is an open blocker sitting under the majority of the frozen surface, and the dependency chain is never drawn.
`prd.md` FR-27 (188–196), open question 1 (line 284).

FR-27 states it "blocks implementation of FR-26." The chain is longer than that and the PRD never
draws it:

```
FR-27 (unresolved: which wp-config.php reader)
  └─ FR-26 (config reading as a provider)
       ├─ FR-1  (WpDatabase(wp_config=...) — one of two frozen construction paths)
       │    └─ ensure() itself (__init__.py:38 constructs WpConfigFile unconditionally)
       ├─ FR-2  (CLI: --wp-config is required)
       ├─ FR-17 ($table_prefix — and Addendum D warns $table_prefix is a *variable*, not a
       │         define(), so it is not certain the chosen option can read it at all)
       └─ FR-6 / FR-36 (what the compatibility suite and the install check can exercise)
```

So one unresolved ADR blocks `ensure()` — the verb §1 says everything else supports — the CLI, and
most of what FR-6 can test. Yet FR-35 proposes shipping 1.0.0 as "a stable, intentional public
contract." You cannot promise contract stability while the reader underneath the primary entry
point is undecided among four options with materially different capabilities.

Addendum D is good work and should be promoted into the PRD as a decision, not left as an options
table. Note in particular that the vendoring option's regex extraction cannot read `$table_prefix`
reliably (Addendum D, closing note), which means FR-17 may be unsatisfiable under the option the
memlog says was chosen ("wpconfigr: hard fork", `.memlog.md` line 26).

**Required:** resolve FR-27 before any further planning. It is not an open question among eight; it
is the critical path.

### H8 — Security gaps: no TLS requirement anywhere, an unconfigurable `'%'` grant host, and the password literal outside FR-10's escaping rule.
`prd.md` NFR-1 (247–249), NFR-5 (257–261), FR-10 (136–138), FR-13 (142); `addendum.md` §B.

§1 sells this package on admin-credential hygiene: admin credentials should not live "any longer
than the one operation that needs them." Yet:

**(a) No TLS requirement exists.** Not an FR, not an NFR, not an open question. Admin credentials
and the WordPress user's password both cross the wire. Worse, NFR-5 *plans for the unencrypted
case*: "MySQL 8 `caching_sha2_password` over a non-TLS connection needs PyMySQL's `[rsa]` extra."
The PRD's default assumption is an unencrypted admin connection, and no requirement offers TLS
options, verification, or a documented default. For a package whose stated value is credential
hygiene, this is the largest unaddressed security hole in the document.

**(b) The `[rsa]`/`[ed25519]` extras are not in FR-33.** FR-33 names `aws`, `azure`, `wpconfig`,
`otel`, `all`. So per FR-33 the base install cannot authenticate to a default-configured MySQL 8
over a non-TLS connection — against the PRD's own primary target (G5) — and there is no extra
named to fix it. G6 ("base install dependency-light") and NFR-5 ("no compiler, no system
libraries") also sit awkwardly with pulling `cryptography` for `[rsa]`.

**(c) The password literal is outside FR-10's rule.** FR-10 and NFR-1 require *identifiers* to be
validated, quoted and escaped. But `ALTER USER ... IDENTIFIED BY '<password>'` in Addendum B is a
DDL literal that most drivers will not parameterise, and the password is attacker-influenced input
(it comes from `wp-config.php`). The higher-severity injection site is the one no requirement
covers.

**(d) `ALL PRIVILEGES` vs "least-privilege."** NFR-1 claims grants are "least-privilege and
database-scoped." FR-13 and Addendum B grant `ALL PRIVILEGES ON \`db\`.*`. Database-scoped: yes.
Least-privilege: no. `ALL` on a schema is arguably the right answer (WordPress core upgrades run
DDL), but then say so and drop the least-privilege claim, or specify the privilege list. As written
NFR-1 makes a security assertion the implementation contradicts.

**(e) The grant host is hardcoded `'%'`** (`database.py:180`, Addendum B) — any host — with no
requirement to narrow or configure it, and no mention in NFR-1's security posture.

### H9 — NFR-1 forbids exactly the information NFR-3 and FR-25 require, making the most common misconfiguration undiagnosable.
`prd.md` NFR-1 (247–249), NFR-3 (252–254), FR-25 (180–183), FR-24 (177–179).

NFR-1: "No credential, secret value **or secret identifier** appears in logs, traces, exception
messages or repr output."

NFR-3: "A failure states what was attempted, **against what target**, and what to do next."

FR-25 makes the AWS secret shape explicit and validated, "with a clear error when it is not met."

Now write that error. The most common configuration failure in this feature is a secret whose JSON
lacks `username` or `password`. The operator needs to know *which secret*. NFR-1 forbids naming it.
The resulting message — "a secret did not contain the expected keys" — is exactly the
undiagnosable failure NFR-2 and NFR-3 were written to eliminate.

The premise is also wrong. A Secrets Manager secret ID or ARN is not a secret; it is a resource
name, routinely logged by every AWS SDK and CloudTrail by default. NFR-1 over-classifies, and the
cost lands on supportability.

**Required:** narrow NFR-1 to secret *values* and credential material. State that resource
identifiers are loggable, and that it is the resolved value that must never appear.

### H10 — FR-5 miscounts the affected tests. There are three, not two.
`prd.md` FR-5 line 118.

FR-5: "called out explicitly because **two existing tests** assert the `None` return."

Three do:

- `tests/classes/test_credentials.py:43` — `test_from_username_and_password_username_none`
- `tests/classes/test_credentials.py:54` — `test_from_username_and_password_password_none`
- `tests/classes/test_connection.py:46` — `test_database_properties_credential_username_none`,
  which constructs `WpCredentials.from_username_and_password(None, 'password')` and asserts
  `instance.credentials is None`

The third is the interesting one, and it is the one the PRD missed: it asserts the `None` return
*propagating through* `WpConnection`, so under FR-5 it does not merely need rewriting — the
`WpConnection` construction now raises, changing that test's subject entirely. Note also that
`WpDatabase.__init__` calls `from_username_and_password` on wp-config values
(`database.py:42-44`), so FR-5 changes `WpDatabase(wp_config=...)` from "constructs with
`credentials=None`" to "raises" whenever `wp-config.php` is missing `DB_USER` or `DB_PASSWORD` —
a third-order behaviour change, unenumerated.

This is a 30-second check, in the one paragraph where the document claims precision. It suggests
the "reproduced directly" standard was not applied uniformly.

---

## Medium

### M1 — §9's "frozen surface intact" metric measures nothing about compatibility, and its counter-metric cancels itself.
`prd.md` §9 line 280.

Metric: "FR-6 suite green on every commit." Counter-metric: "Not achieved by freezing defects —
FR-4 still governs."

FR-6 checks imports, signatures and flag parsing. FR-4 authorises arbitrary behaviour change. So
the metric can read 100% green while the behavioural surface changes freely, and the counter-metric
explicitly permits that. The pair measures nothing. Per user rule #3, this is prose overstating its
own coverage — the worst case, because it stops the next reader from looking.

### M2 — NFR-2 is written as a judgement call when it could be a lint rule.
`prd.md` NFR-2 (250–251).

"No bare `except Exception` **that converts a defect into a benign-looking result**." The
qualifier makes it unenforceable: every site becomes an argument about whether the result looks
benign. The document itself says (Addendum E) that this one anti-pattern caused three defects,
which is the strongest possible case for mechanising it.

Write the check: `ruff` `BLE001` (or pylint `W0703`) as an error across `wpdatabase2/`, with
per-site `noqa` plus a justification comment as the only escape. That is one config line and
satisfies user rule #3's "write the check that enforces it in the same change."

### M3 — NFR-3, NFR-8 and three of five §9 metrics have no measurement procedure.
`prd.md` NFR-3 (252–254), NFR-8 (266–268), §9 rows 3–4.

- NFR-3: "Every error path is reachable in tests." Checkable only via branch coverage with a
  stated threshold. No threshold is given. The repo's own coverage report is commented out
  (`test.py:18`) and `AGENTS.md:39-40` confirms it.
- NFR-8 / §9 row 3: "Every public name's docstring matches behaviour," target "every public name."
  There is no procedure. Doctests, or a named review gate, or drop the metric.
- §9 row 4: "Every error path names cause and next step." Same class.

A metric with a 100% target and no measurement is decoration. Per user rule #3, say explicitly
what is mechanically covered and what is not.

### M4 — NFR-4 asserts a MariaDB floor the addendum says is unverified, and FR-38 pins no versions, so CI cannot test the claim.
`prd.md` NFR-4 (255–256), FR-38 (229–230); `addendum.md` §B line 35.

NFR-4 states a MariaDB floor of 10.1. Addendum B: the floor was inferred from the 10.1 branch
grammar and "the commonly cited 10.1.3 patch level could not be confirmed from an authoritative
page." So the requirement asserts as settled what the supporting document flags as unverified.

FR-38 then says integration tests run against "MySQL 8.x, MySQL 9.x and MariaDB" — no versions
pinned. A container matrix running MariaDB `latest` does not exercise a 10.1 floor. The guard's
scope does not cover the claim it is supposed to protect (user rule #4). Either pin the floor
version in the matrix or state the floor as unverified and stop publishing it as support policy.

### M5 — FR-4 and Addendum F disagree about the host/port order-dependence, and NFR-8 would force documenting a trap as intended behaviour.
`prd.md` FR-4, NFR-8, G1; `addendum.md` §F lines 98–100; `connection.py:40-54`.

Addendum F says the `db_host` setter's port-clobbering is "preserved behaviour, documented in
`AGENTS.md`." But it is not in the *documented contract* FR-4 defines: the setter's docstring reads
`"Gets the database host"` (`connection.py:41`) — wrong even about being a setter — and says
nothing about the port. So under FR-4 the behaviour is unprotected, while Addendum F declares it
preserved. Direct conflict.

NFR-8 makes it worse: it requires the docstring to match behaviour, so the rewrite must newly
*document a footgun as intended semantics* — which fights G1 ("better-designed") and NFR-3
(supportability). `AGENTS.md:50-52` already records this as a pitfall agents must work around.

Pick one and write it down: (i) freeze it, document it as a known wart, and add a deprecation path
to an explicit `db_port` argument; or (ii) break it and enumerate it under FR-4. The current
position is both.

Related: `tests/classes/test_database.py:141` asserts `db_port == '3306'` — a **string**. The
frozen surface therefore includes the port's type. PyMySQL's `connect(port=...)` expects an int
where `mysql-connector` coerced strings. Either coerce internally or change the property type and
enumerate the break. Unaddressed.

### M6 — The freeze omits CLI exit codes and log format, which are the actual machine contract for scenario S3.
`prd.md` FR-2, FR-28, §6 S3; `addendum.md` §F line 112; `__main__.py:58-77`.

FR-2 freezes flags and mutual-exclusion rules. Addendum F's inventory lists flags only. Neither
mentions exit codes — and for S3 ("an operator running Python automation") exit codes are the
contract.

Current behaviour: `arg_parser.error()` exits 2, so the following `exit(1)`, `exit(2)`, `exit(3)`
calls (`__main__.py:62, 71, 77`) are dead code. A rewrite that "preserves semantics" might
reasonably implement the apparently-intended 1/2/3 and thereby change every observable exit code.
FR-6 cannot detect it — it only parses flags.

Same class: FR-28 moves to structured events. For an operator whose automation greps the log, the
output format is an observable contract, and `--log-level` is frozen while the thing it controls is
being replaced. Neither FR-2 nor FR-6 covers it.

**Required:** add exit codes and log-output stability to the Addendum F inventory and to FR-6's
assertions, or explicitly declare them unfrozen.

### M7 — FR-11 is a no-op with no mechanism and no possible test.
`prd.md` FR-11 (140–142).

"Admin credentials ... are not retained on the instance after `ensure()` completes." They are
already not retained: `ensure_database_setup(admin_credentials, ...)` takes them as a parameter
(`database.py:145`) and never assigns them to `self`. The requirement describes the status quo
while reading as a security improvement.

Where retention actually happens is outside the instance's control: `WpCredentials._resolve_secret`
caches the resolved username and password into instance attributes (`credentials.py:55-60`), and
the **caller** holds that object. FR-11 cannot govern it. There is no mechanism (no scrubbing, no
context manager, no scoping rule) and no stated way to verify it.

Either specify the mechanism — e.g. admin credentials are accepted only inside a context manager
whose exit clears them, and the resolved values are never cached — or delete the requirement.

### M8 — Missing functional requirements a 15-line-of-SQL competitor would already cover.
Across §7.

If the differentiator is *correctness*, these gaps matter more than the provider framework:

- **`DB_CHARSET` / `DB_COLLATE` on `CREATE DATABASE`.** WordPress defines both in `wp-config.php`,
  and the config reader is already parsing that file. Creating the database with the server default
  (`utf8` vs `utf8mb4`) is a classic, hard-to-reverse WordPress breakage. No FR mentions charset or
  collation. This is cheap, real, and the sort of thing that would genuinely beat a hand-written
  snippet.
- **Connection timeouts.** FR-14 requires distinguishing "host unreachable," but with no timeout
  requirement that distinction takes the OS default (~2 minutes) to reach.
- **Partial failure.** MySQL DDL is non-transactional; `conn.commit()` (`database.py:187`) is
  theatre. If `GRANT` fails after `CREATE DATABASE`, state is half-built. Nothing states the
  recovery contract (presumably "re-run is safe," which needs FR-7 fixed first — see C5).
- **User exists with different grants, or a different host part.** See C5.
- **Multiple `ensure()` calls concurrently** (plausible in S2's control plane). No statement.

### M9 — §6 is entirely inferred, and its strongest scenario is the one a maintained competitor already serves.
`prd.md` §6 (83–97); `addendum.md` §G (116–119).

§6 opens by admitting it was "drawn from research and the code's shape, **not elicited from you**."
Every scenario is an assumption, and the PRD's entire scope rests on them.

S2 is labelled "the one demonstrated buyer for this shape." Addendum G identifies that signal as
Cyberfusion's `python3-cyberfusion-database-support` / `-wordpress-support`, both released
2026-09-15 and "actively maintained." That is a **competitor**, not a buyer. So the strongest
demand signal in the document is a maintained package already serving that need — which strengthens
§3's counterweight rather than answering it. The PRD does not notice.

S4 ("you use it in your own WordPress stacks") is the only scenario not inferred. If that is the
real driver, say so — and note that it argues for the minimal fix, not for 1.0.0 with a plugin
framework and multi-cloud providers.

### M10 — The non-goal "not replacing Ansible" is unfalsifiable and is doing rhetorical work.
`prd.md` §5 line 80.

"Replacing Ansible, Terraform or wp-cli for teams already standardized on them" cannot be tested,
observed, or violated. What it does is relabel §3's strongest objection — that Ansible already
solves this idempotently and is broadly maintained — as out of scope. Declaring a competitor out of
scope is not an answer to the competitor. Either engage with it in §3 (what does this do that
`community.mysql` does not?) or drop the non-goal, which currently reads as a deflection.

### M11 — FR-12 and FR-16 are undefined together.
`prd.md` FR-12 (141), FR-16 (152–154).

FR-12 freezes `force=True` as "skip the existence check and re-run setup." FR-16 rewires routing so
authentication and connectivity failures are reported rather than treated as a create signal. What
does `force=True` do when authentication fails? FR-12 says skip the check and proceed; FR-16 says
report. Unspecified, and it is the exact combination an operator reaches for when the first run
half-failed (see M8's partial-failure gap).

### M12 — FR-18 converts every WordPress release into a maintenance task in this repo.
`prd.md` FR-18 (157–162), §3 (59–64).

FR-18 ships a generated table and a "maintenance task with a documented command." WordPress ships
several releases a year. Each one makes this package's data stale, for a feature (`wp_version`) that
no §6 scenario needs and that §1's intent does not mention. §3's claimed differentiator is *being
maintained* — and FR-18 spends that scarce maintenance budget on the least valuable feature in the
package. See H6 for the freeze that forces it and for the missing freshness check.

---

## Low

### L1 — G1 is the headline goal and has no test.
`prd.md` G1 (line 68). "Modern, supportable, well-designed" has no criterion, so it can never be
failed. NFR-3 and NFR-8 are partial proxies; say so, and state what "supportable" means
concretely, or accept that the primary goal is a taste judgement and rank the testable goals
above it.

### L2 — FR-22 is redundant with FR-1.
`prd.md` FR-22 (173–175). "`from_aws_secrets_manager()` and `Secret` keep working per FR-1" is
FR-1. Delete it, or keep only the "when that provider is installed" qualifier, which is FR-24's
subject.

### L3 — Twelve `[ASSUMPTION]` tags, several load-bearing, inside a document proposing 1.0.0.
Counted: 12 occurrences, including the Python floor (FR-34), the extras names (FR-33), the version
number itself (FR-35), the deprecation policy (FR-31), the driver (NFR-5), the second provider
(FR-23), the OTel packaging (FR-30), and **all of §6 and all of §9** — the demand model and the
success criteria. Honest tagging, and better than silent invention. But a PRD whose users and
success metrics are both entirely assumed is not ready to authorise a rewrite, let alone a 1.0.0
stability promise. Resolve §6 and §9 first; they determine whether most of §7 should exist.

### L4 — FR-40's justification is about the planning tooling, not the project.
`prd.md` FR-40 (234–240). "`uv` is chosen over Poetry because it is already a hard requirement of
this repo's tooling, so it adds nothing new to install." The tooling in question is the BMad/agent
harness, not the package or its consumers. That BMad needs `uv` is not an argument about the right
build tool for a published Python library. The conclusion is probably correct — argue it on merit
(speed, PEP 621 support, interpreter provisioning for FR-34, `uv build`/`uv publish`) and drop the
circular reason. Also note FR-40 retires `build.sh`/`publish.sh`, which `AGENTS.md:15-17` says are
Shawn's release path — worth confirming that policy change is intended.

### L5 — FR-3 freezes the distribution name without weighing the discoverability problem it creates.
`prd.md` FR-3 (111); `addendum.md` §G line 118. Addendum G notes the nearest competitor is
"undiscoverable under any 'wordpress database' search," which is also true of `wpdatabase2` — a
name whose `2` suffix signals a fork of a dead one-star package. Freezing the name is defensible
for compatibility, but adoption, not compatibility, is this package's actual problem, and the PRD
never weighs the trade (e.g. keep `wpdatabase2` as an alias, publish under a findable name).

### L6 — The PRD never names an owner, which is the one thing the value claim depends on.
`prd.md` §3 (line 62). "The defensible value here is being maintained." No requirement, metric or
statement addresses who maintains it, at what cadence, or what happens when they stop. Given the
six-year dormancy documented in §2, this belongs in §9 as the primary counter-metric — with a
target that would actually be falsified by another dormant period.

---

## What would make this document defensible

Not a rewrite of the review's findings — a rewrite of the decision. In order:

1. **Resolve the premise (C1).** Put the four options — minimal fix, full rewrite, deprecate in
   favour of `community.mysql`, archive — side by side with costs, and pick. If the answer is the
   full rewrite because it is your own infrastructure and you want it well built, say that; it is a
   legitimate reason and it changes which FRs survive.
2. **Resolve FR-27 (H7).** It is the critical path, not an open question.
3. **Build the freeze baseline artifact (C3, C4, M6).** Docstrings and the Addendum F inventory at
   `e82e6aa`, committed, machine-readable, diffed by FR-6 — extended to raised types, return types,
   exit codes and log format. Until this exists, G2 is prose.
4. **Fix the state-model contradictions (C2, C5).** Write the (probe, credential set, outcome) →
   action matrix, including user and grant state, and say which frozen signature gives way.
5. **Cut to the value claim (H1, H2, M12).** Delete FR-23 and FR-29; reduce FR-21 to a callable,
   FR-25 to dict validation, FR-30 to "create no global OTel state"; drop `wp_version` or accept
   FR-18's cost explicitly. Roughly 10 of 41 FRs deliver everything §3 says is defensible.
6. **Add what actually beats 15 lines of SQL (H8, M8).** TLS options, charset/collation from
   `wp-config.php`, connection timeouts, grant host control, and a stated recovery contract for
   partial failure. These are the requirements that would justify the package's existence, and
   none of them is in the document.
