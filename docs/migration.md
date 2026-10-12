# Migrating from `wpdatabase2`

`l3io-wordpress-database` is a rewrite, not a new version of `wpdatabase2`: nothing of
the old public API is preserved, and there is no compatibility shim. The table
below maps every entry point that existed before onto its replacement.

See [rewrite-notes.md](rewrite-notes.md) for what changed and why.


| Before | After |
|---|---|
| `import wpdatabase2` | `from l3io.wp import database` |
| `wpdatabase2.ensure(path, credentials)` | `WpDatabase(WpConfigSource(path).connection()).ensure(admin)` |
| `WpConnection(db_host=..., db_name=...)` | `WpConnection.from_db_host(db_host=..., db_name=...)` |
| `credentials.username` | `credentials.resolve().username` |
| `db.test_config()` | `db.inspect().is_ready` |
| `db.does_database_exist()` | `db.inspect()` — six states, not a boolean |
| `except mysql.connector.Error` | `except WpDatabaseError` |
