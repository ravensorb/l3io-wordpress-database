# ADR-0004: Every operation that changes or moves something has a check

- **Status:** Accepted
- **Date:** 2026-10-14
- **Deciders:** Shawn Anderson

## Context

Callers need to know, before anything runs, whether an operation would be refused
and why, and to branch on the reason without parsing a message. A boolean loses the
reason; an exception alone cannot be asked for in advance.

## Decision

Each operation `X` that changes or moves something has `check_X(...) -> Verdict`,
which changes nothing. A `Verdict` holds `Finding`s; each has a `Code` with exactly
one severity, blocker or warning. `X` runs the same check and raises `RefusedError`,
carrying the `Verdict`, on any blocker, so the check is never skipped and never
differs from the run. Warnings travel on every result and are logged once.

## Consequences

- A dry run is a call to `check_X`.
- The code catalogue is an API: every code is documented, and a test fails if no
  test asserts it.
- A refusal that is not a finding — an unusable argument — is an exception raised
  before anything starts.
