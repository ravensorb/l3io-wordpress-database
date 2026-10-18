# Local equivalents of every CI gate. `make ci` replays the pipeline under act.
#
# Anything CI does that act cannot (artifact upload, and the clean-install job
# that consumes the uploaded artifact) has a local substitute here, so no gate
# is reachable only on a runner.

UV ?= uv
ACT ?= act
# --concurrent-jobs 1 is required locally, not a preference. act defaults to one
# job per CPU and runs the job container with --network host, so every parallel
# matrix leg's service container tries to bind host port 3306 and all but the
# first fail with "port is already allocated". On GitHub each leg gets its own
# runner, so the conflict does not exist there.
# -W pins act to ci.yml. act has no OIDC and ignores job.permissions, so it
# must never pick up publish.yml; file separation plus this flag is the boundary.
ACT_FLAGS ?= --var-file .act.vars --concurrent-jobs 1 -W .github/workflows/ci.yml

# ~/.actrc declares secrets as bare `-s NAME`, which act resolves from the
# environment; `infisical run` is what puts them there. act prompts for any
# that are unset OR empty and then fails on a non-interactive terminal, so the
# secrets have to be present even though ci.yml uses none of them.
#
# Do NOT substitute placeholder values. A bogus GITHUB_TOKEN is worse than an
# absent one: act passes it to git as a credential when fetching actions, and
# the fetch fails with "authentication required" instead of proceeding
# anonymously. Verified the hard way.
INFISICAL ?= infisical
INFISICAL_PROJECT ?= 7ca0e01b-28f6-4a61-b901-5fe834e1661a
INFISICAL_ENV ?= prod
# This repo's CI leaf in the home-lab project (ADR-0008): /ci/<platform>/<repo>.
INFISICAL_PATH ?= /ci/act/l3io-wordpress-database
ACT_RUNNER ?= $(INFISICAL) run --projectId $(INFISICAL_PROJECT) --env $(INFISICAL_ENV) --path $(INFISICAL_PATH) --

.DEFAULT_GOAL := help
.PHONY: help sync check lint format types test test-db test-transfer contracts namespace-check audit build verify-wheel ci ci-job ci-list ci-dryrun ci-dryrun-one clean

help: ## Show this help
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-16s %s\n", $$1, $$2}'

sync: ## Install the locked environment
	$(UV) sync --locked --all-extras --dev

check: lint format types test contracts ## Every gate that needs no database

lint: ## ruff check
	$(UV) run ruff check .

format: ## ruff format --check
	$(UV) run ruff format --check .

types: ## mypy --strict
	$(UV) run mypy --strict

test: ## Unit tests (integration skips without DB_HOST)
	$(UV) run pytest -q

test-db: ## Integration tests against a server; set DB_HOST first
	@test -n "$(DB_HOST)" || { echo "set DB_HOST (and DB_PORT/DB_ADMIN_USER/DB_ADMIN_PASSWORD)"; exit 1; }
	$(UV) run pytest -q tests/test_integration.py

TRANSFER_PORT ?= 33399

test-transfer: ## Export/import tests against ENGINE (a server image) using its own client tools
	@test -n "$(ENGINE)" || { echo "set ENGINE, e.g. make test-transfer ENGINE=mysql:8.4"; exit 1; }
	@set -eu; name="l3io-transfer-$$$$"; \
	docker run -d --rm --name "$$name" -e MYSQL_ROOT_PASSWORD=root -e MARIADB_ROOT_PASSWORD=root \
	  -p 127.0.0.1:$(TRANSFER_PORT):3306 "$(ENGINE)" >/dev/null; \
	trap 'docker rm -f "'"$$name"'" "'"$$name"'-tests" >/dev/null 2>&1' EXIT; \
	trap 'exit 130' INT TERM; \
	docker run --rm --name "$$name-tests" --network host -v "$(CURDIR)":/repo:ro \
	  -e L3IO_ENGINE="$(ENGINE)" -e L3IO_TRANSFER_CONTAINER=1 \
	  -e DB_HOST=127.0.0.1 -e DB_PORT=$(TRANSFER_PORT) -e DB_ADMIN_USER=root -e DB_ADMIN_PASSWORD=root \
	  --entrypoint bash "$(ENGINE)" /repo/tools/transfer-tests.sh & \
	wait $$!

contracts: ## Architecture contracts (AD-27, AD-28)
	$(UV) run pytest -q tests/test_architecture.py tests/test_identifiers.py

namespace-check: ## AD-27 alone, including sibling coexistence
	$(UV) run pytest -q tests/test_architecture.py -k "namespace or coexist"

audit: ## Scan uv.lock for known vulnerabilities (needs network; not part of check)
	$(UV) audit --locked --preview-features audit

build: ## Build wheel and sdist without development sources
	rm -rf dist
	$(UV) build --no-sources
	$(UV) run python tools/check_dist_metadata.py

verify-wheel: build ## Install the BUILT wheel into an isolated env and import it
	@# A fast standalone equivalent of CI's verify-install job. That job now
	@# runs under act too, so this is convenience rather than the only local
	@# coverage -- `make ci` exercises the same checks across the pipeline.
	@set -eu; \
	wheel=$$(ls dist/*.whl); \
	$(UV) run --isolated --no-project --with "$$wheel" \
	    python -c "from l3io.wp import database; print('import ok', database.__version__)"; \
	$(UV) run --isolated --no-project --with "$$wheel" python -c "\
import importlib.util, sys; \
[sys.exit('base install pulled ' + m) for m in ('boto3','botocore','l3io.wp.config','pyrage') if importlib.util.find_spec(m) is not None]; \
print('base install is clean')"; \
	$(UV) run --isolated --no-project --with "$$wheel" l3io-wordpress-database --version; \
	bash tools/verify_extras.sh "$$wheel"

ci: ## Replay the CI pipeline locally under act
	$(ACT_RUNNER) $(ACT) $(ACT_FLAGS)

ci-job: ## Replay one job under act, e.g. make ci-job JOB=static
	@test -n "$(JOB)" || { echo "set JOB, e.g. make ci-job JOB=static"; exit 1; }
	$(ACT_RUNNER) $(ACT) $(ACT_FLAGS) -j $(JOB)

ci-list: ## List the jobs act would run
	$(ACT_RUNNER) $(ACT) $(ACT_FLAGS) -l

# ---------------------------------------------------------------------------
# Validating the workflows act CANNOT execute
#
# `make ci` runs ci.yml for real. publish.yml and release.yml are deliberately
# outside it -- act has no OIDC and ignores job.permissions, so running them
# locally would be misleading at best, and release.yml CREATES TAGS and dispatches
# publishes, which must never happen from a laptop.
#
# A dry run is the middle ground and it is worth more than it looks. act resolves
# every `uses:` ref against the remote before deciding to skip the step, so a
# dryrun fails on an action version that does not exist -- it is what catches
# `changelog-parser@v3.0.14`, a real version of a DIFFERENT action, which no
# amount of YAML validation would have found. It also catches expression syntax
# errors, unknown contexts and missing `needs`.
#
# --dryrun IS LOAD-BEARING, not a nicety. Without it this target cuts real tags
# and fires real publishes. A contract test asserts every workflow named here is
# run with it, so removing it fails `make check` rather than surprising someone.
# ---------------------------------------------------------------------------

ACT_DRYRUN_FLAGS ?= --var-file .act.vars --concurrent-jobs 1 --dryrun

# The legs live in .github/act-dryrun-legs.json, not here, because a pytest
# contract asserts they reach every job in every workflow -- and it can only do
# that if both read the same declaration. Hand-listing them in the recipe would
# put the rule and its check in two places, which is how they drift.
#
# ci.yml is NOT dry-run: `make ci` runs it for real, and act SEGFAULTS dry-running
# it (nil pointer in containerReference.GetHealth) because it declares MySQL
# service containers that a dry run never starts. An act limitation, not a defect
# in the workflow.
ACT_DRYRUN_LEGS := .github/act-dryrun-legs.json

ci-dryrun: ## Dry-run the workflows `make ci` cannot run, resolving every action ref
	@set -eu; \
	test -f $(ACT_DRYRUN_LEGS) || { echo "missing $(ACT_DRYRUN_LEGS)"; exit 1; }; \
	legs=$$(python3 -c "import json;[print(l['workflow'],l['event'],l.get('eventpath','-'),','.join(f'{k}={v}' for k,v in (l.get('inputs') or {}).items()) or '-') for l in json.load(open('$(ACT_DRYRUN_LEGS)'))['legs']]"); \
	test -n "$$legs" || { echo "no legs declared -- this gate would pass vacuously"; exit 1; }; \
	rc=0; n=0; \
	echo "$$legs" | while read -r wf ev epath inputs; do \
	  args=""; \
	  [ "$$epath" = "-" ] || args="$$args -e $$epath"; \
	  if [ "$$inputs" != "-" ]; then \
	    for kv in $$(echo "$$inputs" | tr ',' ' '); do args="$$args --input $$kv"; done; \
	  fi; \
	  printf '%-13s %-18s %-26s ' "$$wf" "$$ev" "$$inputs"; \
	  if $(ACT_RUNNER) $(ACT) $(ACT_DRYRUN_FLAGS) -W ".github/workflows/$$wf" $$ev $$args \
	       >$(CURDIR)/.act-dryrun.log 2>&1; then echo "ok"; else \
	    echo "FAILED"; \
	    grep -iE "couldn.t find remote ref|failed to fetch|^Error:|invalid|unable to" $(CURDIR)/.act-dryrun.log \
	      | head -3 | sed 's/^/                                                       /'; \
	    echo fail >> $(CURDIR)/.act-dryrun.rc; \
	  fi; \
	  rm -f $(CURDIR)/.act-dryrun.log; \
	done; \
	if [ -f $(CURDIR)/.act-dryrun.rc ]; then rm -f $(CURDIR)/.act-dryrun.rc; \
	  echo "one or more legs failed"; exit 1; \
	else echo "all legs dry-run clean; every action ref resolved"; fi

ci-dryrun-one: ## Dry-run one workflow: make ci-dryrun-one WF=release.yml
	@test -n "$(WF)" || { echo "set WF, e.g. make ci-dryrun-one WF=release.yml"; exit 1; }
	@case "$(WF)" in \
	  release.yml) ev="workflow_dispatch --input bump=patch" ;; \
	  publish.yml) ev="workflow_dispatch --input target=mirror" ;; \
	  *)           ev="push" ;; \
	esac; \
	$(ACT_RUNNER) $(ACT) $(ACT_DRYRUN_FLAGS) -W .github/workflows/$(WF) $$ev

clean: ## Remove build output
	rm -rf dist .pytest_cache .mypy_cache .ruff_cache

# ---------------------------------------------------------------------------
# Releasing
#
# These targets do NOT compute a version, build, or publish. They dispatch
# release.yml and stop. The version is derived from the git tag by hatch-vcs
# (AD-30), so anything that worked out a version locally would be a second
# implementation of the one thing that must have exactly one.
#
# `make release patch` and `make release BUMP=patch` are the same command. The
# bare words are no-op targets that exist only so make does not fail on the
# second goal.
# ---------------------------------------------------------------------------

GH ?= gh
RELEASE_WORKFLOW ?= release.yml
RELEASE_BRANCH ?= main
BUMP ?=

_BUMP_WORDS := patch minor major dev
_BUMP_GOAL := $(firstword $(filter $(_BUMP_WORDS),$(MAKECMDGOALS)))
_BUMP := $(if $(BUMP),$(BUMP),$(_BUMP_GOAL))

.PHONY: release release-patch release-minor release-major release-dev $(_BUMP_WORDS)

release: ## Cut a release: make release patch|minor|major|dev
	@set -eu; \
	bump="$(_BUMP)"; \
	if [ -z "$$bump" ]; then \
	  echo "usage: make release patch|minor|major|dev   (or make release BUMP=patch)"; \
	  exit 2; \
	fi; \
	case "$$bump" in patch|minor|major|dev) ;; *) echo "unknown bump '$$bump'"; exit 2 ;; esac; \
	command -v $(GH) >/dev/null || { echo "gh is not installed"; exit 1; }; \
	$(GH) auth status >/dev/null 2>&1 || { echo "gh is not authenticated: run 'gh auth login'"; exit 1; }; \
	branch=$$(git rev-parse --abbrev-ref HEAD); \
	if [ "$$branch" != "$(RELEASE_BRANCH)" ]; then \
	  echo "on '$$branch', not '$(RELEASE_BRANCH)' -- release.yml tags whatever it checks out"; exit 1; \
	fi; \
	if [ -n "$$(git status --porcelain --untracked-files=no)" ]; then \
	  echo "tracked files are modified. That work is NOT in the release, and a dirty"; \
	  echo "tree also makes a local build report a different version than the tag."; \
	  git status --short --untracked-files=no; exit 1; \
	fi; \
	git fetch --quiet origin $(RELEASE_BRANCH); \
	if [ "$$(git rev-parse HEAD)" != "$$(git rev-parse origin/$(RELEASE_BRANCH))" ]; then \
	  echo "HEAD and origin/$(RELEASE_BRANCH) differ -- the workflow releases the PUSHED commit,"; \
	  echo "so push or pull first. Local: $$(git rev-parse --short HEAD)  origin: $$(git rev-parse --short origin/$(RELEASE_BRANCH))"; \
	  exit 1; \
	fi; \
	latest=$$(git tag -l 'v[0-9]*.[0-9]*.[0-9]*' --sort=-v:refname | head -1); \
	echo "  repo         $$($(GH) repo view --json nameWithOwner -q .nameWithOwner)"; \
	echo "  commit       $$(git rev-parse --short HEAD)"; \
	echo "  latest tag   $${latest:-<none: the first release will be v1.0.0>}"; \
	echo "  bump         $$bump"; \
	if [ "$$bump" = "dev" ]; then \
	  echo "  effect       publishes this commit to the internal mirror as <next patch>.dev<distance>; NO tag, NO GitHub release"; \
	else \
	  echo "  effect       pushes the next $$bump tag, which triggers build, smoke, mirror publish and a GitHub release"; \
	fi; \
	printf "\nType the bump to confirm: "; \
	read -r reply; \
	if [ "$$reply" != "$$bump" ]; then echo "aborted"; exit 1; fi; \
	$(GH) workflow run $(RELEASE_WORKFLOW) --ref $(RELEASE_BRANCH) -f bump="$$bump"; \
	echo; \
	echo "dispatched. Watch it with:  $(GH) run watch \$$($(GH) run list --workflow $(RELEASE_WORKFLOW) --limit 1 --json databaseId -q '.[0].databaseId')"

release-patch: ## Release a patch version (alias for: make release patch)
	@$(MAKE) --no-print-directory release BUMP=patch

release-minor: ## Release a minor version
	@$(MAKE) --no-print-directory release BUMP=minor

release-major: ## Release a major version
	@$(MAKE) --no-print-directory release BUMP=major

release-dev: ## Publish a dev build of this commit to the mirror (no tag)
	@$(MAKE) --no-print-directory release BUMP=dev

# Reached only as the second goal of `make release <word>`. On its own it is a
# typo for the real target, so say so rather than silently succeeding.
$(_BUMP_WORDS):
	@case " $(MAKECMDGOALS) " in \
	  *" release "*) : ;; \
	  *) echo "make: '$@' is not a target. Did you mean 'make release $@'?"; exit 2 ;; \
	esac
