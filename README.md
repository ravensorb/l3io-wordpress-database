# l3io-wordpress-database

Create and inspect WordPress MySQL databases and their users, idempotently.

WordPress's own tooling does not do this. `wp db create` issues `CREATE DATABASE`
and nothing more — the database user must already exist with rights — and the
official WordPress Docker image states that the database "needs to already
exist... it will not be created by the `wordpress` container". This library
fills that gap: database, user, and scoped grants in one idempotent call.

The design idea worth knowing before you use it: **two credential sets**.
WordPress's own credentials live in its config and are the ones *created and
granted*. Separate administrative credentials are used *only* to do the
creating, and are never defaulted to the WordPress account.

> **Status:** not yet published to any public index. `l3io-wordpress-config`, needed
> only for the optional `wpconfig` extra, currently resolves from git. See
> [Installing](#installing).

## Installing

```shell
pip install l3io-wordpress-database              # core: PyMySQL, structlog, opentelemetry-api
pip install 'l3io-wordpress-database[aws]'       # + AWS Secrets Manager credentials
pip install 'l3io-wordpress-database[wpconfig]'  # + reading wp-config.php
```

Optional dependencies are optional *imports*: the core never imports `boto3` or
the config reader, so a base install pays for neither. Asking for a feature
whose extra is absent raises an error naming the extra to install.

## Library use

```python
from l3io.wp.database import WpConnection, WpCredentials, WpDatabase

db = WpDatabase(
    WpConnection.from_db_host(
        db_host="127.0.0.1:3306",  # host, or host:port
        db_name="wp_site",
        credentials=WpCredentials.from_username_and_password("wpuser", "wp-pass"),
    )
)

result = db.ensure(WpCredentials.from_username_and_password("root", "root-pass"))
print(result.state, result.changed, result.actions)
```

From a `wp-config.php` (needs the `wpconfig` extra):

```python
from l3io.wp.database import WpConfigSource

source = WpConfigSource("/var/www/wp-config.php")
db = WpDatabase(source.connection())
print(source.table_prefix)
```

### Asking what state things are in

`inspect()` answers *why*, not just whether:

```python
from l3io.wp.database import ConnectionState

state = db.inspect()
if state.needs_provisioning:
    ...
elif state.blocks_provisioning:
    ...  # unreachable, or credentials unobtainable: create nothing
```

| State | Meaning |
|---|---|
| `ready` | Connected, authenticated, database usable |
| `database_absent` | Authenticated, but the database does not exist |
| `access_denied` | Authenticated, but may not use this database |
| `authentication_failed` | Reached the server; it rejected the credentials |
| `unreachable` | Could not reach the server |
| `credentials_unobtainable` | Credentials could not be obtained; nothing was attempted |

One thing worth understanding: a server authenticates *before* it resolves the
database. On a site with neither the account nor the database, you get
`authentication_failed` and never `database_absent` — so a failed login by the
account being provisioned is evidence about the account, not about the
database. That is why administrative credentials, not the WordPress account,
decide what exists.

## Command line

```shell
# report state; changes nothing, needs no administrative credentials
l3io-wordpress-database --inspect --wp-config /var/www/wp-config.php

# provision
l3io-wordpress-database --wp-config /var/www/wp-config.php \
    --admin-username root --admin-password secret

# administrative credentials from AWS Secrets Manager (needs the 'aws' extra)
l3io-wordpress-database --wp-config /var/www/wp-config.php \
    --admin-credentials-aws-secret-id AdminSecretId \
    --admin-credentials-aws-region eu-west-1
```

Exit codes are distinct per failure class, so automation can branch without
parsing messages: `0` ok, `2` usage, `3` configuration, `4` credentials,
`5` unreachable, `6` provisioning failed, `7` not ready (from `--inspect`).

## Supported servers

MySQL 8.0, MySQL 8.4, MySQL 9.x and MariaDB (10.2 or newer). Each is exercised
in CI. The authentication plugin is never hardcoded — `mysql_native_password`
was removed in MySQL 9.0 — so the server's own default is used.

## Development

```shell
make sync            # locked environment, all extras
make check           # lint, format, types, tests, contracts
make test-db DB_HOST=127.0.0.1   # integration tests against a real server
make ci              # replay the CI pipeline locally under act
make verify-wheel    # install the BUILT wheel into an isolated env and import it
```

`make verify-wheel` matters more than it looks: installing the working tree
would have passed throughout the six years the predecessor package could not be
installed from PyPI at all.

## Licence

MIT. A predecessor of this package was written by Cariad Eccleston; the
`wp-config.php` reader it used lives on as `l3io-wordpress-config`.
