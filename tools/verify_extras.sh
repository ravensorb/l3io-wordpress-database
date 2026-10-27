#!/usr/bin/env bash
# Install the built wheel once per extra, each into its own isolated environment,
# and use what that extra enables (spec §12). Usage: verify_extras.sh WHEEL [PYTHON]
#
# l3io-wordpress-config is not on PyPI, so the wpconfig leg takes it from its
# GitHub release. l3io-age-passphrase is GitHub Releases only, so the encryption
# leg takes AGE_PASSPHRASE_WHEEL or downloads the manylinux abi3 wheel into
# .cache/age-passphrase-wheels/.
set -euo pipefail

wheel=${1:?usage: verify_extras.sh WHEEL [PYTHON]}
python=${2:-}
config_wheel=${WPCONFIG_WHEEL:-https://github.com/ravensorb/l3io-wordpress-config/releases/download/v0.1.0/l3io_wordpress_config-0.1.0-py3-none-any.whl}
pkg_url="file://$(realpath "$wheel")"

isolated() {
  uv run --isolated --no-project ${python:+--python "$python"} "$@"
}

binder_wheel=${AGE_PASSPHRASE_WHEEL:-}
if [ -z "$binder_wheel" ]; then
  # mkdir before realpath: realpath fails when the path does not exist yet
  # (CI runners have no .cache/; .gitignore excludes it).
  cache_dir="$(dirname "$0")/../.cache/age-passphrase-wheels"
  mkdir -p "$cache_dir"
  cache="$(realpath "$cache_dir")"
  binder_wheel=$(ls "$cache"/l3io_age_passphrase-*.whl 2>/dev/null | head -1 || true)
  if [ -z "$binder_wheel" ]; then
    ver=${BINDER_VERSION:-0.1.0}
    binder_download=${BINDER_WHEEL_URL:-https://github.com/ravensorb/l3io-age-passphrase/releases/download/v${ver}/l3io_age_passphrase-${ver}-cp311-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl}
    curl -fsSL -o "$cache/$(basename "$binder_download")" "$binder_download"
    binder_wheel=$(ls "$cache"/l3io_age_passphrase-*.whl | head -1)
  fi
fi
binder_url="file://$(realpath "$binder_wheel")"

isolated --with "l3io-wordpress-database[aws] @ $pkg_url" python -c '
import boto3
from l3io.wp.database import AwsSecretsManager
print("aws ok: boto3", boto3.__version__)
'

isolated --with "l3io-wordpress-database[encryption] @ $pkg_url" \
         --with "l3io-age-passphrase @ $binder_url" python -c '
from l3io.wp.database import generate_identity, encrypt, decrypt
import io
identity, recipient = generate_identity()
assert identity.startswith("AGE-SECRET-KEY-") and recipient.startswith("age1")
plain = b"verify-extras\n"
out = io.BytesIO()
encrypt(io.BytesIO(plain), out, passphrase="verify-secret")
back = io.BytesIO()
decrypt(io.BytesIO(out.getvalue()), back, passphrase="verify-secret")
assert back.getvalue() == plain
print("encryption ok")
'

isolated --with "l3io-wordpress-database[wpconfig] @ $pkg_url" \
         --with "l3io-wordpress-config @ $config_wheel" python - <<'PY'
import pathlib
import tempfile

from l3io.wp.database import WpConfigFile

path = pathlib.Path(tempfile.mkdtemp()) / "wp-config.php"
path.write_text(
    "<?php\ndefine('DB_NAME', 'wp_site');\ndefine('DB_USER', 'wp');\n"
    "define('DB_PASSWORD', 'ab);cd');\ndefine('DB_HOST', 'localhost');\n"
)
assert WpConfigFile(path).resolve().password == "ab);cd", "a config without the parser fix"
print("wpconfig ok")
PY
