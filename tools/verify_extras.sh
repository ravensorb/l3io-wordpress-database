#!/usr/bin/env bash
# Install the built wheel once per extra, each into its own isolated environment,
# and use what that extra enables (spec §12). Usage: verify_extras.sh WHEEL [PYTHON]
#
# l3io-wordpress-config is not on PyPI, so the wpconfig leg takes it from its
# GitHub release. The extra's own specifier must still accept that version, or uv
# refuses to resolve -- which is the point of installing through the extra.
set -euo pipefail

wheel=${1:?usage: verify_extras.sh WHEEL [PYTHON]}
python=${2:-}
config_wheel=${WPCONFIG_WHEEL:-https://github.com/ravensorb/l3io-wordpress-config/releases/download/v0.1.0/l3io_wordpress_config-0.1.0-py3-none-any.whl}
url="file://$(realpath "$wheel")"

isolated() {
  uv run --isolated --no-project ${python:+--python "$python"} "$@"
}

isolated --with "l3io-wordpress-database[aws] @ $url" python -c '
import boto3
from l3io.wp.database import AwsSecretsManager
print("aws ok: boto3", boto3.__version__)
'

isolated --with "l3io-wordpress-database[encryption] @ $url" python -c '
from l3io.wp.database import generate_identity
identity, recipient = generate_identity()
assert identity.startswith("AGE-SECRET-KEY-") and recipient.startswith("age1")
print("encryption ok")
'

isolated --with "l3io-wordpress-database[wpconfig] @ $url" \
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
