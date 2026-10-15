# ADR-0001: Every operation on a site's database is owned here

- **Status:** Accepted
- **Date:** 2026-10-14
- **Deciders:** Shawn Anderson

## Context

`l3io-wordpress-backup`, test suites, provisioning scripts and operators all act on
WordPress databases: checking existence and emptiness, provisioning, changing
accounts, destroying, exporting and importing. Each caller that issues its own SQL
or runs `mysqldump` itself carries its own copy of the server-family differences
and its own way of handling a database password.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Each caller does its own database work | No dependency between packages | Several implementations of secret handling and portability |
| B. This package owns inspection and provisioning; backup owns export and import | Backup controls its archive path | Two packages pass passwords to client tools |
| C. This package owns every operation, export and import included | One implementation of each | This API becomes backup's contract |

## Decision

**C.** Every operation on a site's database is a call into this package. Backup
issues no SQL against a site's database and never handles a database password.
Export and import run the server's own client tools, chosen per server family; the
package never parses SQL.

## Consequences

- One place owns portability across MySQL 8.0–9.x and MariaDB 10.2+, and one place
  owns secret handling.
- Backup's dry run is a call to a `check_*` function.
- Export and import need the client tools on `PATH` and `/dev/fd`, so they do not
  run on Windows.
- 1.0.0 waits until backup has integrated against this API.
