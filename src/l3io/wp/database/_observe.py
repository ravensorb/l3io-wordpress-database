"""One span, one timed completion event, per public operation. Internal.

The package never configures logging. A caller that binds a Run ID with
``structlog.contextvars`` sees it here because the caller's processor chain
merges it, not because this module does anything.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

import structlog
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from .connection import Connection
from .errors import RefusedError
from .verdict import Verdict

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
            fields[VERDICT_KEY] = exc.verdict
            _complete(name, connection, "refused", started, fields)
            raise
        except BaseException:
            _complete(name, connection, "failed", started, fields)
            raise
        _complete(name, connection, "succeeded", started, fields)


class Running:
    """A public operation that outlives the call that began it, as a dump's stream does.

    Its span is current only inside :meth:`current` and while :meth:`end` logs,
    never across calls, so ending it from any thread or a finalizer leaves every
    context as it was. Only the first :meth:`end` counts. Span, attributes,
    completion event and outcomes are those of :func:`operation`.
    """

    def __init__(self, name: str, connection: Connection) -> None:
        self.fields: dict[str, object] = {}
        self._name = name
        self._connection = connection
        self._started = time.monotonic()
        self._lock = threading.Lock()
        self._ended = False
        self._span = _tracer.start_span(f"l3io.wp.database.{name}")
        self._span.set_attribute("db.name", connection.database)
        self._span.set_attribute("server.address", connection.host)
        self._span.set_attribute("server.port", connection.port)

    @contextmanager
    def current(self) -> Iterator[dict[str, object]]:
        """Make the span current for a block on the calling thread."""
        with trace.use_span(
            self._span, end_on_exit=False, record_exception=False, set_status_on_exception=False
        ):
            yield self.fields

    def end(self, error: BaseException | None) -> None:
        """Complete the operation: succeeded, or refused or failed by ``error``."""
        with self._lock:
            if self._ended:
                return
            self._ended = True
        span = self._span
        if isinstance(error, RefusedError):
            span.set_attribute("l3io.verdict.codes", [str(f.code) for f in error.verdict.blockers])
            self.fields[VERDICT_KEY] = error.verdict
        if isinstance(error, Exception):
            span.record_exception(error)
            span.set_status(Status(StatusCode.ERROR, f"{type(error).__name__}: {error}"))
        outcome = (
            "succeeded"
            if error is None
            else "refused"
            if isinstance(error, RefusedError)
            else "failed"
        )
        try:
            # Current only for the event itself, so a caller's log processor sees this span.
            with trace.use_span(
                span, end_on_exit=False, record_exception=False, set_status_on_exception=False
            ):
                _complete(self._name, self._connection, outcome, self._started, self.fields)
        finally:
            span.end()


#: An operation puts its Verdict in the yielded dict under this key, so the
#: warnings it found are logged once, at WARNING level, however it ends (§6).
VERDICT_KEY = "_verdict"

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
    verdict = fields.pop(VERDICT_KEY, None)
    if isinstance(verdict, Verdict):
        for finding in verdict.warnings:
            _log.warning(
                event=finding.message,
                code=str(finding.code),
                operation=name,
                database=connection.database,
            )
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
