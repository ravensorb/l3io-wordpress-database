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
| `server` | `ServerInfo`, `ServerFamily` |
| `inspection` | `survey`, `Survey`, `inspect`, `ConnectionState`, `schema_version`, `SchemaVersion` |
| `provision` | `ensure`, `EnsureResult`, `rotate_password`, `revoke`, `drop_user`, `drop_database`, `OperationResult`, and `check_` for each |
| `transfer` | `dump`, `iter_dump`, `DumpStream`, `load`, `TransferResult`, `check_dump`, `check_load` |
| `encryption` | used through `dump(recipients=)` and `load(identities=)`; `generate_identity` |
| `identifiers` | `quote_identifier`, `quote_grant_database`, `validate_database_name`, `validate_user_name` |
| `errors` | `DatabaseError` and its subclasses (section 10) |
| (root) | `Database`, a facade binding one `Connection`; `ClientTool` (a transfer's client tool, defined in the internal `_client` module); `__version__` |

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
| `WpConfigFile(path)` | `DB_USER`, `DB_PASSWORD` from `wp-config.php`; also provides `connection()` (from `DB_HOST`, `DB_NAME`) and `table_prefix` | `wpconfig` |
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

Catalogue:

| Code | Severity | Raised when |
|---|---|---|
| `UNREACHABLE` | blocker | the server cannot be reached |
| `CREDENTIALS_UNOBTAINABLE` | blocker | a credential source failed |
| `AUTHENTICATION_FAILED` | blocker | the supplied account was rejected (for an admin operation, the admin) |
| `SERVER_UNSUPPORTED` | blocker | below MySQL 8.0 or MariaDB 10.2 |
| `MISSING_PRIVILEGE` | blocker | the account lacks a privilege the operation needs; `fields.privilege` names it |
| `CLIENT_TOOL_MISSING` | blocker | no suitable `mysqldump`/`mariadb-dump`/`mysql`/`mariadb` on `PATH`; `fields.tools` names those tried |
| `PLATFORM_UNSUPPORTED` | blocker | a transfer was requested where `/dev/fd` does not exist (Windows) |
| `MISSING_DEPENDENCY` | blocker | an operation needs an extra that is not installed; `fields.extra` names it |
| `OPTION_NOT_ALLOWED` | blocker | a caller-supplied client option is outside the allow-list |
| `DATABASE_ABSENT` | blocker | the operation needs an existing database |
| `DATABASE_NOT_EMPTY` | blocker | `load` into a database holding tables, without `replace=` naming it |
| `USER_ABSENT` | blocker | the operation needs an existing account |
| `CONFIRMATION_MISMATCH` | blocker | `confirm=` or `replace=` does not equal the target |
| `INCOMPATIBLE_DUMP_SOURCE` | blocker | the load source begins with MariaDB's sandbox line and the client tool cannot read it; `allow_unsandboxed=True` strips that one line |
| `IDENTITY_REQUIRED` | blocker | the load source is `age`-encrypted and no `identities` were given |
| `LIVE_WORDPRESS_SITE` | warning | a destructive target has a WordPress options table and schema version |
| `CLIENT_SERVER_SKEW` | warning | the client tool belongs to the other server family, or its major.minor version is older than the server's |
| `STORED_OBJECTS_PRESENT` | warning | the database being dumped has views or triggers: they carry `DEFINER` clauses that loading needs privilege for, and MariaDB keeps their original text, which may name this schema |
| `CROSS_FAMILY_DUMP` | warning | the load source comes from the other server family, whose collations may not exist on the target |
| `END_OF_LIFE_SERVER` | warning | the server version is past upstream end of life (MySQL 8.0, MariaDB 10.2) |
| `PRIVILEGES_UNVERIFIED` | warning | the administrator holds an active role, whose privileges `information_schema` does not show, so privilege checks were skipped and the operation is attempted |
| `PASSWORD_UNVERIFIED` | warning | `ensure` ran for an account whose `user_host` does not match this machine, so it did not judge or set an existing password by logging in, and did not verify the result |

A test requires every code to be documented in the enum and every code to be
emitted by at least one test.

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
| `ensure(conn, admin, wordpress, *, user_host="%", charset="utf8mb4", collation="utf8mb4_unicode_ci")` | creates the database and account if absent, sets the password if the account cannot log in with it, and grants `ALL` on this database only | admin needs `CREATE`, `CREATE USER`, `GRANT OPTION`, the WordPress privileges (`SELECT`, `INSERT`, `UPDATE`, `DELETE`, `CREATE`, `DROP`, `ALTER`, `INDEX`) and **global** `SELECT` |
| `rotate_password(conn, admin, wordpress, *, user_host="%")` | sets the account's password | `USER_ABSENT`; admin needs `CREATE USER` and global `SELECT` |
| `revoke(conn, admin, user, *, user_host="%", confirm)` | revokes the account's privileges on this database only — both the escaped grant `ensure` writes and a grant on the unescaped name, which the 0.0.x package wrote and which also matched neighbouring names; an account holding neither is `changed=False` | `confirm` equals `user`; `USER_ABSENT`; admin needs `GRANT OPTION` and global `SELECT` |
| `drop_user(conn, admin, user, *, user_host="%", confirm)` | drops the account; an absent account is `changed=False` | `confirm` equals `user`; admin needs `CREATE USER` |
| `drop_database(conn, admin, *, confirm)` | drops the database; an absent database is `changed=False` | `confirm` equals `conn.database`; `LIVE_WORDPRESS_SITE` warning; admin needs `DROP` |

`ensure` queries the administrator's catalog first and runs only the statements that
change something. `EnsureResult` reports `created_database`, `created_user`,
`password_set` and `granted` as booleans, plus `changed` (any of them) and the
`Verdict`. A second `ensure` against a converged server reports all four false and
executes no write. Statements are portable across MySQL 8.0 to 9.x and MariaDB:
`CREATE USER IF NOT EXISTS`, `ALTER USER` for the password, and `GRANT` without
`IDENTIFIED BY`. The authentication plugin is never named, so each server uses its
own default (`mysql_native_password` is absent from MySQL 9). `charset` and `collation`
cannot be parameterised, so they are restricted to `^[A-Za-z0-9_]+$`. The privilege check
enumerates what WordPress needs; `GRANT ALL` may expand to further privileges on a given
server, so an administrator restricted below them passes the check and `ensure` then
raises `ProvisioningError` naming the steps completed. A rerun after fixing the
administrator converges, because `ensure` is idempotent.

`ensure` judges an existing account's password by logging in as it, and verifies the
result the same way. Both are meaningful only when the server would match this machine
to `user_host`, which `ensure` asks the server. When it would not, `ensure` leaves an
existing password unchanged, skips the verification, and reports `PASSWORD_UNVERIFIED`;
`rotate_password` is the explicit way to set that account's password.

Grant targets use `quote_grant_database`, because a database-level GRANT matches
its target as a `LIKE` pattern: `_` and `%` must be escaped there (AD-28). Every other
identifier uses `quote_identifier`. Identifiers are validated before reaching SQL.
Grants are always scoped to `database.*`, never global.

### 7.3 Export and import

- **`dump(conn, credentials, to, *, recipients=None, options=()) -> TransferResult`**:
  `to` is a writable binary stream or a path. A path is written under a temporary
  name in the same directory (mode `0600`) and renamed into place only on success,
  so a failed dump never leaves a plausible-looking file behind. The temporary file
  is opened before the client tool starts, so an unusable target is refused with
  `InvalidArgumentsError` and starts nothing. A stream target is flushed before
  `dump` returns, so a final chunk the stream fails to write fails the dump.
- **`iter_dump(conn, credentials, *, recipients=None, options=()) -> DumpStream`**:
  iterate `DumpStream` for byte chunks. If the tool fails, the iteration **raises
  `TransferError` at the end instead of stopping normally**, so a truncated dump
  cannot be mistaken for a whole one. Closing the stream early kills and reaps the
  subprocess. After exhaustion, `.result` holds the `TransferResult`.
- **`load(conn, credentials, source, *, replace=None, identities=None, options=(), allow_unsandboxed=False) -> TransferResult`**:
  `source` is a path, a readable binary stream, or an iterable of byte chunks.
  Loading into a database holding tables requires `replace=conn.database`.
  `replace=` is a confirmation gate only: the package does not drop or empty the
  target. The dump's own `DROP TABLE IF EXISTS` statements replace the tables it
  contains; tables in the target that the dump does not contain remain.
- **`check_dump(conn, credentials, *, options=())`** and
  **`check_load(conn, credentials, *, source=None, replace=None, identities=None, options=(), allow_unsandboxed=False)`**
  return the `Verdict` the operation would act on. `check_load` takes `source` only
  as a path, or `None` to skip the header check; a stream or iterable is refused
  with `InvalidArgumentsError`, because it cannot be read twice. `load` always
  evaluates the header. A path source that `check_load` cannot open or decrypt
  raises as `load` would (`InvalidArgumentsError`, `DecryptionError` or
  `CorruptDumpError`) rather than returning a verdict.

`dump` and `iter_dump` share one engine. `TransferResult` carries `bytes`,
`duration_ms`, `tool` (name and version), `server` and the `Verdict`. `bytes` counts
what the transfer moved: for a load, the plaintext bytes delivered to the client
tool; for a dump, the bytes produced, counted after encryption when there is any.

**Engine.**

1. The check resolves the server family and version, selects the client tool
   (`mariadb-dump`/`mariadb` for MariaDB, falling back to `mysqldump`/`mysql`;
   `mysqldump`/`mysql` for MySQL, falling back to the MariaDB tools, which
   `CLIENT_SERVER_SKEW` then reports), reads its version, and verifies privileges.
   Dump needs `SELECT`, `SHOW VIEW` and `TRIGGER`; it needs no `LOCK TABLES`,
   because `--single-transaction` takes no locks. Load needs `CREATE`, `INSERT`,
   `ALTER`, `DROP`, `INDEX`, `REFERENCES` and `CREATE VIEW` on the target.
2. **Credentials go through an anonymous pipe.** The `[client]` options (user,
   password, host, port, and `protocol=TCP`) are written to `os.pipe()`. The read
   end is passed to the child with `pass_fds` and named as
   `--defaults-file=/dev/fd/N`, as the first argument. Nothing is written to disk,
   and the child's argument vector and environment hold no password. `protocol=TCP`
   makes `localhost` mean the same server to the client tool as to PyMySQL, instead
   of a Unix socket. A `--defaults-file` replaces the option-file search, so a
   hostile `~/.my.cnf` is ignored. MySQL clients still read `~/.mylogin.cnf` even
   then, so the package suppresses it: `MYSQL_TEST_LOGIN_FILE` names a nonexistent
   path for every client, which MySQL 8.0 honours, and MySQL 8.4 and later also get
   `--no-login-paths`. MariaDB has no login-path file. `--defaults-extra-file` and
   `MYSQL_PWD` are never used.
3. **Option values** are wrapped in `"…"` with `\`, `"` and newline
   backslash-escaped; a NUL is refused. MariaDB's option reader splits a line longer
   than its buffer into two, which would let a long value inject an option, so a
   connection value (user, password or host) whose escaped form exceeds 1024 UTF-8
   bytes, or that is not valid UTF-8, is refused with `InvalidArgumentsError` before
   the client tool is started for the transfer. The check does not report it: the
   refusal comes from the operation, after its check has connected and read the
   tool's version. No message names the value.
4. **The child's environment** is `PATH`, `LANG`, `LC_ALL` and
   `MYSQL_TEST_LOGIN_FILE`, and nothing else. No inherited `HOME`, `MYSQL_PWD`,
   `MYSQL_HOST` or `MYSQL_TCP_PORT` can authenticate or redirect it.
5. **Dump defaults:** `--single-transaction --quick --hex-blob
   --default-character-set=utf8mb4 --no-tablespaces`, plus `--set-gtid-purged=OFF` when
   the tool is MySQL's `mysqldump`, and the database name as a positional argument (not `--databases`). The
   output therefore contains no `CREATE DATABASE` or `USE`, so it loads into a
   database of any name, which is what a staging restore needs. Callers may add
   options from an allow-list (for example `--routines`, `--events`,
   `--ignore-table`). Any option touching credentials, option files, hosts or output
   files is refused with `OPTION_NOT_ALLOWED`. The dump check reports
   `STORED_OBJECTS_PRESENT` when the database has views or triggers.
6. **Load** runs the client tool with `--default-character-set=utf8mb4
   --database=<target>` and the dump on stdin. It first reads the source's first
   64 KiB, decrypting them when the source is `age`-encrypted and identities are
   given, and compares the first lines against fixed strings only; no SQL is
   parsed. The `age` header without identities is `IDENTITY_REQUIRED`. A dump
   from the other family is `CROSS_FAMILY_DUMP`. The family is the source
   server's: a `-- Server version` line among the first lines decides it
   (MariaDB versions contain `MariaDB`), because MySQL's tool can dump a MariaDB
   server; without that line, the `-- MariaDB dump` or `-- MySQL dump` banner
   decides it. MariaDB's sandbox line as the first line is
   `INCOMPATIBLE_DUMP_SOURCE` when the client tool cannot read it (MySQL clients
   read it as a comment; MariaDB clients read it from the release in each series
   that added it); `allow_unsandboxed=True` strips that one line and nothing else.
7. **Damage is found mid-stream.** A corrupt or truncated source is discovered
   after the statements before the damage have run, so a caller loads into a
   staging database and switches to it only after the load succeeds, as backup
   does.
8. **Order of failures.** Recipients are validated, and a missing `encryption`
   extra raises `MissingDependencyError`, before the dump tool is started. A path source or target that
   cannot be opened, or a source whose head cannot be read, is refused with
   `InvalidArgumentsError` before any program starts. A read or write failure of
   the caller's own source or target once the transfer runs raises `TransferError`.
9. stdout (dump) or stdin (load) is pumped in chunks. stderr is drained on its own
   thread, so a tool writing more stderr than a pipe holds cannot deadlock, and is
   kept up to 64 KiB with the password redacted. On a non-zero exit, `TransferError`
   carries the `Verdict`, the exit code and the redacted stderr. When feeding a load
   fails for any reason, the client tool is killed rather than its input closed,
   so a partial statement never runs.

**Encryption** is optional (extra `encryption`, `pyrage`). `recipients` takes age or
SSH public keys; the dump stream is encrypted in the standard `age` format on its
way to the caller. `identities` takes age identities. An identity may itself be
passphrase-protected, using age's passphrase mode on the small identity file.
`generate_identity()` returns a new identity and its public key. Because the format
is standard `age`, any output can be decrypted by the stock `age` command line. This
is the family's single encryption format; backup uses the same one for its archives.
An identity that matches no recipient raises `DecryptionError` before anything is
loaded. A truncated or damaged `age` stream raises `CorruptDumpError`.

## 8. Observability

- The package logs through `structlog` and **never configures logging**. A caller
  that binds a correlation or Run ID with `structlog.contextvars` sees it on every
  record this package emits (AD-10). There is no correlation-ID parameter.
- **One span per public operation** (`check_*`, `survey`, `inspect`, `ensure`, `dump`,
  `load`, the drops), each a child of the caller's current span. There are no spans
  per SQL statement or per chunk. Attributes: `db.name`, `server.address`,
  `server.port`, the server family (`db.system`), and on failure the `Verdict` codes. Error status
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
  `--wp-config PATH`, from a user name with the name of the environment variable
  holding its password (`--admin-user` with `--admin-password-env`, and `--db-user`
  with `--db-password-env` for the WordPress account), from
  `--admin-aws-secret-id`/`--admin-aws-region`, or, when no password variable is
  given, from an interactive prompt on a terminal. An argument vector is visible to every user on the machine.
- Destructive subcommands require `--confirm NAME`; `load` into a non-empty database
  requires `--replace NAME`.
- Extra client options are passed as `--option=--name[=value]`, joined with `=` so
  the parser does not read the client option as its own; the allow-list of
  section 7.3 applies.
- `--log-level` (default `INFO`) and `--log-format console|json`, consistent with
  backup.
- Results are printed as JSON on stdout; errors go to stderr. The exception is
  `dump --output -`: the dump itself is on stdout, so its result goes to stderr.
- Distinct exit codes per outcome class, part of the CLI contract: `0` success, `1`
  operation failed, `2` usage, `3` refused (a blocker), `4` credentials, `5`
  unreachable, `7` not ready (`inspect` found the account cannot use the database).

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
| `DatabaseUnreachableError`, `AuthenticationFailedError`, `AccessDeniedError` | raised by the read operations `survey` and `schema_version`, which have no check form, and by a server error mid-operation |
| `TransferError(verdict, exit_code, stderr)` | a dump or load started and failed; stderr is redacted |
| `DecryptionError` | none of the supplied identities can decrypt the source (a wrong identity), or an identity file's passphrase is wrong |
| `CorruptDumpError` | an encrypted source is truncated or damaged; kept distinct from `DecryptionError`, because the remedy differs |

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

**Transfer tests use the client tools from the server's own image**, so the client
and server versions match what an operator has. `make test-transfer ENGINE=<image>`
starts the server from the image and runs the transfer tests in a second container
of the same image, with Python installed by `uv`. CI job `transfer` runs that
command once per engine, and a developer runs the same command locally.

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

- **V1 — settled 2026-10-13.** MariaDB 11.4 dumps begin
  `/*M!999999\- enable the sandbox mode */`. MySQL clients accept it as a comment;
  MariaDB 10.2's client rejects it (`Unknown command '\-'`), hence
  `INCOMPATIBLE_DUMP_SOURCE` and `allow_unsandboxed`. Cross-family loads fail on
  collations: MariaDB 11.4 to MySQL 8.4 with `Unknown collation
  utf8mb4_uca1400_ai_ci`, MySQL 8.4 to MariaDB 10.2 with `Unknown collation
  utf8mb4_0900_ai_ci`; MySQL 8.4 to MariaDB 11.4 works. Hence `CROSS_FAMILY_DUMP`.
- **V2 — settled 2026-10-13.** `~/.mylogin.cnf` overrides `--defaults-file`: a planted
  login path changed the login to its own user. `MYSQL_TEST_LOGIN_FILE` set to a
  nonexistent path suppresses it on MySQL 8.0; `--no-login-paths` does on 8.4 and 9.7.
- **V3 — settled 2026-10-13.** The suite runs inside each server image (MySQL 8.0,
  8.4 and 9.7, MariaDB 10.2 and 11.4) after installing `git` and `uv` 0.11.6 with
  `UV_PYTHON=3.11`, with the image's own client tools on `PATH`. `make test-transfer`
  is the one command CI, act and a developer run.
- **V4 — settled 2026-10-13.** `pyrage` 1.4 reports a wrong identity as
  `DecryptError('No matching keys found')`, a truncated or corrupted body as a bare
  `OSError('decryption error')`, and a corrupted header or a non-`age` input as
  `DecryptError` with other text. That separates `DecryptionError` from
  `CorruptDumpError`. Encryption streams: 512 MiB encrypts with an 11 MiB peak RSS.
- **V5 — settled 2026-10-13.** Option-file values wrapped in `"…"`, with `\` and `"`
  backslash-escaped, reach the server intact on all five engines for `#`, `;`, `'`,
  `"`, `\`, leading and trailing spaces, `ab);cd`, `=` and `[`.
- **V6 — settled 2026-10-12.** `information_schema.USER_PRIVILEGES` and
  `SCHEMA_PRIVILEGES` answer privilege questions on MySQL 8.0/8.4/9.7 and MariaDB
  10.2/11.4. `SCHEMA_PRIVILEGES.TABLE_SCHEMA` stores the escaped grant pattern (`wp\_x`),
  so `%s LIKE TABLE_SCHEMA` reproduces the server's match. Privileges held through an
  active role are not listed, hence `PRIVILEGES_UNVERIFIED`. `CURRENT_ROLE()` is `NONE`
  (MySQL) or `NULL` (MariaDB) when no role is active.
- **V7 — settled 2026-10-13.** `--single-transaction --quick --hex-blob
  --default-character-set=utf8mb4 --no-tablespaces`, plus `--set-gtid-purged=OFF` with
  MySQL tools, is accepted by every client in the matrix. The dumps contain no
  `CREATE DATABASE` or `USE` and load into a differently named database with equal
  table checksums; MySQL strips same-schema qualifiers from views. MariaDB stores a
  trigger's original statement text, so a trigger created with a schema-qualified
  name is dumped qualified, hence `STORED_OBJECTS_PRESENT`.
- **V8 — settled 2026-10-13.** A test process can read a child's `/proc/<pid>/cmdline`
  and `/proc/<pid>/environ`, and a pipe passed with `pass_fds` is readable by the
  child as `/dev/fd/N`.

## 17. Success criteria

- Backup Stories 2.1, 2.4, 3.2, 3.4, 3.5 and 5.1 can each be implemented by calling
  this package, with no SQL and no password handling in backup.
- Every operation has a check whose verdict is identical to the refusal its operation
  would raise.
- Every section 13 verification is mechanical and runs in CI. None relies on review.
- `pip install l3io-wordpress-database` and each extra resolve from PyPI in a clean
  environment on every supported Python version.
