# ADR-0002: Credentials reach client tools through an anonymous-pipe option file

- **Status:** Accepted
- **Date:** 2026-10-14
- **Deciders:** Shawn Anderson

## Context

`mysqldump`, `mariadb-dump`, `mysql` and `mariadb` need the password. Every user on
the machine can read a process's argument vector, `/proc/<pid>/environ` exposes
`MYSQL_PWD`, an option file on disk outlives the process, and MySQL clients read
`~/.mylogin.cnf` even when told to use another option file.

## Options considered

| Option | Risk |
|---|---|
| `--password=` in the arguments | readable by every local user |
| `MYSQL_PWD` | readable through `/proc`; deprecated by MySQL |
| a `0600` temporary option file | on disk, and left behind by a crash |
| `--defaults-extra-file` | still reads the user's own option files |
| an option file written to a pipe | none of the above |

## Decision

The `[client]` options — user, password, host, port and `protocol=TCP` — are
written to `os.pipe()`. The read end is passed with `pass_fds` and named as
`--defaults-file=/dev/fd/N`, the first argument. The child's environment is
`PATH`, `LANG`, `LC_ALL` and `MYSQL_TEST_LOGIN_FILE` (a nonexistent path) and
nothing else; MySQL 8.4 and later also get `--no-login-paths`. Values are quoted
and escaped, and a value whose escaped form exceeds 1024 UTF-8 bytes, or that is not
UTF-8, is refused, because MariaDB's option reader splits long lines.

## Consequences

- No password in an argument vector, an environment or a file; a hostile
  `~/.my.cnf` or `~/.mylogin.cnf` changes nothing.
- `protocol=TCP` makes `localhost` mean the same server to the tool as to PyMySQL.
- Needs `/dev/fd`. MySQL 8.1–8.3 clients lack `--no-login-paths`; those releases
  are past end of life and not supported.
