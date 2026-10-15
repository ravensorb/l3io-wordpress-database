# ADR-0003: `age`, through `pyrage`, is the encryption format

- **Status:** Accepted
- **Date:** 2026-10-14
- **Deciders:** Shawn Anderson

## Context

Dumps leave the server and sit in backups. The family needs one encryption format
that streams, whose output an operator can decrypt without this package, and that
needs no key-server or keyring state.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| GPG through `python-gnupg` | widely known | needs the `gpg` binary and keyring state |
| Fernet (`cryptography`) | one dependency | not streaming; a format only Python reads |
| `age` through `pyrage` | streaming, standard format, SSH keys as recipients | `pyrage` ships no type information |

## Decision

`age` through `pyrage>=1.4,<2`, behind the `encryption` extra and imported only
when used. `recipients` takes `age` or SSH public keys; `identities` takes `age`
identities, which may themselves be passphrase-protected. A wrong identity raises
`DecryptionError`; a truncated or damaged stream raises `CorruptDumpError`, because
the remedy differs.

## Consequences

- Any dump decrypts with the stock `age` command line; backup's archives use the
  same format.
- Encryption streams with bounded memory (a 512 MiB dump encrypts with an 11 MiB
  peak).
- Damage is found mid-load, so callers load into a staging database first.
