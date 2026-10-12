"""One span, one timed completion event, per public operation. Internal.

The package never configures logging. A caller that binds a Run ID with
``structlog.contextvars`` sees it here because the caller's processor chain
merges it, not because this module does anything.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

import structlog
from opentelemetry import trace

from .connection import Connection
from .errors import RefusedError

_log = structlog.get_logger("l3io.wp.database")
_tracer = trace.get_tracer("l3io.wp.database")


@contextmanager
def operation(name: str, connection: Connection) -> Iterator[dict[str, object]]:
    """Wrap one public operation in a span and a completion event."""
    fields: dict[str, object] = {}
    started = time.monotonic()
    with _tracer.start_as_current_span(f"l3io.wp.database.{name}") as span:
        span.set_attribute("db.name", connection.database)
        span.set_attribute("server.address", connection.host)
        span.set_attribute("server.port", connection.port)
        try:
            yield fields
        except RefusedError as exc:
            span.set_attribute("l3io.verdict.codes", [str(f.code) for f in exc.verdict.blockers])
            _complete(name, connection, "refused", started, fields)
            raise
        except BaseException:
            _complete(name, connection, "failed", started, fields)
            raise
        _complete(name, connection, "succeeded", started, fields)


#: Parameter names of structlog's call chain (BoundLogger method and _proxy_to_logger).
#: A caller field with one of these names would collide when passed as a keyword.
_STRUCTLOG_PARAMETERS = frozenset({"self", "method_name"})


def _complete(
    name: str, connection: Connection, outcome: str, started: float, fields: dict[str, object]
) -> None:
    # One dict, reserved keys written last: a caller field with a colliding name
    # must never raise here, because this runs inside the exception handlers.
    # The event name is structlog's first positional parameter, so it travels as a
    # keyword too; otherwise a caller field named "event" collides with it.
    caller_fields = {k: v for k, v in fields.items() if k not in _STRUCTLOG_PARAMETERS}
    event: dict[str, object] = {
        **caller_fields,
        "event": "operation complete",
        "operation": name,
        "outcome": outcome,
        "duration_ms": round((time.monotonic() - started) * 1000, 1),
        "database": connection.database,
    }
    _log.info(**event)
