# PRD Quality Review — wpdatabase2

## Overall verdict

The diagnosis is excellent and the shape is right: §2's three defects were reproduced rather than
inferred (I re-verified all of them against the source), §3 states the counter-case that would kill
the project — "the defensible value here is **being maintained, installable and correct**... not
novel capability" — and §6 correctly refuses personas and journeys for a developer library. What is
at risk is everything downstream of that honesty. §7 does not follow from §3's thesis: 41 FRs, no
phasing, no prioritization, all nominally shipping as 1.0.0, including OpenTelemetry tracing and a
second cloud credential provider for a 750-line library whose stated win is that `pip install` works.
And the provisioning and state-inspection core — the part the rewrite exists for — contains two
adjacent contradictions and one unspecified observable contract, so an engineer cannot derive "done"
for it. This is a strong problem statement with a solution section that has not yet been decided.

## Decision-readiness — strong

This dimension is the PRD's best. Decisions are stated as decisions and the losing side is named.
FR-27 is labelled "**OPEN DECISION, NOT SETTLED**" with four candidates at real versions and an
explicit refusal to pick — "No option is selected here." FR-5 names a breaking change and says why
it is one ("two existing tests assert the `None` return"). FR-30's assumption is flagged as
genuinely ambiguous rather than resolved by the author's preference: "that is a real fork and your
answer could be read either way." FR-40 records why `uv` beat Poetry in terms someone could check
("already a hard requirement of this repo's tooling") and admits "the repo currently uses neither;
this is adoption, not migration."

§10's open questions are actually open. Item 5 argues *against* the PRD's own assumption — FR-5 and
FR-31 assume a deprecation period, and §10 replies "For a package nobody can currently install, an
immediate clean break may be more honest." That is a validator's-eye objection the drafter raised on
themselves, and it is the opposite of a rhetorical question.

The gap is that §3's counterweight is stated and then not used. It closes with an instruction —
"Scope decisions in this document should be read against that" — and §7 never does. Nothing in §7 is
cut, deferred, or justified against thin demand; the section instead grows an extensibility layer
(FR-21, FR-23), a tracing story (FR-30), and a build-time data-generation pipeline (FR-18). A
decision-maker reading §3 would ask "so what did we drop?" and find no answer.

### Findings

- **high** §3's counterweight is raised and then ignored (§3 → §7) — §3 concedes the hole is "roughly
  fifteen lines of SQL", that Ansible already fills it, and that "demand evidence is thin", then
  instructs the reader to weigh scope against that. §7 contains no cut, no deferral, and no FR
  justified against it. The strongest honest passage in the PRD is load-bearing for nothing.
  *Fix:* add a short subsection after §5 — "What the counterweight costs us" — naming the two or
  three FRs that would not exist if the thesis were applied strictly (candidates: FR-23, FR-30,
  FR-18's build-time generation), and either drop them, defer them past 1.0.0, or record why the
  thesis does not bind them.
- **low** No `[NOTE FOR PM]` callouts anywhere (whole document, 0 occurrences) — the function is
  served instead by `[ASSUMPTION]` and FR-27's "OPEN DECISION", so nothing is actually hidden. Noted
  only because downstream tooling that greps for the marker will find the PRD clean when it is not.
  *Fix:* mark the two real tensions (FR-4's unbounded scope, FR-30's mandatory-vs-extra fork) with
  the conventional callout so they survive extraction.

## Substance over theater — strong

Almost nothing here is furniture. §6 explicitly declines the theater the template invites — "no
personas, no narrated journeys" — and the four scenarios are ranked by evidence, not listed for
symmetry: S1 is "rated the most plausible demand", S2 is "the one demonstrated buyer for this
shape." §1's intent statement could not be swapped into another PRD; it names this package's actual
design idea (two credential sets, one discarded) and the verb it exists for.

The NFRs are the test case, and they pass. NFR-2 is traced to an observed root cause — "This single
anti-pattern is the root cause of three separate observed defects", which addendum E itemizes and
which I confirmed at `wpdatabase2/classes/database.py:101`. NFR-4 names a MariaDB floor of 10.1 with
the reason (`CREATE USER ... IF NOT EXISTS`), and the addendum admits the patch level could not be
confirmed. NFR-5 names three rejected drivers with versions, licenses, and the specific friction
("builds from source on Linux"). This is the opposite of "the system must be scalable."

Two items read as motivated by design elegance rather than by anything in §3 or §6. FR-23 exists "to
prove the interface is not AWS-shaped" — a requirement whose stated beneficiary is the abstraction,
not a scenario; none of S1–S4 needs a second cloud credential store. And G4 plus FR-30 make
OpenTelemetry a "first-class" capability of a library that opens a connection, runs four statements,
and exits.

### Findings

- **medium** FR-23's justification is the interface, not a user (§7.4) — "At least one additional
  provider is supported to prove the interface is not AWS-shaped." No scenario in §6 asks for Azure;
  the `[ASSUMPTION]` admits it comes from "your answer naming Azure", not from demand. The cost is a
  second cloud SDK's API surface to track for 1.0.0.
  *Fix:* satisfy the anti-AWS-shaping goal with a test double or a local-file/environment provider
  (which S1 and S3 would actually use) and defer Azure Key Vault until someone asks, recording that
  as the trigger.
- **low** FR-11 restates current behaviour as a requirement (§7.2) — admin credentials are already
  never stored on the instance; `ensure_database_setup(admin_credentials, ...)` takes them as an
  argument. As written FR-11 is satisfied by the code being rewritten. Note that the real retention
  risk is elsewhere: `WpCredentials._resolve_secret()` caches the resolved username and password on
  the caller-held object permanently, and `.username`/`.password` are frozen public properties.
  *Fix:* re-aim FR-11 at the credentials object's lifetime, or state explicitly that FR-11 is a
  preservation requirement rather than a change.

## Strategic coherence — thin

The thesis exists and is well stated — installability, correctness and maintenance, not capability.
§9's metrics genuinely validate it (install-from-clean-env, server matrix, docstring accuracy,
diagnosable failures, frozen surface) rather than measuring activity, and every row carries a real
counter-metric that names the cheat it forbids: "Not achieved by weakening assertions or skipping
tests", "Not achieved by freezing defects — FR-4 still governs." That is better than most PRDs
manage.

What is missing is any connection between the thesis and the ordering of §7. There is no MVP scope,
no phasing, no priority marks, and FR-35 sets the release at **1.0.0**, which reads as all 41 FRs
landing together. On the thesis, the shortest path to value is small and identifiable: fix the pin
(FR-36), fix the `except Exception` swallow (NFR-2, FR-14–16), fix the MySQL 8 `GRANT` syntax error
(FR-8, FR-9), move to `pyproject.toml` (FR-32), publish. That is perhaps eight requirements. The
other thirty-three are a supportability program — pluggable providers, a second cloud store,
build-time data generation, structured events, correlation IDs, OTel spans, a three-server
integration matrix — and the PRD gives a reader no way to tell which of them 1.0.0 waits for. For a
package that "sat uninstallable for six years without a bug report loud enough to prompt a fix"
(§3), the risk this creates is specific: the rewrite does not ship, and the defect §2 documents stays
live.

The scope kind is also unstated. §3 argues a problem-solving scope ("being maintained, installable
and correct"), while §7.4's provider interface and FR-23 are platform-scope logic. The two are not
reconciled, and FR-21's "The base install carries none of them" is the point where platform logic
starts contradicting the frozen surface (see Done-ness, FR-26).

### Findings

- **critical** No phasing, prioritization, or MVP boundary across 41 FRs (§7 entire, with FR-35) —
  nothing marks what 1.0.0 requires versus what follows, and FR-35's "versioned **1.0.0**, reflecting
  a stable, intentional public contract" implies the whole set. The thesis in §3 identifies a much
  smaller shipping unit; the PRD does not draw it. Story creation downstream will flatten 41 FRs into
  one undifferentiated backlog.
  *Fix:* split §7 into "1.0.0 — restores the package" and "post-1.0.0 — supportability", placing
  FR-36, FR-32, FR-8, FR-9, FR-14–16, FR-1, FR-6, FR-39 in the first and defending each item kept in
  the first against §3's counterweight. Add `[NON-GOAL for MVP]` to what moves out.
- **high** G4 and FR-30 make observability a headline goal without deriving it from the thesis or any
  scenario (§4, §7.5) — "**OpenTelemetry tracing is first-class**: spans for `ensure()` and each
  database operation." The justification given is provenance, not need: "Per your answer this is a
  core capability, not an afterthought." For a library whose whole job is one short idempotent
  operation, spans are a cost carried by every importer's dependency review; S1 (ephemeral test
  databases) and S4 (own infrastructure) get nothing from them. The genuinely load-bearing
  observability requirement is NFR-3/FR-14 — knowing *why* a failure happened — and that needs no
  tracing library at all.
  *Fix:* keep FR-28 and FR-29 (structured events, correlation ID) in 1.0.0 since NFR-3 depends on
  them; move FR-30 behind the `otel` extra as a post-1.0.0 item, and demote G4 to "failures are
  diagnosable" so the goal states the outcome rather than the technology.
- **medium** §9's metrics have no horizon, owner, or verification method (§9) — four of five rows are
  CI-assertable and effectively already specified by FRs, but "Documented-contract accuracy — Every
  public name's docstring matches behaviour" and "Diagnosable failures — Every error path names cause
  and next step" have no check behind them and no point at which they are measured. As written they
  cannot be failed.
  *Fix:* give each row the mechanism (e.g. docstring accuracy → the FR-6 suite asserting documented
  signatures plus a doctest or `pydoclint` gate; diagnosable failures → branch coverage on error
  paths at a stated threshold, which NFR-3 already half-promises) and a measurement point ("at each
  release tag").

## Done-ness clarity — thin

This is the dimension that matters most for what comes next, and the provisioning and
state-inspection core — §7.2 and §7.3, the reason the rewrite exists — is not implementable as
written. Three specific problems, in descending order of consequence.

First, FR-7 and FR-8 contradict each other one line apart. FR-7: `ensure()` "running it against an
already-correct database and user succeeds and **changes nothing**." FR-8 requires, unconditionally,
"then `ALTER USER` to set the password (required — `IF NOT EXISTS` will not update an existing
account's password)." Every run therefore rewrites the WordPress user's password. That is a server
state change, it is observable, and under a `password_history` or `password_reuse_interval` policy it
can *fail* — turning the idempotent happy path into an error. The addendum's SQL block (§B) has the
same unconditional `ALTER USER`. An engineer must choose between FR-7 and FR-8 and the PRD does not
say which wins.

Second, FR-14's four outcomes have no observable contract. FR-14 requires the check to distinguish
"database present and reachable; database absent; authentication failed; host unreachable", and
addendum E calls fixing this "the highest-leverage single change in the rewrite." But FR-15 keeps
`test_config()` returning a boolean, FR-1 freezes `does_database_exist()` as a boolean, and FR-16
says only that a failure "is reported rather than treated as a reason to create things." Reported
*how*? A new exception hierarchy? A return enum on a new method? `throw=True`? Nothing in the PRD
says, and FR-1 freezes the surface through which it would have to surface. The single most important
behavioural fix in the document has no testable consequence attached.

Third, FR-4 is an unbounded license. "Where current *behaviour* contradicts the *documented*
contract, the documented contract wins and the behaviour is corrected... Each such correction is
enumerated in the release notes." The enumeration is deferred to release notes that do not exist yet,
so the PRD never states how many breaking corrections there are. FR-5 presents itself as the
exception worth calling out, but at least two more hide inside other FRs: FR-15 changes
`does_database_exist()` from a connection test to an existence check, and FR-18/FR-19 change what
`WpDatabaseVersion.wp_version` returns for db_versions the current table already recognizes (the
committed map at `wpdatabase2/classes/database.py:218` says `38590 → "4.9.9"`, while a
source-derived map with FR-19's "highest release whose `db_version` <= observed" rule yields a
different, later 4.9.x string). FR-31's deprecation requirement only names FR-5, so the deprecation
surface is scoped to one of at least three breaks.

Beyond those, the adjectives: FR-24's "actionable error", FR-25's "clear error when it is not met",
NFR-3's "states what was attempted, against what target, and what to do next". FR-24 is the only one
that supplies a bound, and it is a good one — "naming the exact extra to install — never a bare
`ImportError`" — which is exactly what the other two need and lack.

Last, the PRD states mechanical enforcement as a value in one place and then does not apply it. FR-6
is explicit: "This suite is the mechanical enforcement of G2, **not a prose promise**." Good. But
NFR-1 (no secret in logs, traces, exception messages or repr), NFR-2 (no bare `except Exception`) and
NFR-8 (every docstring matches behaviour) are left as prose, and NFR-2 in particular is a one-line
linter rule (`ruff` BLE001 / `pylint` W0703) guarding the anti-pattern the PRD itself calls the root
cause of three defects. The PRD knows the standard; it applies it to the compatibility surface and
the install, and not to security or to the defect class that caused the outage.

### Findings

- **critical** FR-7 and FR-8 contradict each other on idempotency (§7.2) — FR-7 promises a re-run
  "changes nothing"; FR-8 mandates an unconditional `ALTER USER ... IDENTIFIED BY` on every run,
  which rewrites the password and can fail under server password-reuse policy. Addendum §B repeats
  the unconditional form.
  *Fix:* decide the rule and state it in FR-7 — either "password is set only when the user is newly
  created, or when the caller passes an explicit reconcile/force flag (FR-12)", or amend FR-7 to
  "converges to the configured state; the WordPress user's password is re-asserted on every run" and
  add the failure mode to NFR-3's diagnosable set.
- **critical** FR-14's four outcomes have no observable contract through the frozen surface
  (§7.3, FR-14–FR-16 against FR-1) — the distinction addendum E calls the highest-leverage change in
  the rewrite is specified only as an internal capability; FR-15 keeps a boolean return and FR-16
  says failures are "reported" without saying through what. No engineer can write a test for
  "authentication failed" from this PRD.
  *Fix:* specify the mechanism as an FR — e.g. a new exception hierarchy (`AuthenticationFailed`,
  `HostUnreachable`) raised by a new method, with `test_config()` and `does_database_exist()`
  retaining their booleans for FR-1 compatibility by catching them — and add the four outcomes to
  FR-6's or FR-38's assertions so each is exercised.
- **high** FR-4 grants unbounded behaviour-change license with no enumeration in the PRD (§7.1) —
  "Each such correction is enumerated in the release notes" defers the only list that exists. FR-5
  reads as the single break; FR-15 and FR-18/FR-19 are two more that are never labelled as such, so
  FR-31's deprecation requirement under-covers.
  *Fix:* enumerate the FR-4 corrections in the PRD as a table (name, documented contract, current
  behaviour, new behaviour, breaking y/n, deprecation required y/n). If the list cannot be completed
  now, say so and make completing it a precondition alongside FR-27.
- **high** NFR-1, NFR-2 and NFR-8 are prose promises in a PRD that names prose promises as
  insufficient (§8 against FR-6) — NFR-2 guards the documented root cause of three defects and is
  enforceable by one linter rule; NFR-1's "never appears in logs, traces, exception messages or repr"
  is checkable by a test that asserts secret material is absent from captured log output and
  `repr()`; NFR-8's docstring accuracy is the one §9 row with no mechanism.
  *Fix:* add the checks in the same change as the rules — enable BLE001/W0703 in the FR-37 lint gate
  with no per-file ignores, add a redaction test to the FR-6 suite, and name the docstring-accuracy
  gate. Derive the lint scope from the package source tree, not a hand-kept file list.
- **medium** FR-19 and FR-20 conflict on unknown `db_version` values (§7.3) — FR-19 resolves to "the
  highest release whose `db_version` is less than or equal to the observed value"; FR-20 says an
  "unrecognized or newer `db_version` is reported as such" and `wp_version` "continues to return
  `None` for unknown values." Under FR-19 a newer value resolves to the latest known release; under
  FR-20 it is unknown and returns `None`. Both cannot hold.
  *Fix:* state the precedence explicitly — e.g. exact match returns the release; a value above the
  table's maximum is "newer than known" and yields `None`; a value between known entries resolves
  downward per FR-19 — and give each of the three cases a test.
- **medium** FR-18/FR-19 change `wp_version` return values without being listed as a break (§7.3
  against FR-4/FR-5/FR-31) — the committed table maps each `db_version` to the *last* patch release
  carrying it (`38590 → "4.9.9"`); a source-derived table under FR-19's rule will return a different
  string for values callers already resolve successfully today. `.db_version` also currently holds
  the raw column value as a string, while FR-19's `<=` comparison implies numeric ordering, so the
  property's type may change too.
  *Fix:* add both to the FR-4 enumeration, and state whether `.db_version` remains a string.
- **medium** Adjective-bounded error requirements (FR-25, NFR-3) — "a clear error when it is not
  met", "what to do next". FR-24 shows the standard these should meet ("naming the exact extra to
  install — never a bare `ImportError`").
  *Fix:* give FR-25 the required message content (which keys were expected, which were found — names
  only, never values, per NFR-1) and give NFR-3 a testable form ("every raised exception names the
  operation, the target host and database, and one remediation").
- **medium** No test framework named, and the existing hand-rolled runner is not retired (§7.6) —
  FR-40 explicitly retires `build.sh` and `publish.sh`, but `test.py` — a bespoke script wrapping
  `coverage run -m unittest discover` — is never mentioned, and no FR says whether the rewrite's
  tests are pytest or unittest. FR-6, FR-37, FR-38 and NFR-3's "every error path is reachable in
  tests" all depend on the answer.
  *Fix:* name the framework in FR-37, state that `test.py` is retired in favour of invoking it
  directly (or via a `uv` task per FR-40), and make FR-38's container fixtures a fixture in that
  framework rather than new scaffolding.

## Scope honesty — adequate

§5 does real work rather than restating the goals negatively. "Replacing Ansible, Terraform or wp-cli
for teams already standardized on them" is the non-goal that matters, because §3 just conceded
Ansible "already fills it idempotently and is broadly maintained" — drawing that boundary
immediately after is honest sequencing. §3's counterweight is the most candid passage I have seen in
a PRD of this kind: it volunteers "the ancestor package earned one star in eight years" and "sat
uninstallable for six years without a bug report loud enough to prompt a fix." The inferred sections
are labelled at the top (§6: "drawn from research and the code's shape, **not elicited from you**")
rather than at the bottom.

Three gaps. There is no Assumptions Index, and the 12 inline `[ASSUMPTION]` tags do not round-trip
through §10: FR-18 (build-time generation of the version map), FR-33 (extra names), FR-35 (releasing
as 1.0.0), FR-37 (GitHub Actions) and NFR-5 (PyMySQL as the driver) appear in no open question and no
index. NFR-5 is the striking one — the driver choice is arguably the most consequential technical bet
in the document, it carries license and packaging consequences spelled out in addendum §A, it is
tagged `[ASSUMPTION]`, and a reader working only from §10 would never learn it was assumed.

Second, §5's non-goals are all "not this product" and none is "not this release." With no
`[NON-GOAL for MVP]` anywhere and no phasing (see Strategic coherence), a reader cannot tell whether
FR-23, FR-30 or FR-18 are commitments or aspirations — and the PRD's silence defaults them to
commitments.

Third, open-items density is high for the stakes and only one item is triaged. Counting: 12
`[ASSUMPTION]` tags, 8 open questions, and FR-27's open decision — roughly 21 open items against 41
FRs, on a "published library, real users" PRD. FR-27 is correctly marked "Blocking", and it is the
only one. Nothing says whether NFR-5's driver, FR-34's Python floor or FR-35's version number must
close before implementation starts, or whether implementation can begin on §7.2 while they stay open.
That is defensible for a Fast-path draft, but the PRD should say it rather than leave the reader to
infer it.

### Findings

- **medium** No Assumptions Index; 5 of 12 `[ASSUMPTION]` tags never surface in §10 (§7/§8 against
  §10) — unrepresented: FR-18, FR-33, FR-35, FR-37 and NFR-5. NFR-5 is the driver decision, with
  license and install-friction consequences documented in addendum §A but no elicitation ask
  attached.
  *Fix:* add an Assumptions Index as §11 listing all 12 with their FR/NFR anchor and whether each is
  awaiting confirmation, and promote NFR-5's driver choice to a numbered open question.
- **medium** No `[NON-GOAL for MVP]` callouts; §5 does not separate "not this product" from "not this
  release" (§5) — every non-goal is a permanent boundary, so every FR in §7 reads as a 1.0.0
  commitment by default. This is the same gap as the phasing finding, seen from the omissions side.
  *Fix:* once §7 is split by release, mark the deferred items `[NON-GOAL for MVP]` in place so a
  reader of §7.4 or §7.5 alone sees the deferral without consulting §5.
- **medium** Only FR-27 is triaged against "can implementation start?" (§10) — 21 open items, one
  labelled blocking, and no statement of what the other 20 block or do not block. QQ3 (Python floor)
  and NFR-5 (driver) are both prerequisites for FR-32/FR-33/FR-36 work.
  *Fix:* tag each §10 item *blocking implementation* / *blocking release* / *non-blocking*, and say
  explicitly which parts of §7 can proceed with FR-27 still open.

## Downstream usability — adequate

Mechanically this extracts cleanly. FR-1 through FR-41 and NFR-1 through NFR-8 are contiguous with no
gaps and no duplicate definitions; every `FR-`/`NFR-`/`G` cross-reference in the document resolves to
a defined ID. Sections stand alone reasonably well — §7.3 is readable without §7.2, and FR-27 carries
its own candidate list rather than pointing "see above." The addendum is correctly separated as
architecture input and each of its sections declares what it feeds ("feeds FR-8, FR-9").

Two things will cost the downstream workflows. There is no glossary, and "identifier" carries four
distinct meanings: SQL identifiers (FR-10, "Database and user identifiers are validated"), secret
identifiers (NFR-1, `Secret(identifier=...)`), and correlation identifiers (FR-29). Two of those
collide inside NFR-1's adjacent sentences — "No credential, secret value or secret identifier appears
in logs" followed immediately by "Identifiers reaching SQL are validated, quoted and escaped." A
security NFR is the worst place for that ambiguity, because an implementer reading only NFR-1 could
plausibly conclude that secret identifiers need SQL escaping, or that SQL identifiers must be
redacted from logs — and redacting the target database name from logs would defeat FR-28 and NFR-3.

Second, the frozen surface — the PRD's one hard constraint, "the outward surface does not break"
(§1) — is only partly in the PRD. FR-1 lists importable names; the actual signatures, properties and
the behavioural quirk that FR-6 must assert live in addendum §F, a document whose own header says it
is "depth that belongs downstream" and "deliberately kept out of the PRD narrative." FR-6 promises
"every signature accepts its documented arguments" while the signatures sit in the file designated as
not-the-PRD.

There is also one place where the provider abstraction and the frozen surface appear to be in direct
conflict, which will surface as the first architecture question: FR-21 says credential sources are
pluggable and "The base install carries none of them", FR-26 makes reading `wp-config.php` "itself an
optional provider", and FR-1 freezes top-level `wpdatabase2.ensure(wp_config_filename, ...)` — which
takes a *path* and must therefore parse `wp-config.php`. On a plain reading, the base install cannot
execute the package's headline verb, the one §1 says "everything else in the package supports."
FR-26 asserts "The connection-only core works without it" without acknowledging that `ensure()` is
not in that core. FR-17 has the same hidden dependency — honouring `$table_prefix` requires the
reader FR-27 has not chosen, and addendum §D flags that `$table_prefix` "is a variable rather than a
`define`... worth confirming the chosen option can read it at all" — yet the PRD marks FR-27 as
blocking only FR-26.

### Findings

- **high** The base install cannot run `ensure()`, and the PRD does not say so (FR-21 + FR-26 against
  FR-1 and §1) — `ensure(wp_config_filename, ...)` is frozen and takes a path; if config reading is
  an optional provider that the base install omits, the frozen entry point raises on a bare install.
  Either G6's "dependency-light base" or FR-1's frozen `ensure()` has to give, and nothing states
  which. This is the first thing architecture will hit.
  *Fix:* state the intended packaging explicitly — most likely "the `wpconfig` extra is required for
  `ensure()` and the CLI; the connection-only path (`WpDatabase(wp_connection=...)`) is the
  dependency-free core" — and say whether `pip install wpdatabase2` pulls that extra by default. Add
  FR-17 to FR-27's blocked list.
- **medium** No glossary, and "identifier" is overloaded four ways, twice within NFR-1 (§8 NFR-1,
  FR-10, FR-29, addendum §F) — SQL identifier / secret identifier / correlation identifier /
  `Secret(identifier=)`, with the first two in adjacent sentences of the same security NFR.
  *Fix:* add a short glossary (*SQL identifier*, *secret id*, *correlation id*, *provider*,
  *documented contract*, *frozen surface*) and use the distinct terms in NFR-1, FR-10 and FR-29.
  "Documented contract" and "frozen surface" are already used consistently — the glossary would just
  pin them.
- **medium** The frozen-surface inventory lives in the addendum, not the PRD (FR-1/FR-6 against
  addendum §F) — FR-6 asserts signatures that the PRD never states, and addendum §F is explicitly
  framed as out-of-PRD downstream depth. It also carries the one behavioural quirk compatibility
  depends on: the `db_host` setter re-parses `host:port` and overwrites the port, "so assignment
  order matters."
  *Fix:* move §F inline as §7.1's appendix (it is short), or have FR-1 name it as normative — "the
  frozen surface is the inventory in addendum §F, which FR-6 asserts mechanically" — so the
  constraint is not defined in a document declared non-binding.
- **low** FR-40 cites "the FR-34 matrix" but FR-34 defines a floor, not a matrix (§7.6) — FR-34 is
  "declares a Python floor and ships type hints"; the matrices are FR-38 and NFR-4. The ID resolves
  but the referent does not.
  *Fix:* say "interpreter provisioning for the Python versions tested under FR-37", and add the
  version list to FR-34 or FR-37 if a matrix rather than a floor is intended.

## Shape fit — strong

The shape is right and deliberately chosen. This is a brownfield capability spec for a single-verb
library, and the PRD spends its rigor where that shape demands it: a frozen-surface contract (§7.1)
with mechanical enforcement (FR-6), a compatibility matrix (NFR-4), and reproduced defect evidence
(§2). It spends none on ceremony the shape does not support — §6 declines personas and journeys with
a stated reason ("this is a developer library rather than an end-user product"), and there are no UJs
at all, which is correct here; inventing protagonists for `ensure()` would have been pure overhead.
§9 is correctly operational (CI-assertable release properties) rather than user-facing.

Brownfield accuracy, which this shape makes non-negotiable, holds up under checking. I verified
against the source: `setup.py` pins `wpconfigr>=1.0.0,<=2.0.0` (§2); `.circleci/config.yml` uses
`circleci/python:3.7.1` and installs via `pip install -e .[dev]`, which cannot resolve that pin
(FR-37); `test_config()` wraps `with self._connect(...) as conn` in a bare `except Exception`
(§2, NFR-2, addendum §E); `does_database_exist()` is literally `return self.test_config(False)`
(FR-15); `get_database_version()` hardcodes `` `wp_options` `` (FR-17); `InvalidDatabaseNameError` is
defined and exported but never raised (FR-10); `GRANT ... IDENTIFIED BY` is the SQL actually emitted
(FR-8); `boto3` and `wpconfigr` are imported unconditionally at `wpdatabase2/__init__.py:8` and `:10`
(FR-26); `build.sh` really does run `sudo python3 setup.py install` (FR-40). Every specific claim I
checked was accurate. That is unusual and it is what makes the rest of the PRD trustworthy.

Two small notes. The README claim in FR-39 is slightly off in a way worth correcting before it
becomes a story: the snippet is `import wpdatabase2` followed by `wpdb = WpDatabase('path to
wp-config.php')`, so it raises `NameError` before it could raise `InvalidArgumentsError` — the
constructor never runs. And §6's S4 addresses the reader in the second person ("You use it in your
own WordPress stacks"), which is honest for a solo-maintained library but means the PRD's audience
and its user are the same person, so §6 cannot be independently validated. That is a property of the
situation rather than a defect; it is worth naming only because §10 item 8 asks for correction of §6
and there is no one else to give it.

### Findings

- **low** FR-39's README claim misstates the failure mode (§7.6) — the example raises `NameError`
  (`WpDatabase` is never imported), not `InvalidArgumentsError`. Separately, the README's
  Prerequisites table lists `DB_HOST`, `DB_USER` and `DB_PASSWORD` but omits `DB_NAME`, which
  `WpDatabase.__init__` reads and without which nothing works — a documentation defect FR-39 does
  not mention.
  *Fix:* amend FR-39 to name both (missing import and missing `DB_NAME` row), and add the CircleCI
  badge to the list of things the README correction must remove, given FR-37 retires CircleCI.

## Mechanical notes

- **ID continuity** — clean. FR-1…FR-41 and NFR-1…NFR-8 contiguous, no gaps, no duplicate
  definitions (FR-27 is bolded three times, but twice inside its own body as self-reference). G1–G6
  and S1–S4 contiguous. Every `FR-`/`NFR-`/`G` cross-reference in the document resolves to a defined
  ID. The only defective reference is semantic, not numeric: FR-40's "the FR-34 matrix" (FR-34
  defines a floor).
- **Assumptions Index roundtrip** — no index exists. 12 inline `[ASSUMPTION]` tags (§6, FR-5, FR-18,
  FR-23, FR-30, FR-31, FR-33, FR-34, FR-35, FR-37, NFR-5, §9). Seven reach §10; five do not — FR-18,
  FR-33, FR-35, FR-37, NFR-5. Three §10 items (1, 4, 6) have no inline tag anchoring them, which is
  fine for FR-27 (marked as an open decision in place) but leaves items 4 and 6 unanchored to any FR.
- **Glossary** — absent. Real drift on "identifier" (four meanings; see Downstream usability).
  "Documented contract", "frozen surface", "provider" and "correlation identifier" are each used
  consistently, so a glossary would be cheap to add.
- **Callout markers** — zero `[NOTE FOR PM]` and zero `[NON-GOAL for MVP]` in the document. The
  functions are partly served by FR-27's "OPEN DECISION" label and by §5, so the omission is more a
  tooling-extraction problem than a content one.
- **Section coverage for the stakes** — present and appropriate for a brownfield capability spec:
  intent, justification, gap with counter-case, goals, non-goals, scenarios, FRs, NFRs, metrics with
  counter-metrics, open questions. Missing for "published library, real users": an Assumptions Index,
  a glossary, a release/phasing boundary, and an FR-4 breaking-change table.
- **Addendum hygiene** — each section declares what it feeds, and unverified claims are marked as
  such ("Unverified: how far back tags carry a parseable `$wp_db_version`"; "the commonly cited
  10.1.3 patch level could not be confirmed"; "PyPI no longer serves download counts"). Addendum §F,
  however, is normative in practice despite the header disclaiming it (see Downstream usability).
