# Architecture decision records

This package's own decisions. The rules the `l3io.wp` family shares (AD-n) are in
`l3io-wordpress-backup`'s architecture spine and are not restated here.

| ADR | Decision |
|---|---|
| [0001](0001-operations-owned-here.md) | Every operation on a site's database, including export and import, is owned here |
| [0002](0002-credentials-through-a-pipe.md) | Credentials reach client tools through an anonymous-pipe option file |
| [0003](0003-age-encryption.md) | `age`, through `pyrage`, is the encryption format |
| [0004](0004-check-first-verdict.md) | Every operation that changes or moves something has a check returning a `Verdict` |
| [0005](0005-destructive-calls-name-the-target-twice.md) | Destructive calls name their target twice |
