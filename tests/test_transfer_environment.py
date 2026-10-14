"""The transfer container provides the server's own client tools.

Runs only inside `make test-transfer`, which sets L3IO_TRANSFER_CONTAINER.
"""

from __future__ import annotations

import os
import shutil

import pytest

pytestmark = [
    pytest.mark.transfer,
    pytest.mark.skipif(
        not os.environ.get("L3IO_TRANSFER_CONTAINER"), reason="runs inside make test-transfer"
    ),
]


def test_the_images_client_tools_are_on_path() -> None:
    engine = os.environ["L3IO_ENGINE"]
    names = ("mariadb-dump", "mysqldump") if engine.startswith("mariadb") else ("mysqldump",)
    assert any(shutil.which(n) for n in names), f"no dump tool on PATH in {engine}"
