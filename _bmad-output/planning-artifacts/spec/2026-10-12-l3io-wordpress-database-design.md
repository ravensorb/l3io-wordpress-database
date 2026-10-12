---
title: l3io-wordpress-database — design specification
status: draft, for review
date: 2026-10-12
owner: Shawn Anderson
replaces: the PRD folder prds/prd-py-wordpress-database-2026-09-15/ (removed by this work)
---

# l3io-wordpress-database — design specification

This is the single requirements document for the package. It states what the
package is and does. Where a requirement exists because of a risk, the risk is
given beside it.

## 1. Purpose and callers

`l3io-wordpress-database` owns the operations a WordPress site performs against its
MySQL or MariaDB database: inspecting it, provisioning it, changing its accounts,
destroying it, and exporting and importing it. Every operation acts **on behalf of
the caller, with credentials the caller supplies**. Every operation can be
**checked before it runs**, and its answer is typed, so a caller can branch on it
rather than parse a message.

It imports as `l3io.wp.database`, a PEP 420 namespace shared with
`l3io-wordpress-config` and `l3io-wordpress-backup`.

Callers:

- **`l3io-wordpress-backup`**. Every database action backup takes goes through this
  package: existence and emptiness checks, provisioning a staging database, export,
  import, and dropping the database that loses a cutover. Backup never issues SQL
  against a site's database itself, and never handles a database password itself.
- **Python code using it directly**: test suites provisioning throwaway databases,
  provisioning scripts, and migration tooling.
- **Operators**, through the `l3io-wordpress-database` command line.

## 2. Principles

1. **Operations, not SQL.** A caller names an operation. The package chooses the
   statements and the client-tool invocation, and owns their correctness across
   server families.
2. **Check first, always.** Each mutating or transferring operation `X` has a
   `check_X(...) -> Verdict` that changes nothing. `X(...)` runs the same check and
   refuses on any blocker, so the check is never skipped and never differs from the
   run. Backup's Dry Run is a call to `check_X`.
3. **Credentials are parameters.** No credential is stored on a long-lived object.
   Each operation takes the credential source it needs. Administrative operations
   take administrative credentials explicitly and never fall back to the WordPress
   account, because that fallback is privilege escalation by accident.
4. **No secret is ever exposed.** No password appears in a process argument vector,
   a child's environment, a file on disk, a log record, a span, an exception message
   or a `repr`. Secret *identifiers* (a secret's name, an environment variable's
   name) may appear, because an error naming no source is not actionable.
5. **Existence is answered by the administrator** (family rule AD-29). A failed login
   by the account being provisioned is evidence about that account, never about the
   database.
6. **Destruction is named twice.** A destructive call requires its target to be
   repeated, so a wrong variable cannot destroy a different database.
7. **Maintained libraries, not hand-rolled ones** (global rule 1). The SQL dump
   format is the server's own client tools. Encryption is `age` via `pyrage`. The
   `wp-config.php` reader is `l3io-wordpress-config`.

Family rules this package is bound by, owned by backup's architecture spine and not
restated here: AD-2 (dependency direction), AD-8 (an optional dependency is an
optional import), AD-9 (resolution is an explicit call), AD-14 (only package-owned
error types cross the boundary), AD-15 (release order and the resolvability gate),
AD-27 (PEP 420 namespace), AD-28 (a GRANT's database name is escaped), AD-29.

## 3. Public surface

No name carries a `Wp` prefix; the namespace already says WordPress. Every public
name is exported from `l3io.wp.database`.

| Module | Public names |
|---|---|
| `credentials` | `CredentialSource` (protocol), `ResolvedCredentials`, `Explicit`, `Environment`, `WpConfigFile`, `AwsSecretsManager`, `CredentialChain` |
| `connection` | `Connection` |
| `verdict` | `Verdict`, `Finding`, `Code`, `Severity` |
| `server` | `ServerInfo`, `ServerFamily`, `ClientTool` |
| `inspection` | `survey`, `Survey`, `inspect`, `ConnectionState`, `schema_version`, `SchemaVersion` |
| `provision` | `ensure`, `EnsureResult`, `rotate_password`, `revoke`, `drop_user`, `drop_database`, `OperationResult`, and `check_` for each |
| `transfer` | `dump`, `iter_dump`, `DumpStream`, `load`, `TransferResult`, `check_dump`, `check_load` |
| `encryption` | used through `dump(recipients=)` and `load(identities=)`; `generate_identity` |
| `identifiers` | `quote_identifier`, `quote_grant_database`, `validate_database_name`, `validate_user_name` |
| `errors` | `DatabaseError` and its subclasses (section 10) |
| (root) | `Database`, a facade binding one `Connection`; `__version__` |

No module shares a name with a function exported from the package root: an
imported submodule rebinds that attribute, so the root export would be silently
replaced. A test asserts it.

`Database(connection)` exposes every operation as a method taking the same
arguments minus the connection. The free functions remain the primary API. The
facade exists so one object can serve one site.

Not provided: async variants, connection pooling, writing `wp-config.php` (that is
`l3io-wordpress-config`), WordPress table creation (`wp core install`), and content
or URL rewriting (WP-CLI).

## 4. Connection

`Connection(host: str, database: str, port: int = 3306)` is frozen. Construction
validates the host, the port range and the database name (`validate_database_name`).
`Connection.from_db_host(db_host, database)` accepts WordPress's `DB_HOST`, including
`host:port`. A `Connection` carries no credentials.

## 5. Credentials

```python
class CredentialSource(Protocol):
    @property
    def source(self) -> str: ...          # a label for logs; never the secret
    def resolve(self) -> ResolvedCredentials: ...

@dataclass(frozen=True)
class ResolvedCredentials:
    username: str
    password: str                          # redacted in repr
    source: str                            # which source produced it
```

Any object satisfying the protocol is accepted. Nothing needs to subclass a package
type. Built-in sources:

| Source | Reads | Extra |
|---|---|---|
| `Explicit(username, password)` | the given values | — |
| `Environment(username_var="DB_USER", password_var="DB_PASSWORD")` | the named variables | — |
| `WpConfigFile(path)` | `DB_USER`, `DB_PASSWORD` from `wp-config.php` | `wpconfig` |
| `AwsSecretsManager(secret_id, region=None)` | a JSON secret holding `username` and `password` | `aws` |
| `CredentialChain(*sources)` | the first source with an answer | — |

**Absent versus failed.** A source with nothing to offer (an unset variable, a config
without `DB_USER`) raises `CredentialsAbsentError`. A source that tried and failed
(AWS refused access, the config is unreadable, the secret is malformed) raises
`CredentialsUnobtainableError`. `CredentialChain` moves to the next source only on
*absent*. A *failure* stops the chain, because silently falling through to a
different credential is exactly the substitution principle 3 forbids. The result's
`source` names the source that answered. When every source is absent, the error
names every source tried.

An empty password is a value, not an absence. MySQL permits it.

## 6. The Verdict

```python
class Severity(StrEnum): BLOCKER, WARNING

@dataclass(frozen=True)
class Finding:
    code: Code
    severity: Severity                     # fixed per code
    message: str                           # human-readable, names the cause and the remedy
    fields: Mapping[str, str | int | bool] # structured detail, e.g. {"privilege": "PROCESS"}

@dataclass(frozen=True)
class Verdict:
    operation: str
    findings: tuple[Finding, ...]
    @property
    def blockers(self) -> tuple[Finding, ...]: ...
    @property
    def warnings(self) -> tuple[Finding, ...]: ...
    @property
    def ok(self) -> bool: ...              # no blockers
```

Each `Code` has exactly one severity. Every result type carries the `Verdict` its
check produced, so warnings reach the caller on success. `RefusedError` carries it
on refusal. Warnings are also logged, once, at WARNING level.

Initial catalogue:

| Code | Severity | Raised when |
|---|---|---|
| `UNREACHABLE` | blocker | the server cannot be reached |
| `CREDENTIALS_UNOBTAINABLE` | blocker | a credential source failed |
| `AUTHENTICATION_FAILED` | blocker | the supplied account was rejected (for an admin operation, the admin) |
| `SERVER_UNSUPPORTED` | blocker | below MySQL 8.0 or MariaDB 10.2 |
| `MISSING_PRIVILEGE` | blocker | the account lacks a privilege the operation needs; `fields.privilege` names it |
| `CLIENT_TOOL_MISSING` | blocker | no suitable `mysqldump`/`mariadb-dump`/`mysql`/`mariadb` on `PATH` |
| `CLIENT_TOO_OLD` | blocker | the client tool is below the version the server requires |
| `PLATFORM_UNSUPPORTED` | blocker | a transfer was requested where `/dev/fd` does not exist (Windows) |
| `MISSING_DEPENDENCY` | blocker | an operation needs an extra that is not installed; `fields.extra` names it |
| `OPTION_NOT_ALLOWED` | blocker | a caller-supplied client option is outside the allow-list |
| `DATABASE_ABSENT` | blocker | the operation needs an existing database |
| `DATABASE_NOT_EMPTY` | blocker | `load` into a database holding tables, without `replace=` naming it |
| `USER_ABSENT` | blocker | the operation needs an existing account |
| `CONFIRMATION_MISMATCH` | blocker | `confirm=` or `replace=` does not equal the target |
| `INCOMPATIBLE_DUMP_SOURCE` | blocker | a dump cannot load into this server family as it stands (subject to V1) |
| `LIVE_WORDPRESS_SITE` | warning | a destructive target has a WordPress options table and schema version |
| `CLIENT_SERVER_SKEW` | warning | the client tool's family or major version differs from the server's |
| `END_OF_LIFE_SERVER` | warning | the server version is past upstream end of life (MySQL 8.0, MariaDB 10.2) |

A test requires every code to be documented in the enum and every code to be emitted
by at least one test.

## 7. Operations

All signatures take the `Connection` first. `admin` and `credentials` are
`CredentialSource`s.

### 7.1 Inspection

- **`survey(conn, admin, *, wordpress_user=None, user_host="%", table_prefix="wp_") -> Survey`**
  runs as the administrator. `Survey` holds: `server: ServerInfo` (family, version);
  `database_exists`; `table_count`; `size_bytes`; `is_wordpress` (an
  `{table_prefix}options` table exists); `schema_version: SchemaVersion | None`; and,
  when `wordpress_user` is given, `user_exists` and `user_privileges` on this
  database. This is the existence and emptiness answer backup's restore needs.
- **`inspect(conn, credentials) -> ConnectionState`** is the named account's own login
  probe. It returns one of `READY`, `DATABASE_ABSENT`, `ACCESS_DENIED`,
  `AUTHENTICATION_FAILED`, `UNREACHABLE` or `CREDENTIALS_UNOBTAINABLE`, and never
  raises for an ordinary failure. It describes the account, not whether the
  database exists.
- **`schema_version(conn, credentials, table_prefix="wp_") -> SchemaVersion | None`**
  reads `db_version` from the options table and maps it to a WordPress release
  through the generated version map (`_version_map.py`, regenerated by
  `tools/generate_version_map.py`, never hand-edited). The supported floor is
  WordPress 5.0. `SchemaVersion` exposes `release`, `is_newer_than_known` and
  `is_older_than_supported`.

### 7.2 Provisioning

| Operation | Effect | Guard |
|---|---|---|
| `ensure(conn, admin, wordpress, *, user_host="%", charset="utf8mb4", collation="utf8mb4_unicode_ci")` | creates the database and account if absent, sets the password if the account cannot log in with it, and grants `ALL` on this database only | — |
| `rotate_password(conn, admin, wordpress, *, user_host="%")` | sets the account's password | `USER_ABSENT` |
| `revoke(conn, admin, user, *, user_host="%", confirm)` | revokes the account's privileges on this database only | `confirm` equals `user` |
| `drop_user(conn, admin, user, *, user_host="%", confirm)` | drops the account | `confirm` equals `user` |
| `drop_database(conn, admin, *, confirm)` | drops the database | `confirm` equals `conn.database`; `LIVE_WORDPRESS_SITE` warning |

`ensure` queries the administrator's catalog first and runs only the statements that
change something. `EnsureResult` reports `created_database`, `created_user`,
`password_set` and `granted` as booleans, plus `changed` (any of them) and the
`Verdict`. A second `ensure` against a converged server reports all four false and
executes no write. Statements are portable across MySQL 8.0 to 9.x and MariaDB:
`CREATE USER IF NOT EXISTS`, `ALTER USER` for the password, and `GRANT` without
`IDENTIFIED BY`. The authentication plugin is never named, so each server uses its
own default (`mysql_native_password` is absent from MySQL 9).

Grant targets use `quote_grant_database`, because a database-level GRANT matches
its target as a `LIKE` pattern: `_` and `%` must be escaped there (AD-28). Every other
identifier uses `quote_identifier`. Identifiers are validated before reaching SQL.
Grants are always scoped to `database.*`, never global.

### 7.3 Export and import

- **`dump(conn, credentials, to, *, recipients=None, options=()) -> TransferResult`**:
  `to` is a writable binary stream or a path. A path is written under a temporary
  name in the same directory and renamed into place only on success, so a failed
  dump never leaves a plausible-looking file behind.
- **`iter_dump(conn, credentials, *, recipients=None, options=()) -> DumpStream`**:
  iterate `DumpStream` for byte chunks. If the tool fails, the iteration **raises
  `TransferError` at the end instead of stopping normally**, so a truncated dump
  cannot be mistaken for a whole one. Closing the stream early terminates the
  subprocess. After exhaustion, `.result` holds the `TransferResult`.
- **`load(conn, credentials, source, *, replace=None, identities=None, options=()) -> TransferResult`**:
  `source` is a path, a readable binary stream, or an iterable of byte chunks.
  Loading into a database holding tables requires `replace=conn.database`.

`dump` and `iter_dump` share one engine. `TransferResult` carries `bytes`,
`duration_ms`, `tool` (name and version), `server` and the `Verdict`.

**Engine.**

1. The check resolves the server family and version, selects the client tool
   (`mariadb-dump`/`mariadb` for MariaDB, falling back to `mysqldump`/`mysql`;
   `mysqldump`/`mysql` for MySQL), reads its version, and verifies privileges.
   Dump needs `SELECT`, `SHOW VIEW`, `TRIGGER` and `LOCK TABLES`. Load needs `CREATE`,
   `INSERT`, `ALTER`, `DROP`, `INDEX`, `REFERENCES` and `CREATE VIEW` on the target.
2. **Credentials go through an anonymous pipe.** The `[client]` options (user,
   password, host, port) are written to `os.pipe()`. The read end is passed to the
   child with `pass_fds` and named as `--defaults-file=/dev/fd/N`, as the first
   argument. Nothing is written to disk, and the child's argument vector and
   environment hold no password. A `--defaults-file` replaces the option-file search,
   so a hostile `~/.my.cnf` is ignored (verified on MySQL 8.4 and MariaDB 11.4).
   MySQL clients still read `~/.mylogin.cnf` even then, so the package suppresses it:
   `--no-login-paths` on MySQL 8.4 and later, and `MYSQL_TEST_LOGIN_FILE` set to a
   nonexistent path on MySQL 8.0, which does not know that option. MariaDB has no
   login-path file. Option values are escaped for option-file syntax.
   `--defaults-extra-file` and `MYSQL_PWD` are never used.
3. **Dump defaults:** `--single-transaction --quick --hex-blob
   --default-character-set=utf8mb4 --no-tablespaces`, plus `--set-gtid-purged=OFF` on
   MySQL, and the database name as a positional argument (not `--databases`). The
   output therefore contains no `CREATE DATABASE` or `USE`, so it loads into a
   database of any name, which is what a staging restore needs. Callers may add
   options from an allow-list (for example `--routines`, `--events`,
   `--ignore-table`). Any option touching credentials, option files, hosts or output
   files is refused with `OPTION_NOT_ALLOWED`.
4. **Load** runs the client tool with `--database=<target>` and the dump on stdin.
5. stdout (dump) or stdin (load) is pumped in chunks. stderr is captured up to a size
   cap and redacted. On a non-zero exit, `TransferError` carries the `Verdict`, the
   exit code and the redacted stderr.

**Encryption** is optional (extra `encryption`, `pyrage`). `recipients` takes age or
SSH public keys; the dump stream is encrypted in the standard `age` format on its
way to the caller. `identities` takes age identities. An identity may itself be
passphrase-protected, using age's passphrase mode on the small identity file.
`generate_identity()` returns a new identity and its public key. Because the format
is standard `age`, any output can be decrypted by the stock `age` command line. This
is the family's single encryption format; backup uses the same one for its archives.

## 8. Observability

- The package logs through `structlog` and **never configures logging**. A caller
  that binds a correlation or Run ID with `structlog.contextvars` sees it on every
  record this package emits (AD-10). There is no correlation-ID parameter.
- **One span per public operation** (`check_*`, `survey`, `inspect`, `ensure`, `dump`,
  `load`, the drops), each a child of the caller's current span. There are no spans
  per SQL statement or per chunk. Attributes: `db.name`, `server.address`,
  `server.port`, the server family, and on failure the `Verdict` codes. Error status
  is set on failure. The package depends on `opentelemetry-api` only, so it is inert
  until the host configures an SDK.
- Every operation's completion event carries `operation`, `outcome` and
  `duration_ms`. Transfers also carry `bytes`. These are emitted whether or not
  tracing is configured.
- Secrets never reach logs, spans, error messages, captured stderr or reprs
  (principle 4).

## 9. Command line

The `l3io-wordpress-database` command has one subcommand per operation (`survey`,
`inspect`, `ensure`, `rotate-password`, `revoke`, `drop-user`, `drop-database`,
`dump`, `load`, `schema-version`) and `check <operation>`.

- **No password is accepted as an argument value.** Credentials come from
  `--wp-config PATH`, from environment variable names (`--admin-user-env`,
  `--admin-password-env`, and the same for the WordPress account), from
  `--admin-aws-secret-id`/`--admin-aws-region`, or from an interactive prompt on a
  terminal. An argument vector is visible to every user on the machine.
- Destructive subcommands require `--confirm NAME`; `load` into a non-empty database
  requires `--replace NAME`.
- `--log-level` (default `INFO`) and `--log-format console|json`, consistent with
  backup.
- Distinct exit codes per outcome class: success, usage, refused (a blocker),
  credentials, unreachable, operation failed. They are part of the CLI contract.

## 10. Errors

One base, `DatabaseError`. No driver, `pyrage` or `boto3` type crosses the boundary;
each is wrapped with `raise ... from` (AD-14).

| Error | Meaning |
|---|---|
| `RefusedError(verdict)` | a check found a blocker; nothing ran |
| `CredentialsAbsentError` / `CredentialsUnobtainableError` | section 5 |
| `MissingDependencyError(extra)` | an extra is needed; names it |
| `InvalidArgumentsError`, `InvalidIdentifierError`, `InvalidDatabaseNameError` | rejected input |
| `ConfigUnreadableError`, `MissingConfigValueError` | `wp-config.php` could not supply a value |
| `ProvisioningError` | a provisioning operation started and failed; carries the statements completed |
| `TransferError(verdict, exit_code, stderr)` | a dump or load started and failed; stderr is redacted |
| `DecryptionError` | wrong identity, kept distinct from a corrupt or truncated stream |

## 11. Compatibility

- **Python** 3.11, 3.12, 3.13 and 3.14. The classifiers declare them, `requires-python`
  is `>=3.11`, and every CI matrix runs exactly that set (`tests/test_declared_facts.py`).
- **Servers:** MySQL 8.0 and later, MariaDB 10.2 and later. The MariaDB floor is set
  by `ALTER USER`, which 10.1 rejects with `ERROR 1064`. CI covers MySQL 8.0, 8.4 and
  9.7 and MariaDB 10.2 and 11.4. Exact image tags, because `mysql:lts` moves.
- **Platforms:** everything except export and import is pure Python and runs anywhere.
  Export and import need `/dev/fd` (Linux, macOS) and the client tools on `PATH`.

## 12. Packaging and release

- **Version:** this design ships as **0.1.0**: documented and typed, with no stability
  promise. **1.0.0** is declared after `l3io-wordpress-backup` has integrated against
  it. From 1.0.0, semantic versioning applies with deprecation before removal.
- **Dependencies:** every requirement, runtime and extra, carries an upper bound
  (AD-15), enforced by a test:
  - core: `PyMySQL[rsa]>=1.2,<2`, `structlog>=26.1,<27`, `opentelemetry-api>=1.30,<2`;
  - `aws`: `boto3>=1.34,<2`;
  - `wpconfig`: `l3io-wordpress-config>=X,<0.1`, where X is the first config release
    carrying the define-parser fix (config is pre-1.0, so a minor bump may break);
  - `encryption`: `pyrage>=1.4,<2`.

  The `rsa` extra of PyMySQL is required for `caching_sha2_password` over a non-TLS
  connection, which is exactly the first-provisioning path.
- **Installation is verified per extra:** CI installs the built wheel, bare and with
  each extra, into an isolated environment, and imports what each extra enables. The
  bare install must not pull any optional dependency.
- **Publication order** (AD-15): config reaches PyPI with its parser fix; this package
  re-pins to that release and drops its git source; 0.1.0 is rehearsed on TestPyPI,
  then published to PyPI by deliberate dispatch through a trusted publisher
  registered under `l3io-wordpress-database`. `tools/check_name_claim.py` and
  `tools/check_dist_metadata.py` gate every upload.
- **Legacy name:** a single `wpdatabase2` 0.0.16 tombstone, with no dependencies,
  whose README and import error point to `l3io-wordpress-database`. `wpdatabase` is
  not registered.

## 13. Verification

**Unit tests:**
- `Verdict` construction and the code catalogue;
- the argument vector for every client invocation;
- option-file escaping against awkward passwords (`#`, `;`, quotes, backslashes,
  spaces, leading and trailing spaces, and `ab);cd`);
- credential chain absent/failed semantics;
- confirmation guards;
- atomic path writes;
- `age` round trip, truncation, and wrong identity versus corruption.

**Integration tests, against every engine in the matrix:**
- `ensure` convergence, with a second run reporting no change and executing no write;
- `survey` facts;
- each destructive operation and its guard;
- dump followed by load **into a differently named database**, compared by table
  checksums;
- a dump killed mid-stream raises;
- `inspect`'s six states;
- `schema_version` with a custom prefix.

**Transfer tests use the client tools from the server's own image**, run as the job
container, so the client and server versions match what an operator has.

**Secret checks:**
- during a dump and a load, the child's `/proc/<pid>/cmdline` and `/proc/<pid>/environ`
  contain no password;
- no file appears in the temporary directory;
- a planted `~/.my.cnf` and `~/.mylogin.cnf` change nothing;
- log records, spans, error messages and captured stderr are clean;
- the CLI defines no password-valued option.

**Observability:**
- a bound contextvar appears on every record of an operation;
- spans nest under a caller's span;
- completion events carry `duration_ms` and `bytes`.

**Repository guards that stay:**
- namespace contracts (AD-27), built-wheel inspection into an empty directory;
- `check_dist_metadata`, `check_name_claim`, `test_declared_facts`, `test_act_workspace`;
- dependency audit (`security-audit.yml`, `make audit`).

A coverage floor is enforced in CI.

## 14. Documentation and retirement of the predecessor

This package is the only version. Its documentation describes only it.

- **Preserve first.** Before any deletion, branch `legacy/main` from `main` as it
  stands, so every predecessor file and document stays retrievable as it was. The
  existing remote branch `dev-1.0.1` moves to `legacy/dev-1.0.1`. `main`'s history is
  not rewritten. The cleanup below lands on `main` as ordinary commits, so every
  tag, release and pinned commit stays valid. From then on, `main` carries only the
  current package. Predecessor material is never re-added to `main`; it is read from
  `legacy/main`.
- **Delete:** `docs/migration.md`; `docs/rewrite-notes.md`; the folder
  `_bmad-output/planning-artifacts/prds/prd-py-wordpress-database-2026-09-15/` (PRD,
  addendum, reviews and decision log).
- **Rewrite as current-only:** `README.md`; `docs/handoff/wordpress-database.md`;
  `AGENTS.md`, through `bmad-project-context`; and docstrings, comments, tests and
  workflow comments that narrate the predecessor or the rewrite. A rule that history
  justified keeps its check, and its reason is restated as a present-tense risk.
- **`LICENSE`:** `Copyright (c) 2026 Shawn Anderson`.
- **Architecture record:** `docs/adr/` holds this package's own decisions. `AGENTS.md`
  and the README point to backup's spine for family rules, which are never copied
  here. The initial ADRs:
  1. operations are owned here, including export and import;
  2. credentials reach client tools through an anonymous-pipe option file;
  3. `age` via `pyrage` is the encryption format;
  4. the check-first `Verdict` model;
  5. destructive calls name their target twice.

**Remote housekeeping**, each confirmed again immediately before it runs:
- push `legacy/main`; rename `dev-1.0.1` to `legacy/dev-1.0.1` on GitHub;
- delete tag `v1.0`, locally and on GitHub;
- delete the GitHub release `v0.0.1` (the tag stays);
- delete the Gitea package `l3io-wp-database` 0.0.1 (org `liquidlogiclabs`);
- publish the `wpdatabase2` tombstone (section 12).

## 15. Requests to the family

These documents belong to other repositories; each item is a request, not an edit.

**`l3io-wordpress-backup`:**
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
  version premise; ADR-0013's description of `make ci`.

**`l3io-wordpress-config`:** release the define-parser fix; this package re-pins to
it before 0.1.0.

## 16. To verify during planning

Each item is settled by a test or a probe before its dependent code is written.

- **V1** Whether MariaDB's dump tool writes a first line MySQL's client rejects, and on
  which versions. If so, `INCOMPATIBLE_DUMP_SOURCE` plus an option to strip that line.
- **V2** `MYSQL_TEST_LOGIN_FILE` suppression on MySQL 8.0, with a login file planted by
  `mysql_config_editor`.
- **V3** A job container built from each server image, with Python installed by `uv`,
  runs on GitHub Actions and under act.
- **V4** `pyrage` distinguishes a wrong identity from a corrupt stream well enough for
  `DecryptionError` to be distinct.
- **V5** Option-file value escaping rules for both client families.
- **V6** Privilege detection without parsing `SHOW GRANTS` text (for example through
  `information_schema`), including MySQL 8 roles.
- **V7** Every dump default is accepted by every client in the matrix
  (`--set-gtid-purged` is MySQL-only; `--no-tablespaces` on MariaDB).
- **V8** Reading a child's `/proc/<pid>/environ` and `cmdline` from the test process
  on CI runners.

## 17. Success criteria

- Backup Stories 2.1, 2.4, 3.2, 3.4, 3.5 and 5.1 can each be implemented by calling
  this package, with no SQL and no password handling in backup.
- Every operation has a check whose verdict is identical to the refusal its operation
  would raise.
- Every section 13 verification is mechanical and runs in CI. None relies on review.
- `pip install l3io-wordpress-database` and each extra resolve from PyPI in a clean
  environment on every supported Python version.
