"""The facade binds a connection and adds nothing else."""

from __future__ import annotations

import inspect as pyinspect
from collections.abc import Callable
from typing import Any

from l3io.wp.database import inspection, provision
from l3io.wp.database.connection import Connection
from l3io.wp.database.credentials import Explicit
from l3io.wp.database.facade import Database
from l3io.wp.database.state import ConnectionState

OPERATIONS = [
    "survey",
    "inspect",
    "schema_version",
    "check_ensure",
    "ensure",
    "check_rotate_password",
    "rotate_password",
    "check_revoke",
    "revoke",
    "check_drop_user",
    "drop_user",
    "check_drop_database",
    "drop_database",
]


def _free(name: str) -> Callable[..., Any]:
    found: Callable[..., Any] = getattr(inspection, name, None) or getattr(provision, name)
    return found


def test_every_operation_is_bound_with_the_same_parameters() -> None:
    for name in OPERATIONS:
        free = list(pyinspect.signature(_free(name)).parameters)
        bound = list(pyinspect.signature(getattr(Database, name)).parameters)
        assert bound == ["self", *free[1:]], name


def test_inspect_delegates() -> None:
    db = Database(Connection(host="127.0.0.1", database="wp", port=1))
    assert db.inspect(Explicit("u", "p")) is ConnectionState.UNREACHABLE
