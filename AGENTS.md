<!-- bmad:context -->
<!-- Verified 2026-10-12 against 6c8c423.
     Managed by bmad-project-context; edits inside this block are replaced on
     refresh. Keep anything you want preserved outside the markers. -->

## l3io-wordpress-database

Creates and inspects WordPress MySQL databases and their users, idempotently.
Imports as `l3io.wp.database`, a PEP 420 namespace shared with
`l3io-wordpress-config` and `l3io-wordpress-backup`. Python 3.11+, uv, ruff, mypy --strict, PyMySQL.
Planning artifacts live in `_bmad-output/planning-artifacts/`.

## Policy

- Never add `__init__.py` at `src/l3io/` or `src/l3io/wp/`. It makes this a
  regular package, shadowing the namespace and making both sibling
  distributions unimportable. `mypy` will actively suggest adding one; the fix
  is `mypy_path` + `explicit_package_bases` + `namespace_packages`, never the
  file. `tests/test_architecture.py` and a CI step fail on it in this repo alone;
  the sibling breakage it causes only shows once two packages are installed.
- Never publish. Releases are Shawn's, and the Gitea registry is temporary
  staging — PyPI comes after all three packages are refactored, bottom-up.

## Where things are

- Public API and `__all__`: `src/l3io/wp/database/__init__.py`
- Provisioning and state inspection: `database.py`. CLI: `cli.py`.
- Generated data: `_version_map.py` — never hand-edit; regenerate with
  `uv run python tools/generate_version_map.py`.

## Running and verifying

- Use the `make` targets, not bare `ruff`/`pytest` calls. CI checks `.`, which
  includes Python code blocks inside Markdown; narrower hand-run checks pass
  while CI fails.
- `make ci` replays the whole pipeline under act and needs Infisical for the
  bare `-s` secrets `~/.actrc` declares. Do not substitute placeholders: a
  bogus `GITHUB_TOKEN` makes act fail to fetch actions, which is worse than an
  absent one.
- `uv run` syncs the default groups and **prunes extras**, which is why the
  optional dependencies are also in the dev group. Without that, `uv run`
  silently uninstalls them and their tests skip instead of running.
- Integration tests skip unless `DB_HOST` is set: `make test-db DB_HOST=127.0.0.1`.

## Conventions that differ from defaults

- `l3io-wordpress-config` is pinned to a git tag in `[tool.uv.sources]` and must never
  reach a release. `uv build --no-sources` strips it; a VCS dependency in
  published metadata is the defect that left the predecessor unresolvable for
  six years.
- Under act, database services are on `127.0.0.1`, not the service label — act
  runs the job with `--network host`. The test matrix collapses to one leg via
  `vars.LOCAL_ACT` because parallel legs collide on host port 3306.

<!-- /bmad:context -->
