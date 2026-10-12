from __future__ import annotations

from l3io.wp.database.connection import Connection
from l3io.wp.database.credentials import Explicit
from l3io.wp.database.inspection import inspect
from l3io.wp.database.state import ConnectionState


def test_unreachable_server_is_a_state_not_an_exception() -> None:
    state = inspect(Connection(host="127.0.0.1", database="wp", port=1), Explicit("u", "p"))
    assert state is ConnectionState.UNREACHABLE


class _Unobtainable:
    source = "broken"

    def resolve(self):  # type: ignore[no-untyped-def]
        from l3io.wp.database.errors import CredentialsUnobtainableError

        msg = "nope"
        raise CredentialsUnobtainableError(msg)


def test_unobtainable_credentials_are_a_state() -> None:
    state = inspect(Connection(host="127.0.0.1", database="wp", port=1), _Unobtainable())
    assert state is ConnectionState.CREDENTIALS_UNOBTAINABLE
