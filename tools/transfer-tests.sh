#!/usr/bin/env bash
# Runs inside a container built from a database SERVER image, so the client
# tools under test are the ones that ship with that server (probe V3). The
# repository is mounted read-only at /repo; everything written goes to /tmp.
set -euo pipefail

if command -v microdnf >/dev/null; then
  microdnf install -y git >/dev/null          # Oracle Linux (mysql:*); no -q flag
else
  apt-get update -qq >/dev/null
  apt-get install -y -qq curl ca-certificates git >/dev/null   # Debian/Ubuntu (mariadb:*)
fi
curl -LsSf https://astral.sh/uv/0.11.6/install.sh | env UV_UNMANAGED_INSTALL=/tmp/uvbin sh >/dev/null

export PATH=/tmp/uvbin:$PATH UV_PROJECT_ENVIRONMENT=/tmp/venv UV_CACHE_DIR=/tmp/uvcache
export UV_PYTHON=3.11 PYTHONDONTWRITEBYTECODE=1
git config --global --add safe.directory /repo
cd /repo
uv sync --locked --all-extras --dev -q

for _ in $(seq 1 90); do
  if uv run --no-sync python -c "import os, pymysql; pymysql.connect(host=os.environ['DB_HOST'], port=int(os.environ['DB_PORT']), user='root', password='root').close()" 2>/dev/null; then
    break
  fi
  sleep 2
done
exec uv run --no-sync pytest -p no:cacheprovider -m transfer
