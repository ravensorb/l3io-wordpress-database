---
status: final
stepsCompleted: [1, 2, 3, 4]
inputDocuments:
  - _bmad-output/planning-artifacts/plans/2026-10-20-plan-4-passphrase-stream.md
  - _bmad-output/planning-artifacts/spec/2026-10-12-l3io-wordpress-database-design.md
  - docs/adr/0003-age-encryption.md
  - docs/handoff/wordpress-database.md
---

# l3io-wordpress-database - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for
l3io-wordpress-database plan-4 (streaming passphrase encryption → 0.2.0),
decomposing the requirements from the plan-4 design, design spec encryption
sections, ADR-0003, and handoff into implementable stories.

## Requirements Inventory

### Functional Requirements

FR1: Contribute streaming passphrase encrypt/decrypt IO to upstream pyrage
(`passphrase.encrypt_io` / `decrypt_io`), mirroring recipient `encrypt_io` /
`decrypt_io`, leaving existing one-shot `passphrase.encrypt` / `decrypt` unchanged.

FR2: pyrage streaming passphrase output MUST be decryptable by stock `age -d`
(age v1 scrypt recipient as sole recipient).

FR3: `encrypt(reader, writer, recipients=None, *, passphrase=None)` streams any
byte stream (dumps or caller-built archives) as age; exactly one of `recipients`
or `passphrase`.

FR4: `decrypt(reader, writer, identities=None, *, passphrase=None)` streams age
ciphertext to plaintext; exactly one of `identities` or `passphrase`.

FR5: `check_passphrase(passphrase)` refuses a passphrase encrypt could not use,
before any data moves (parallel to `check_recipients`).

FR6: Package root re-exports `encrypt`, `decrypt`, `check_recipients`,
`check_passphrase`, and `generate_identity` in `__all__`, covered by the
API-surface / export guards.

FR7: `dump` / `iter_dump` / `check_dump` accept keyword `passphrase=` mutually
exclusive with `recipients=`.

FR8: `load` / `check_load` accept keyword `passphrase=` mutually exclusive with
`identities=`; passphrase path uses `encryption.decrypt(..., passphrase=)`.

FR9: Encrypted source with neither identities nor passphrase yields
`IDENTITY_REQUIRED` with message mentioning both `identities=` and `passphrase=`
(no new verdict code in 0.2.0).

FR10: Wrong passphrase raises `DecryptionError`; truncated / non-age / damaged
body raises `CorruptDumpError`.

FR11: Empty passphrase, both modes set, or neither mode set on encrypt/decrypt
raises `InvalidArgumentsError`.

FR12: CLI dump/load gain a passphrase path that never puts the secret on argv
(`--passphrase-file` and/or TTY prompt); mutex with `--recipient` / `--identity`.

FR13: `encryption` extra's pyrage lower bound rises to the first release that
ships streaming passphrase IO (`pyrage>=X,<2`).

FR14: Amend ADR-0003 and design spec (§6, §7.3, §9, §12, §13) for passphrase
streaming; update README and handoff for backup's 0.2.0 pin.

FR15: Target release is 0.2.0; after merge, Shawn cuts the release (same publish
path as 0.1.0). Backup pins `l3io-wordpress-database[encryption]>=0.2,<0.3`.

### NonFunctional Requirements

NFR1: Streaming — bounded memory independent of archive/dump size; large
chunked readers must not hold the whole plaintext (backup AD-21 intent).

NFR2: Secrets — passphrase never on argv, never in logs, spans, exception
messages, captured stderr, or `repr` (spec §2.4).

NFR3: Lazy import — passphrase path stays behind the `encryption` extra;
base install must not pull `pyrage`.

NFR4: Operator recovery — ciphertext decrypts with stock `age -d` without this
package.

NFR5: No hand-rolled age crypto; no whole-archive buffering via one-shot
`pyrage.passphrase.*`; no `age` CLI subprocess for the passphrase path.

NFR6: Published metadata must not carry a VCS pin of pyrage; a temporary
`[tool.uv.sources]` git pin is allowed for development only and must be
stripped before 0.2.0 publish.

NFR7: Existing recipient/identity path and one-shot identity-file unlock
(`read_identity`) remain unchanged in behaviour.

NFR8: Combining passphrase with recipients/identities is refused loudly (age
forbids scrypt with other recipients).

### Additional Requirements

- Delivery depends on an external pyrage PyPI release; this backlog owns the
  upstream PR work as Epic 1.
- Dev may git-pin pyrage under `[tool.uv.sources]` while waiting on PyPI, same
  pattern as config today.
- `_Header.needs_identity` flag name stays; docstring means "needs a decryption
  secret."
- Out of scope for 0.2.0: backup's AD-26 chain; distinct `PASSPHRASE_REQUIRED`
  code; publishing pyrage ourselves; changing Exit code 6.
- Facade (`Database`) methods mirror dump/load passphrase kwargs.
- Optional slow peak-RSS test size TBD with Shawn; minimum is a chunked-reader
  streaming proof.

### UX Design Requirements

N/A — no UX design contract for this library/CLI slice.

### FR Coverage Map

FR1: Epic 1 — pyrage streaming passphrase encrypt_io / decrypt_io
FR2: Epic 1 — stock age -d decrypts upstream passphrase ciphertext
FR3: Epic 2 — encrypt(..., passphrase=) for any byte stream
FR4: Epic 2 — decrypt(..., passphrase=)
FR5: Epic 2 — check_passphrase
FR6: Epic 2 — root re-exports + API-surface guards
FR7: Epic 2 — dump / iter_dump / check_dump passphrase=
FR8: Epic 2 — load / check_load passphrase=
FR9: Epic 2 — IDENTITY_REQUIRED message includes passphrase
FR10: Epic 2 — DecryptionError vs CorruptDumpError for passphrase
FR11: Epic 2 — InvalidArgumentsError for mutex / empty passphrase
FR12: Epic 2 — CLI passphrase path (no secret on argv)
FR13: Epic 2 — encryption extra pyrage lower bound
FR14: Epic 2 — ADR-0003, spec, README, handoff amendments
FR15: Epic 2 — target 0.2.0; backup pin guidance

## Epic List

### Epic 1: Upstream streaming passphrase in pyrage
Shawn can land streaming scrypt encrypt/decrypt in pyrage so a PyPI release
unblocks this package — without buffering whole archives.
**FRs covered:** FR1, FR2

### Epic 2: Passphrase encryption for archives and dumps (0.2.0)
Backup and other callers can stream-encrypt/decrypt any byte stream — including
archives — via a public root API and dump/load with passphrase=, with stock
age -d recovery, then pin l3io-wordpress-database[encryption]>=0.2,<0.3.
**FRs covered:** FR3, FR4, FR5, FR6, FR7, FR8, FR9, FR10, FR11, FR12, FR13, FR14, FR15

## Epic 1: Upstream streaming passphrase in pyrage

Shawn can land streaming scrypt encrypt/decrypt in pyrage so a PyPI release
unblocks this package — without buffering whole archives.

### Story 1.1: Add passphrase.encrypt_io / decrypt_io to pyrage

As a maintainer of l3io-wordpress-database,
I want pyrage to expose streaming passphrase encrypt/decrypt over file-like IO,
So that multi-GB archives never need to be buffered as `bytes`.

**Acceptance Criteria:**

**Given** a PR against woodruffw/pyrage implementing `passphrase.encrypt_io` /
`decrypt_io` mirroring recipient `encrypt_io` / `decrypt_io`
**When** a multi-chunk stream is encrypted then decrypted with the same passphrase
**Then** the plaintext matches and existing `passphrase.encrypt` / `decrypt` are
unchanged
**And** a wrong passphrase raises `DecryptError`; a truncated body fails in a
mode distinct from a wrong passphrase

**Given** a large synthetic streaming reader
**When** `encrypt_io` runs
**Then** peak RSS stays flat (proves streaming, not whole-buffer)

**Given** ciphertext produced by `encrypt_io`
**When** it is decrypted with stock `age -d` and the passphrase
**Then** the plaintext matches (FR1, FR2)

### Story 1.2: Unblock Epic 2 with an interim pyrage pin (PyPI floor deferred)

As a maintainer,
I want Epic 2 able to call `passphrase.encrypt_io` / `decrypt_io` without waiting
on upstream PyPI,
So that 0.2.0 package work is not stalled on review latency.

**Acceptance Criteria:**

**Given** Story 1.1's APIs exist on a reachable git rev (fork of woodruffw/pyrage#171)
**When** `[tool.uv.sources]` pins that rev for development
**Then** `from pyrage.passphrase import encrypt_io, decrypt_io` succeeds under `uv sync`
**And** the handoff documents the pin, strip-before-publish, and that PyPI floor `X`
is deferred until upstream releases (0.2.0 publish precondition; NFR6)

**Deferred (not this story):** PyPI wheel verification and recording `pyrage>=X,<2`.

## Epic 2: Passphrase encryption for archives and dumps (0.2.0)

Backup and other callers can stream-encrypt/decrypt any byte stream — including
archives — via a public root API and dump/load with `passphrase=`, with stock
`age -d` recovery, then pin `l3io-wordpress-database[encryption]>=0.2,<0.3`.

### Story 2.1: Stream encrypt/decrypt with passphrase= on the public API

As a backup (or other) caller,
I want `encrypt` / `decrypt` / `check_passphrase` with `passphrase=` on the
package root,
So that I can encrypt archive streams without building age argv or using private names.

**Acceptance Criteria:**

**Given** the `encryption` extra with pyrage at the floor from Story 1.2
**When** `from l3io.wp.database import encrypt, decrypt, check_passphrase,
check_recipients, generate_identity` is used
**Then** those names are in `__all__` and pass the API-surface / export guards (FR6)

**Given** a chunked byte reader (not a single `bytes` buffer)
**When** `encrypt(..., passphrase=secret)` then `decrypt(..., passphrase=secret)`
**Then** plaintext matches and ciphertext starts with the age header (FR3, FR4)
**And** stock `age -d` recovers the plaintext (NFR4)

**Given** both `recipients` and `passphrase`, or neither, or an empty passphrase
**When** `encrypt` or `decrypt` is called
**Then** `InvalidArgumentsError` is raised and the passphrase never appears in
the message (FR11, NFR2)

**Given** ciphertext encrypted with a passphrase
**When** decrypt uses the wrong passphrase
**Then** `DecryptionError` is raised
**And** a truncated or non-age body raises `CorruptDumpError` (FR10)

**Given** `check_passphrase`
**When** called before encrypt
**Then** it refuses a passphrase encrypt could not use without moving data (FR5)

**Given** a base install without the `encryption` extra
**When** the forbidden-import check runs
**Then** `pyrage` is still absent (NFR3)

### Story 2.2: Wire passphrase= through dump and load

As a caller of dump/load,
I want `passphrase=` on dump, iter_dump, check_dump, load, and check_load
(and the Database facade),
So that encrypted dumps use the same streaming passphrase path as archives.

**Acceptance Criteria:**

**Given** a database dump target
**When** `dump(..., passphrase=secret)` then `load(..., passphrase=secret)`
**Then** the load succeeds and tables match (FR7, FR8)

**Given** `recipients` and `passphrase` together on dump, or `identities` and
`passphrase` together on load
**When** the call is made
**Then** `InvalidArgumentsError` is raised (FR11, NFR8)

**Given** an age-encrypted source and neither identities nor passphrase
**When** `check_load` or `load` runs
**Then** a blocker `IDENTITY_REQUIRED` is reported whose message mentions both
`identities=` and `passphrase=` (FR9)

**Given** the Database facade
**When** dump/load/check_* are called with `passphrase=`
**Then** behaviour matches the module-level functions

### Story 2.3: CLI passphrase path without secret on argv

As an operator using the CLI,
I want dump/load to accept a passphrase via file or TTY prompt,
So that I can encrypt without putting the secret on the argument vector.

**Acceptance Criteria:**

**Given** `l3io-wordpress-database dump` with `--passphrase-file` (or TTY prompt)
**When** the dump completes
**Then** the output is age-encrypted with a scrypt recipient and the passphrase
never appears in argv (FR12, NFR2)

**Given** `--passphrase-file` together with `--recipient`, or load passphrase
together with `--identity`
**When** the CLI parses arguments
**Then** usage fails with a clear mutex error (FR12)

**Given** README command examples for the passphrase path
**When** `tests/test_readme.py` runs
**Then** every shown command line still parses

### Story 2.4: Raise pyrage bound; amend ADR, spec, README, handoff

As a family maintainer,
I want the encryption extra bound, ADR-0003, design spec, README, and handoff
updated for 0.2.0 passphrase streaming,
So that backup can pin `>=0.2,<0.3` against documented contracts.

**Acceptance Criteria:**

**Given** the pyrage floor from Story 1.2
**When** `pyproject.toml` `encryption` extra is updated to `pyrage>=X,<2`
**Then** declared-facts / extras tests enforce the bound and any
`[tool.uv.sources]` pyrage git pin is absent from a `--no-sources` build (FR13, NFR6)

**Given** ADR-0003 and the design spec (§6, §7.3, §9, §12, §13)
**When** amendments from plan-4 Part C are applied
**Then** passphrase streaming, mutex, error split, and stock `age -d` are
documented (FR14)

**Given** the handoff
**When** the 0.2.0 feature section is updated
**Then** it tells backup to pin
`l3io-wordpress-database[encryption]>=0.2,<0.3` and import `encrypt`/`decrypt`
from the package root for archives (FR15)
