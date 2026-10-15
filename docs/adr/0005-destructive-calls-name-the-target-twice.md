# ADR-0005: Destructive calls name their target twice

- **Status:** Accepted
- **Date:** 2026-10-14
- **Deciders:** Shawn Anderson

## Context

`drop_database`, `drop_user`, `revoke`, and a load over existing tables destroy
data. A variable holding the wrong name destroys the wrong thing, and nothing
inside the call can tell.

## Decision

`drop_database`, `drop_user` and `revoke` require `confirm=` equal to their
target; `load` into a database holding tables requires `replace=` equal to the
connection's database. A mismatch is the `CONFIRMATION_MISMATCH` blocker. The
command line requires `--confirm NAME` and `--replace NAME`. A destructive target
that holds a WordPress site also raises the `LIVE_WORDPRESS_SITE` warning.

## Consequences

- A wrong variable is refused instead of acted on.
- Calls are more verbose, on purpose.
