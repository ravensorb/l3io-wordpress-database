# tests/test_observability.py
"""Correlation by contextvars, one span per operation, timing on every completion."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import structlog
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from structlog.testing import LogCapture

from l3io.wp.database._observe import operation
from l3io.wp.database.connection import Connection
from l3io.wp.database.errors import RefusedError
from l3io.wp.database.verdict import Code, Finding, Verdict

CONN = Connection(host="127.0.0.1", database="wp_site", port=1)
_EXPORTER = InMemorySpanExporter()
_PROVIDER = TracerProvider()
_PROVIDER.add_span_processor(SimpleSpanProcessor(_EXPORTER))
trace.set_tracer_provider(_PROVIDER)


@pytest.fixture
def logs() -> Iterator[LogCapture]:
    capture = LogCapture()
    structlog.configure(processors=[structlog.contextvars.merge_contextvars, capture])
    yield capture
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()


@pytest.fixture(autouse=True)
def _spans() -> Iterator[None]:
    _EXPORTER.clear()
    yield


def test_bound_run_id_appears_on_the_completion_event(logs: LogCapture) -> None:
    structlog.contextvars.bind_contextvars(run_id="run-123")
    with operation("survey", CONN):
        pass
    [event] = [e for e in logs.entries if e["event"] == "operation complete"]
    assert event["run_id"] == "run-123"
    assert event["operation"] == "survey"
    assert event["outcome"] == "succeeded"
    assert isinstance(event["duration_ms"], float)


def test_fields_set_inside_the_block_are_reported(logs: LogCapture) -> None:
    with operation("ensure", CONN) as fields:
        fields["created_database"] = True
    assert logs.entries[-1]["created_database"] is True


def test_refusal_is_reported_with_codes(logs: LogCapture) -> None:
    verdict = Verdict("drop_database", (Finding(Code.CONFIRMATION_MISMATCH, "no"),))
    with pytest.raises(RefusedError), operation("drop_database", CONN):
        raise RefusedError(verdict)
    assert logs.entries[-1]["outcome"] == "refused"
    [span] = _EXPORTER.get_finished_spans()
    assert span.attributes is not None
    assert span.attributes["l3io.verdict.codes"] == ("confirmation_mismatch",)


def test_failure_is_reported_and_reraised(logs: LogCapture) -> None:
    with pytest.raises(ZeroDivisionError), operation("ensure", CONN):
        _ = 1 / 0
    assert logs.entries[-1]["outcome"] == "failed"
    [span] = _EXPORTER.get_finished_spans()
    assert span.status.status_code is trace.StatusCode.ERROR


def test_span_nests_under_the_callers_span() -> None:
    tracer = trace.get_tracer("caller")
    with tracer.start_as_current_span("phase"), operation("survey", CONN):
        pass
    spans = {s.name: s for s in _EXPORTER.get_finished_spans()}
    child, parent = spans["l3io.wp.database.survey"], spans["phase"]
    assert child.parent is not None
    assert child.parent.span_id == parent.context.span_id
    assert child.attributes is not None
    assert child.attributes["db.name"] == "wp_site"


# Expected logged value per reserved key; None means "any float" (duration_ms).
_RESERVED_VALUES: dict[str, str | None] = {
    "event": "operation complete",
    "operation": "drop_database",
    "outcome": "refused",
    "duration_ms": None,
    "database": "wp_site",
}


@pytest.mark.parametrize(
    "reserved",
    ["event", "operation", "outcome", "duration_ms", "database", "self", "method_name"],
)
def test_caller_field_named_like_a_reserved_key_cannot_mask_the_refusal(
    logs: LogCapture, reserved: str
) -> None:
    verdict = Verdict("drop_database", (Finding(Code.CONFIRMATION_MISMATCH, "no"),))
    with pytest.raises(RefusedError), operation("drop_database", CONN) as fields:
        fields[reserved] = "x"
        raise RefusedError(verdict)
    record = logs.entries[-1]
    if reserved in _RESERVED_VALUES:
        expected = _RESERVED_VALUES[reserved]
        if expected is None:
            assert isinstance(record[reserved], float)
        else:
            assert record[reserved] == expected
    else:
        assert record.get(reserved) != "x"
    assert record["outcome"] == "refused"


def test_caller_field_named_self_completes_on_the_success_path(logs: LogCapture) -> None:
    with operation("survey", CONN) as fields:
        fields["self"] = "x"
    record = logs.entries[-1]
    assert record["outcome"] == "succeeded"
    assert record.get("self") != "x"


def test_each_warning_is_logged_once_at_warning_level(logs: LogCapture) -> None:
    verdict = Verdict("drop_database", (Finding(Code.LIVE_WORDPRESS_SITE, "looks live"),))
    with operation("check_drop_database", CONN) as fields:
        fields["_verdict"] = verdict
    warnings = [e for e in logs.entries if e["log_level"] == "warning"]
    assert [(w["code"], w["operation"]) for w in warnings] == [
        ("live_wordpress_site", "check_drop_database")
    ]
    [done] = [e for e in logs.entries if e["event"] == "operation complete"]
    assert "_verdict" not in done


def test_a_refusal_logs_its_warnings_too(logs: LogCapture) -> None:
    verdict = Verdict(
        "drop_database",
        (Finding(Code.CONFIRMATION_MISMATCH, "no"), Finding(Code.LIVE_WORDPRESS_SITE, "live")),
    )
    with pytest.raises(RefusedError), operation("drop_database", CONN):
        raise RefusedError(verdict)
    assert [e["code"] for e in logs.entries if e["log_level"] == "warning"] == [
        "live_wordpress_site"
    ]


def test_server_family_is_recorded_on_the_span() -> None:
    from l3io.wp.database.server import detect_server

    class _Cursor:
        def execute(self, sql: str, args: object = None) -> None:
            pass

        def fetchone(self) -> tuple[str]:
            return ("11.4.5-MariaDB",)

    with operation("survey", CONN):
        detect_server(_Cursor())
    [span] = _EXPORTER.get_finished_spans()
    assert span.attributes is not None
    assert span.attributes["db.system"] == "mariadb"
