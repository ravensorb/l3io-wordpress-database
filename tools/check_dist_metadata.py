"""Assert no development source reached the built distributions' metadata.

Scope, deliberately narrow and stated so this cannot be mistaken for the
stronger claim: this checks the *resolved dependency metadata* of the wheel and
the sdist. It does NOT assert that the sdist's own ``pyproject.toml`` is free of
``[tool.uv]`` configuration -- it is not, and that is inert because uv honours
sources and required-version for the project being developed rather than for a
dependency built from an sdist, and pip ignores the table entirely. See
ADR-0007, which splits those two claims.

Why it inspects ``Requires-Dist`` lines specifically, and must keep doing so: a
search for a hostname over the whole file reports a leak on a completely clean
artifact. ``Project-URL`` entries and the README carried in the long description
both legitimately contain ``github.com``. A check that cries wolf gets switched
off, so do not "simplify" this into a grep.
"""

from __future__ import annotations

import argparse
import re
import sys
import tarfile
import zipfile
from pathlib import Path

#: A dependency source that must never reach published metadata. A VCS or local
#: dependency in a published release makes the package unresolvable from PyPI.
FORBIDDEN = (
    "git+",
    "@ git",
    "file://",
    "@ http://",
    "@ https://",
)

ROOT = Path(__file__).resolve().parent.parent


def offending(metadata: str) -> list[str]:
    """Return the Requires-Dist lines that carry a development source."""
    return [
        line
        for line in metadata.splitlines()
        if line.startswith("Requires-Dist:") and any(marker in line for marker in FORBIDDEN)
    ]


def wheel_metadata(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        name = next(n for n in archive.namelist() if re.match(r".*\.dist-info/METADATA$", n))
        return archive.read(name).decode()


def sdist_metadata(path: Path) -> str:
    with tarfile.open(path) as archive:
        name = next(n for n in archive.getnames() if n.endswith("PKG-INFO"))
        member = archive.extractfile(name)
        if member is None:  # pragma: no cover - PKG-INFO is always a file
            msg = f"{path}: PKG-INFO is not a regular file"
            raise RuntimeError(msg)
        return member.read().decode()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dist",
        default="dist",
        help="directory holding the built distributions (default: dist)",
    )
    args = parser.parse_args()
    dist = ROOT / args.dist

    wheels = sorted(dist.glob("*.whl"))
    sdists = sorted(dist.glob("*.tar.gz"))
    if not wheels or not sdists:
        print(f"no distributions found in {dist}; run `uv build --no-sources` first")
        return 1

    failed = False
    for path, reader in ((wheels[-1], wheel_metadata), (sdists[-1], sdist_metadata)):
        bad = offending(reader(path))
        if bad:
            failed = True
            print(f"::error::development source reached {path.name} metadata")
            for line in bad:
                print(f"  {line}")
        else:
            print(f"{path.name}: dependency metadata clean")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
