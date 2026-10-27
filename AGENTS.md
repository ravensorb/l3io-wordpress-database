<!-- bmad:context -->
<!-- Verified 2026-10-14 against 76c0c6a.
     Managed by bmad-project-context; edits inside this block are replaced on
     refresh. Keep anything you want preserved outside the markers. -->

## l3io-wordpress-database

The operations a WordPress site performs on its MySQL or MariaDB database: inspect,
provision, change accounts, destroy, export and import. Imports as `l3io.wp.database`,
a PEP 420 namespace shared with `l3io-wordpress-config` and `l3io-wordpress-backup`.
Python 3.11+, uv, ruff, mypy --strict, PyMySQL. The spec and plans live in
`_bmad-output/planning-artifacts/`; this package's decisions are in `docs/adr/`.

## Policy

- Never add `__init__.py` at `src/l3io/` or `src/l3io/wp/`. It makes this a
  regular package, shadowing the namespace and making both sibling
  distributions unimportable. `mypy` will actively suggest adding one; the fix
  is `mypy_path` + `explicit_package_bases` + `namespace_packages`, never the
  file. `tests/test_architecture.py` and a CI step fail on it in this repo alone;
  the sibling breakage it causes only shows once two packages are installed.
- Never publish — not to PyPI, TestPyPI or the Gitea registry, and not the
  package under `tombstone/`. Releases are Shawn's, and the Gitea registry is
  temporary staging — PyPI comes after all three packages are refactored,
  bottom-up.
- `main` describes only the current package. Material from earlier packages lives
  on the `legacy/main` branch; read it there and never re-add it. State a rule's reason as a present-tense
  risk, not as history — `tests/test_current_only.py` catches only the common words.
- Family rules (AD-n) live in `l3io-wordpress-backup`'s architecture spine; cite
  them, never copy them here.

## Where things are

- Public API and `__all__`: `src/l3io/wp/database/__init__.py`; the `Database`
  facade: `facade.py`.
- Provisioning: `provision.py`. Inspection: `inspection.py`. Export and import:
  `transfer.py`, with client-tool discovery and the option pipe in `_client.py`.
  CLI: `cli.py`.
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
- Export and import tests skip unless run by `make test-transfer ENGINE=mysql:8.4`
  (any server image): they need that image's own client tools.

## Conventions that differ from defaults

- `l3io-wordpress-config` is pinned to a git tag in `[tool.uv.sources]` and must never
  reach a release. `uv build --no-sources` strips it; a VCS dependency in
  published metadata makes the package unresolvable from PyPI.
- Under act, database services are on `127.0.0.1`, not the service label — act
  runs the job with `--network host`. The test matrix collapses to one leg via
  `vars.LOCAL_ACT` because parallel legs collide on host port 3306.

## Known pitfalls

- Ping a database container for readiness over TCP (`mysqladmin ping -h127.0.0.1`);
  over the Unix socket the image's temporary setup server answers first.

<!-- /bmad:context -->

## Interim (plan-4)

- `pyrage` is also git-pinned under `[tool.uv.sources]` (fork tip with
  `passphrase.encrypt_io` / `decrypt_io`) until upstream PyPI ships those APIs.
  Same strip-before-publish rule as config; see handoff 0.2.0 feature section.
