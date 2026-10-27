# ADR-0003: `age` is the encryption format (pyrage + passphrase backends)

- **Status:** Accepted (amended 2026-10-26 for dual passphrase backends)
- **Date:** 2026-10-14
- **Deciders:** Shawn Anderson

## Context

Dumps leave the server and sit in backups. The family needs one encryption format
that streams, whose output an operator can decrypt without this package, and that
needs no key-server or keyring state. Backup also needs the same format for
archives under a passphrase (not only recipient keys), without buffering
multi-gigabyte payloads or putting the secret on argv.

`pyrage` streams recipients via `encrypt_io` / `decrypt_io`, but its passphrase
module is one-shot only. Upstream declined growing that streaming surface
(woodruffw/pyrage#172). FiloSottile `age` ≥1.3 provides non-interactive
passphrase automation via `age-plugin-batchpass` and `AGE_PASSPHRASE_FD`.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| GPG through `python-gnupg` | widely known | needs the `gpg` binary and keyring state |
| Fernet (`cryptography`) | one dependency | not streaming; a format only Python reads |
| `age` through `pyrage` only | streaming recipients, SSH keys | passphrase path buffers whole payloads |
| Hand-rolled scrypt + STREAM | full control | not stock-`age` compatible; forever ours to maintain |
| Bare `age -p` subprocess | zero crypto code | TTY-only; no safe secret channel on argv |
| Young pure-Python age libs | no Rust wheel matrix | immature / unaudited for multi-GB dumps |
| Own thin PyO3 passphrase binder | streaming, stock format, in-process | we own wheels and crate bumps |
| `age` + `age-plugin-batchpass` | stock Go crypto, sole-scrypt files | needs binaries on PATH; FD secret hygiene |

## Decision

`age` remains the format. Two mutually exclusive modes on `encrypt` / `decrypt` /
`dump` / `load`:

1. **Recipients / identities** — via stock `pyrage` (`encrypt_io` / `decrypt_io`);
   age or SSH public keys; age identities (which may themselves be
   passphrase-protected on the small identity file via `pyrage.passphrase`).
2. **Passphrase** — `passphrase=` emits a sole scrypt recipient (stock `age -d`).
   Implementation is selectable:

   | `L3IO_AGE_PASSPHRASE_BACKEND` | Behaviour |
   |---|---|
   | `auto` (default) | `l3io-age-passphrase` if importable, else `age -j batchpass` if both binaries are on `PATH` |
   | `binder` | require `l3io-age-passphrase` |
   | `cli` | require `age` ≥1.3 and `age-plugin-batchpass` |

   The CLI path passes the secret on `AGE_PASSPHRASE_FD` (never argv). The WordPress
   / backup images we own install both the binder wheel and the age release
   tarball (which ships the plugin).

The `encryption` extra depends on `pyrage>=1.4,<2` and
`l3io-age-passphrase>=0.1,<0.2`. A wrong identity or passphrase raises
`DecryptionError`; a truncated or damaged stream raises `CorruptDumpError`.
Passphrases never appear in exception messages, logs, or spans. The CLI takes
`--passphrase-file` or `--ask-passphrase`, never `--passphrase SECRET`.

## Consequences

- Any dump or archive decrypts with the stock `age` command line; backup uses the
  same format for archives and can import `encrypt` / `decrypt` /
  `check_passphrase` from the package root.
- Encryption streams with bounded memory (payload size does not drive peak RSS;
  passphrase mode still pays a large fixed scrypt cost).
- Damage is found mid-load, so callers load into a staging database first.
- We maintain `l3io-age-passphrase` (maturin wheels) as a sibling package; the
  CLI backend is an image-provided fallback, not a PyPI dependency.
- Pin `l3io-wordpress-database[encryption]>=0.2,<0.3` once 0.2.0 is published.
