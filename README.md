# l3io-wordpress-database

The operations a WordPress site performs against its MySQL or MariaDB database:
inspecting it, provisioning it, changing its accounts, destroying it, and exporting
and importing it. Every operation acts with credentials the caller supplies, and
every operation that changes or moves something can be checked before it runs.

It imports as `l3io.wp.database`, in the `l3io.wp` namespace shared with
`l3io-wordpress-config` and `l3io-wordpress-backup`.

> **Status:** 0.x — documented and typed, with no stability promise until 1.0.0.
> Not yet on PyPI; releases are on
> [GitHub](https://github.com/ravensorb/l3io-wordpress-database/releases).

## Installing

```shell
pip install l3io-wordpress-database                # core: PyMySQL, structlog, opentelemetry-api
pip install 'l3io-wordpress-database[aws]'         # credentials from AWS Secrets Manager
pip install 'l3io-wordpress-database[wpconfig]'    # credentials and location from wp-config.php
pip install 'l3io-wordpress-database[encryption]'  # age-encrypted dumps
```

An optional dependency is an optional import: a base install never imports
`boto3`, the config reader or `pyrage`, and asking for a feature whose extra is
absent raises `MissingDependencyError` naming the extra.

## Two accounts

WordPress's own account — the one in `wp-config.php` — is the account that is
created and granted. A separate administrative account does the creating, and is
never defaulted to the WordPress account. Whether a database exists is answered
by the administrator: a server authenticates before it resolves the database, so a
failed login by the WordPress account says nothing about the database.

## Check, then run

```python
from l3io.wp.database import Connection, Database, Environment, Explicit

db = Database(Connection("127.0.0.1", "wp_site"))
admin = Environment("DB_ADMIN_USER", "DB_ADMIN_PASSWORD")
wordpress = Explicit("wpuser", "wp-pass")

verdict = db.check_ensure(admin, wordpress)
for finding in verdict.findings:
    print(finding.severity, finding.code, finding.message)

if verdict.ok:
    result = db.ensure(admin, wordpress)
    print(result.created_database, result.created_user, result.granted, result.changed)
```

`ensure` runs the same check itself and raises `RefusedError`, carrying the
`Verdict`, on any blocker. It creates only what is missing, and a second run
against a converged server changes nothing. Grants are scoped to the one database,
with the `_` and `%` wildcards in its name escaped.

Destructive operations — `revoke`, `drop_user`, `drop_database` — take
`confirm=`, which must repeat the target's name.

## From wp-config.php

```python
from l3io.wp.database import Database, Environment, WpConfigFile

site = WpConfigFile("/var/www/html/wp-config.php")
db = Database(site.connection())
survey = db.survey(
    Environment("DB_ADMIN_USER", "DB_ADMIN_PASSWORD"),
    wordpress_user=site.resolve().username,
    table_prefix=site.table_prefix,
)
print(survey.database_exists, survey.table_count, survey.is_wordpress, survey.schema_version)
```

`inspect` asks the WordPress account itself what it can do, and never raises
for an ordinary failure:

| State | Meaning |
|---|---|
| `ready` | connected, authenticated, and the database is usable |
| `database_absent` | authenticated, but the database does not exist |
| `access_denied` | authenticated, but may not use this database |
| `authentication_failed` | the server rejected the account |
| `unreachable` | the server could not be reached |
| `credentials_unobtainable` | the credentials could not be obtained; nothing was attempted |

## Export and import

```python
from l3io.wp.database import (
    Connection,
    Database,
    Environment,
    WpConfigFile,
    encrypt,
    generate_identity,
)

site = WpConfigFile("/var/www/html/wp-config.php")
identity, recipient = generate_identity()
Database(site.connection()).dump(site, "/backups/wp_site.sql.age", recipients=[recipient])
# Or passphrase mode (mutually exclusive with recipients= / identities=):
# Database(site.connection()).dump(site, "/backups/wp_site.sql.age", passphrase=secret)

admin = Environment("DB_ADMIN_USER", "DB_ADMIN_PASSWORD")
staging = Database(Connection("127.0.0.1", "wp_site_staging"))
staging.ensure(admin, site)
staging.load(site, "/backups/wp_site.sql.age", identities=[identity])
```

Dumps are made by the server's own client tools (`mysqldump` or `mariadb-dump`),
and loads by `mysql` or `mariadb`. The password reaches them only through an
anonymous pipe: never an argument, an environment variable or a file. A dump to
a path is written under a temporary name and renamed only on success. `iter_dump`
yields the dump as chunks, and raises at the end if the tool failed, so a
truncated dump is never mistaken for a whole one.

Loading into a database that holds tables requires `replace=` naming it. A damaged
source is discovered mid-load, after the statements before the damage have run,
so load into a staging database and switch to it once the load succeeds.

Encryption is standard [age](https://age-encryption.org): recipient keys or a
passphrase (scrypt sole recipient). Either streams; any dump can be decrypted
with the stock `age` command line. Passphrase mode uses the
`l3io-age-passphrase` binder by default, or `age` + `age-plugin-batchpass` when
`L3IO_AGE_PASSPHRASE_BACKEND=cli` (or when the binder is absent under `auto`).
Archive callers can also
`from l3io.wp.database import encrypt, decrypt, check_passphrase`.

## Command line

```shell
l3io-wordpress-database survey --wp-config /var/www/html/wp-config.php \
    --admin-user root --admin-password-env DB_ADMIN_PASSWORD
l3io-wordpress-database check ensure --wp-config /var/www/html/wp-config.php \
    --admin-user root --admin-password-env DB_ADMIN_PASSWORD
l3io-wordpress-database ensure --wp-config /var/www/html/wp-config.php \
    --admin-user root --admin-password-env DB_ADMIN_PASSWORD
l3io-wordpress-database dump --wp-config /var/www/html/wp-config.php \
    --output wp_site.sql.age --recipient age1examplerecipient
l3io-wordpress-database dump --wp-config /var/www/html/wp-config.php \
    --output wp_site.sql.age --passphrase-file /run/secrets/age-passphrase
l3io-wordpress-database load --db-host 127.0.0.1 --db-name wp_site_staging \
    --db-user wpuser --db-password-env DB_PASSWORD \
    --input wp_site.sql.age --identity key.txt
l3io-wordpress-database load --db-host 127.0.0.1 --db-name wp_site_staging \
    --db-user wpuser --db-password-env DB_PASSWORD \
    --input wp_site.sql.age --ask-passphrase
l3io-wordpress-database drop-database --db-host 127.0.0.1 --db-name wp_site_staging \
    --admin-user root --admin-password-env DB_ADMIN_PASSWORD --confirm wp_site_staging
```

No password or age passphrase is accepted as an argument value, because an
argument vector is visible to every user on the machine: a password comes from
`--wp-config`, from the environment variable named by a `--*-password-env`
option, from AWS Secrets Manager, or from a prompt; an age passphrase comes from
`--passphrase-file` or `--ask-passphrase` (mutually exclusive with
`--recipient` / `--identity`). Results are printed as JSON on stdout; with
`dump --output -` the dump is on stdout and the result on stderr.

| Exit code | Meaning |
|---|---|
| `0` | success |
| `1` | the operation started and failed |
| `2` | usage |
| `3` | refused: the check found a blocker, and nothing ran |
| `4` | credentials could not be obtained |
| `5` | the server could not be reached |
| `7` | not ready: `inspect` found the account cannot use the database |

## Supported

- Python 3.11, 3.12, 3.13 and 3.14.
- MySQL 8.0 and later, MariaDB 10.2 and later. CI runs MySQL 8.0, 8.4 and 9.7 and
  MariaDB 10.2 and 11.4.
- Export and import need `/dev/fd` (Linux or macOS) and the client tools on `PATH`.
  Everything else is pure Python.

The package logs through `structlog` and never configures logging, and opens one
OpenTelemetry span per operation through `opentelemetry-api`, inert until the host
configures an SDK.

## Design records

This package's decisions are in [docs/adr](docs/adr/README.md). The rules the
`l3io.wp` family shares (cited as AD-n) are in `l3io-wordpress-backup`'s
architecture spine.

## Development

```shell
make sync                                # locked environment, all extras
make check                               # lint, format, types, tests, contracts
make test-db DB_HOST=127.0.0.1           # integration tests against a server
make test-transfer ENGINE=mysql:8.4      # export/import with that image's own client tools
make verify-wheel                        # install the built wheel, bare and with each extra
make ci                                  # replay the CI pipeline under act
```

## Licence

MIT.
