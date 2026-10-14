"""The transfer engine against fake client programs, so no server is needed.

Each fake is a shell script on PATH answering ``--version`` like a real tool.
The engine is exercised through its internals (_start, DumpStream, _pump_load)
because the public operations need a live server for their preflight.
"""

from __future__ import annotations

import dataclasses
import errno
import gc
import io
import os
import resource
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterable, Mapping
from contextlib import ExitStack
from pathlib import Path
from typing import IO, Any, cast

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from structlog.testing import capture_logs

from l3io.wp.database import _client, _observe, transfer
from l3io.wp.database.connection import Connection
from l3io.wp.database.credentials import Explicit, ResolvedCredentials
from l3io.wp.database.errors import (
    DecryptionError,
    InvalidArgumentsError,
    MissingDependencyError,
    RefusedError,
    TransferError,
)
from l3io.wp.database.server import ServerFamily, parse_version
from l3io.wp.database.verdict import Code, Finding, Verdict

CONN = Connection(host="127.0.0.1", database="wp_site", port=3306)
SECRET = "engine-secret-password"
CREDS = ResolvedCredentials("wpuser", SECRET)
SERVER = parse_version("8.4.11")


class _FailingWriter(io.BytesIO):
    def __init__(self, error: OSError) -> None:
        super().__init__()
        self.error = error

    def write(self, data: object) -> int:
        raise self.error


def _disk_full() -> OSError:
    return OSError(errno.ENOSPC, "No space left on device")


def fake(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, body: str
) -> _client.ClientTool:
    script = tmp_path / name
    script.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--version" ]; then echo "'
        + name
        + '  Ver 8.4.11 for Linux"; exit 0; fi\n'
        + body
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    tool = _client.find_tool(
        _client.PURPOSE_DUMP if "dump" in name else _client.PURPOSE_LOAD, SERVER.family
    )
    assert tool is not None
    return tool


def stream(tool: _client.ClientTool, recipients: list[str] | None = None) -> transfer.DumpStream:
    process = transfer._start(tool, ["wp_site"], CREDS, CONN, for_load=False)
    return transfer.DumpStream(
        process,
        tool=tool,
        server=SERVER,
        verdict=Verdict("dump"),
        recipients=recipients,
        password=SECRET,
    )


def test_dump_yields_the_tools_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tool = fake(tmp_path, monkeypatch, "mysqldump", 'echo "-- MySQL dump"; echo "SELECT 1;"\n')
    s = stream(tool)
    assert b"".join(s) == b"-- MySQL dump\nSELECT 1;\n"
    assert s.result is not None
    assert s.result.bytes == len(b"-- MySQL dump\nSELECT 1;\n")
    assert s.result.verdict == Verdict("dump")


def test_the_option_file_is_readable_and_never_echoed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Report only the size of what the defaults file holds, so the test can
    # prove the fd is readable without the password ever being printed.
    tool = fake(tmp_path, monkeypatch, "mysqldump", 'wc -c < "${1#--defaults-file=}"\n')
    out = b"".join(stream(tool))
    assert int(out.strip()) > 0
    assert SECRET.encode() not in out


def test_a_failing_tool_raises_at_the_end_not_silently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = fake(
        tmp_path,
        monkeypatch,
        "mysqldump",
        f'echo "partial"; echo "mysqldump: Got error: 1044 for {SECRET}" >&2; exit 2\n',
    )
    s = stream(tool)
    with pytest.raises(TransferError) as info:
        list(s)
    assert info.value.exit_code == 2
    assert "1044" in info.value.stderr
    assert SECRET not in info.value.stderr
    assert SECRET not in str(info.value)


def test_closing_early_kills_the_tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tool = fake(
        tmp_path,
        monkeypatch,
        "mysqldump",
        "while true; do echo 'INSERT INTO t VALUES (1);'; done\n",
    )
    s = stream(tool)
    next(s)
    pid = s.pid
    s.close()
    time.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def _exited(pid: int, within: float = 5.0) -> bool:
    """Whether ``pid`` is gone (killed and reaped, not a zombie) within ``within`` seconds."""
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


@pytest.mark.parametrize("encrypted", [False, True])
def test_a_dropped_stream_stops_the_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, encrypted: bool
) -> None:
    recipients = None
    if encrypted:
        pytest.importorskip("pyrage")
        from l3io.wp.database import encryption

        recipients = [encryption.generate_identity()[1]]
    tool = fake(
        tmp_path,
        monkeypatch,
        "mysqldump",
        "while true; do echo 'INSERT INTO t VALUES (1);'; done\n",
    )
    before = set(threading.enumerate())
    s = stream(tool, recipients)
    next(s)
    pid = s.pid
    threads = set(threading.enumerate()) - before
    assert len(threads) == (2 if encrypted else 1)  # stderr drain, and encryption
    del s
    gc.collect()
    assert _exited(pid), "the dump tool outlived its dropped stream"
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()


def test_large_stderr_does_not_deadlock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tool = fake(
        tmp_path,
        monkeypatch,
        "mysqldump",
        "i=0; while [ $i -lt 20000 ]; do\n"
        "  echo 'warning: something noisy happened here' >&2; i=$((i+1))\n"
        "done; exit 3\n",
    )
    s = stream(tool)
    with pytest.raises(TransferError) as info:
        list(s)
    assert info.value.exit_code == 3
    assert len(info.value.stderr) <= transfer.STDERR_CAP + 100


def test_dump_streams_in_bounded_chunks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tool = fake(tmp_path, monkeypatch, "mysqldump", "head -c 50000000 /dev/zero\n")
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    total = 0
    for chunk in stream(tool):
        assert len(chunk) <= transfer.CHUNK
        total += len(chunk)
    assert total == 50_000_000
    grown_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before
    assert grown_kib < 30_000


def test_a_killed_tool_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tool = fake(tmp_path, monkeypatch, "mysqldump", "while true; do echo 'x'; done\n")
    s = stream(tool)
    next(s)
    os.kill(s.pid, signal.SIGKILL)
    with pytest.raises(TransferError):
        list(s)


def test_dump_to_a_path_is_atomic_and_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = fake(tmp_path, monkeypatch, "mysqldump", 'echo "SELECT 1;"\n')
    target = tmp_path / "out" / "site.sql"
    target.parent.mkdir()
    transfer._write_atomically(stream(good), transfer._open_partial(target))
    assert target.read_bytes() == b"SELECT 1;\n"
    assert (target.stat().st_mode & 0o777) == 0o600


def test_a_failed_dump_leaves_no_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bad = fake(tmp_path, monkeypatch, "mysqldump", 'echo "partial"; exit 2\n')
    target = tmp_path / "site.sql"
    with pytest.raises(TransferError):
        transfer._write_atomically(stream(bad), transfer._open_partial(target))
    assert list(tmp_path.glob("*site.sql*")) == []


def test_encrypted_dump_round_trips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("pyrage")
    from l3io.wp.database import encryption

    identity, recipient = encryption.generate_identity()
    tool = fake(tmp_path, monkeypatch, "mysqldump", 'echo "SELECT 42;"\n')
    data = b"".join(stream(tool, recipients=[recipient]))
    assert data.startswith(encryption.AGE_HEADER)
    out = io.BytesIO()
    encryption.decrypt(io.BytesIO(data), out, [identity])
    assert out.getvalue() == b"SELECT 42;\n"


def test_an_unusable_recipient_fails_instead_of_hanging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Encryption fails before reading a byte; the tool's endless output must
    # not leave it, and the stream with it, blocked on a full pipe.
    pytest.importorskip("pyrage")
    tool = fake(tmp_path, monkeypatch, "mysqldump", "while true; do echo 'x'; done\n")
    with pytest.raises(TransferError) as info:
        list(stream(tool, recipients=["not-a-key"]))
    assert isinstance(info.value.__cause__, InvalidArgumentsError)
    assert str(info.value).startswith("dump failed: encryption: ")


def _completions(logs: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [e for e in logs if e.get("event") == "operation complete"]


def test_a_dump_operation_ends_when_its_stream_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = fake(tmp_path, monkeypatch, "mysqldump", 'echo "SELECT 1;"\n')
    monkeypatch.setattr(
        transfer, "_dump_plan", lambda *_: transfer._Plan(Verdict("dump"), CREDS, tool, SERVER)
    )
    with capture_logs() as logs:
        s = transfer.iter_dump(CONN, Explicit("wpuser", SECRET))
        assert _completions(logs) == []
        assert b"".join(s) == b"SELECT 1;\n"
    [event] = _completions(logs)
    assert event["outcome"] == "succeeded"
    assert event["bytes"] == len(b"SELECT 1;\n")
    assert SECRET not in repr(logs)


def test_dump_writes_to_a_stream(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tool = fake(tmp_path, monkeypatch, "mysqldump", 'echo "SELECT 1;"\n')
    monkeypatch.setattr(
        transfer, "_dump_plan", lambda *_: transfer._Plan(Verdict("dump"), CREDS, tool, SERVER)
    )
    out = io.BytesIO()
    result = transfer.dump(CONN, Explicit("wpuser", SECRET), out)
    assert out.getvalue() == b"SELECT 1;\n"
    assert result.bytes == len(b"SELECT 1;\n")
    assert result.tool == tool.label


def test_a_refused_dump_ends_its_operation_and_starts_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refused = Verdict("dump", (Finding(Code.DATABASE_ABSENT, "'wp_site' does not exist"),))
    monkeypatch.setattr(
        transfer, "_dump_plan", lambda *_: transfer._Plan(refused, CREDS, None, SERVER)
    )
    monkeypatch.setattr(transfer, "_start", lambda *_, **__: pytest.fail("started a dump"))
    with capture_logs() as logs, pytest.raises(RefusedError) as info:
        transfer.iter_dump(CONN, Explicit("wpuser", SECRET))
    assert info.value.verdict == refused
    [event] = _completions(logs)
    assert event["outcome"] == "refused"


def _planned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str
) -> tuple[_client.ClientTool, Path]:
    """A fake dump tool that leaves a marker file once it runs, planned as ready."""
    marker = tmp_path / "tool-ran"
    tool = fake(tmp_path, monkeypatch, "mysqldump", f': > "{marker}"\n{body}')
    monkeypatch.setattr(
        transfer, "_dump_plan", lambda *_: transfer._Plan(Verdict("dump"), CREDS, tool, SERVER)
    )
    return tool, marker


def _recording_start(monkeypatch: pytest.MonkeyPatch) -> list[subprocess.Popen[bytes]]:
    started: list[subprocess.Popen[bytes]] = []
    real = transfer._start

    def record(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        process = real(*args, **kwargs)
        started.append(process)
        return process

    monkeypatch.setattr(transfer, "_start", record)
    return started


@pytest.fixture
def spans(monkeypatch: pytest.MonkeyPatch) -> tuple[InMemorySpanExporter, trace.Tracer]:
    """The package's spans in memory, and a caller's tracer on the same provider."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(_observe, "_tracer", provider.get_tracer("l3io.wp.database"))
    return exporter, provider.get_tracer("caller")


def _finished(exporter: InMemorySpanExporter) -> dict[str, Any]:
    return {s.name: s for s in exporter.get_finished_spans()}


def test_a_dump_consumed_inside_another_span_leaves_the_callers_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spans: tuple[InMemorySpanExporter, trace.Tracer],
) -> None:
    exporter, tracer = spans
    _planned(tmp_path, monkeypatch, 'echo "SELECT 1;"\n')
    with tracer.start_as_current_span("job") as job:
        s = transfer.iter_dump(CONN, Explicit("wpuser", SECRET))
        assert trace.get_current_span() is job
        with tracer.start_as_current_span("upload"):
            assert b"".join(s) == b"SELECT 1;\n"
        assert trace.get_current_span() is job
    assert trace.get_current_span() is trace.INVALID_SPAN
    finished = _finished(exporter)
    dump, upload = finished["l3io.wp.database.dump"], finished["upload"]
    job_id = job.get_span_context().span_id
    assert dump.parent is not None
    assert dump.parent.span_id == job_id
    assert upload.parent is not None
    assert upload.parent.span_id == job_id
    assert dump.status.status_code is not trace.StatusCode.ERROR
    assert dump.attributes["db.name"] == "wp_site"


def test_a_dump_finished_on_another_thread_detaches_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spans: tuple[InMemorySpanExporter, trace.Tracer],
    caplog: pytest.LogCaptureFixture,
) -> None:
    exporter, _ = spans
    _planned(tmp_path, monkeypatch, 'echo "SELECT 1;"\n')
    s = transfer.iter_dump(CONN, Explicit("wpuser", SECRET))
    worker = threading.Thread(target=lambda: list(s))
    worker.start()
    worker.join(timeout=10)
    assert "detach" not in caplog.text
    assert trace.get_current_span() is trace.INVALID_SPAN
    assert "l3io.wp.database.dump" in _finished(exporter)


@pytest.mark.parametrize("how", ["close", "drop"])
def test_a_dump_stopped_early_fails_its_operation_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spans: tuple[InMemorySpanExporter, trace.Tracer],
    how: str,
) -> None:
    exporter, _ = spans
    _planned(tmp_path, monkeypatch, "while true; do echo 'INSERT INTO t VALUES (1);'; done\n")
    with capture_logs() as logs:
        s = transfer.iter_dump(CONN, Explicit("wpuser", SECRET))
        next(s)
        pid = s.pid
        if how == "close":
            s.close()
            s.close()
        else:
            del s
            gc.collect()
    assert _exited(pid)
    [event] = _completions(logs)
    assert event["outcome"] == "failed"
    assert event["bytes"] > 0
    [dump] = exporter.get_finished_spans()
    assert dump.status.status_code is trace.StatusCode.ERROR
    assert trace.get_current_span() is trace.INVALID_SPAN


def test_a_refused_dump_span_carries_its_codes(
    monkeypatch: pytest.MonkeyPatch, spans: tuple[InMemorySpanExporter, trace.Tracer]
) -> None:
    exporter, _ = spans
    refused = Verdict("dump", (Finding(Code.DATABASE_ABSENT, "'wp_site' does not exist"),))
    monkeypatch.setattr(
        transfer, "_dump_plan", lambda *_: transfer._Plan(refused, CREDS, None, SERVER)
    )
    with pytest.raises(RefusedError):
        transfer.iter_dump(CONN, Explicit("wpuser", SECRET))
    [dump] = exporter.get_finished_spans()
    assert dump.attributes is not None
    assert dump.attributes["l3io.verdict.codes"] == ("database_absent",)
    assert dump.status.status_code is trace.StatusCode.ERROR
    assert trace.get_current_span() is trace.INVALID_SPAN


@pytest.mark.parametrize("text_mode", ["stringio", "file"])
def test_a_text_target_is_refused_before_a_dump_begins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text_mode: str
) -> None:
    monkeypatch.setattr(transfer, "iter_dump", lambda *_, **__: pytest.fail("began a dump"))
    with ExitStack() as cleanup:
        target: Any = (
            io.StringIO()
            if text_mode == "stringio"
            else cleanup.enter_context(open(tmp_path / "out.sql", "w"))  # noqa: PTH123
        )
        with pytest.raises(InvalidArgumentsError, match="binary stream"):
            transfer.dump(CONN, Explicit("wpuser", SECRET), target)


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (io.StringIO("-- MySQL dump\n"), "binary stream"),
        (iter(["-- MySQL dump\n"]), "must yield bytes, not str"),
    ],
    ids=["text-stream", "iterable-of-str"],
)
def test_a_text_source_is_refused_before_a_load_begins(
    monkeypatch: pytest.MonkeyPatch, source: Any, message: str
) -> None:
    monkeypatch.setattr(transfer, "_load_plan", lambda *_, **__: pytest.fail("planned a load"))
    monkeypatch.setattr(transfer, "_start", lambda *_, **__: pytest.fail("started a load"))
    with pytest.raises(InvalidArgumentsError, match=message):
        transfer.load(CONN, Explicit("wpuser", SECRET), source)


def test_a_path_in_a_missing_directory_starts_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, marker = _planned(tmp_path, monkeypatch, 'echo "SELECT 1;"\n')
    target = tmp_path / "missing" / "site.sql"
    with pytest.raises(InvalidArgumentsError) as info:
        transfer.dump(CONN, Explicit("wpuser", SECRET), target)
    assert str(target) in str(info.value)
    assert isinstance(info.value.__cause__, FileNotFoundError)
    time.sleep(0.2)
    assert not marker.exists()


def test_a_tool_that_cannot_start_is_a_transfer_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = fake(tmp_path, monkeypatch, "mysqldump", 'echo "SELECT 1;"\n')
    gone = dataclasses.replace(tool, path=str(tmp_path / "removed-after-discovery"))
    monkeypatch.setattr(
        transfer, "_dump_plan", lambda *_: transfer._Plan(Verdict("dump"), CREDS, gone, SERVER)
    )
    with capture_logs() as logs, pytest.raises(TransferError) as info:
        transfer.iter_dump(CONN, Explicit("wpuser", SECRET))
    assert isinstance(info.value.__cause__, FileNotFoundError)
    [event] = _completions(logs)
    assert event["outcome"] == "failed"


def test_a_failing_stream_target_is_a_transfer_error_and_reaps_the_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _planned(tmp_path, monkeypatch, "while true; do echo 'INSERT INTO t VALUES (1);'; done\n")
    started = _recording_start(monkeypatch)
    with pytest.raises(TransferError) as info:
        transfer.dump(CONN, Explicit("wpuser", SECRET), _FailingWriter(_disk_full()))
    assert isinstance(info.value.__cause__, OSError)
    assert info.value.__cause__.errno == errno.ENOSPC
    [process] = started
    assert process.returncode is not None
    with pytest.raises(ProcessLookupError):
        os.kill(process.pid, 0)


class _UnflushableWriter:
    """Accepts every write, then fails to flush: the last chunk never lands."""

    def __init__(self) -> None:
        self.written = bytearray()

    def write(self, data: bytes) -> int:
        self.written += data
        return len(data)

    def flush(self) -> None:
        raise _disk_full()


def test_a_stream_target_that_cannot_flush_is_a_transfer_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _planned(tmp_path, monkeypatch, 'echo "SELECT 1;"\n')
    started = _recording_start(monkeypatch)
    target = _UnflushableWriter()
    with pytest.raises(TransferError) as info:
        transfer.dump(CONN, Explicit("wpuser", SECRET), cast(IO[bytes], target))
    assert bytes(target.written) == b"SELECT 1;\n"
    assert isinstance(info.value.__cause__, OSError)
    assert info.value.__cause__.errno == errno.ENOSPC
    [process] = started
    assert process.returncode is not None


def test_a_failing_path_target_is_a_transfer_error_and_leaves_no_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _planned(tmp_path, monkeypatch, 'echo "SELECT 1;"\n')
    started = _recording_start(monkeypatch)
    out = tmp_path / "out"
    out.mkdir()

    def full(fd: int) -> None:
        raise _disk_full()

    monkeypatch.setattr(os, "fsync", full)
    with pytest.raises(TransferError) as info:
        transfer.dump(CONN, Explicit("wpuser", SECRET), out / "site.sql")
    assert isinstance(info.value.__cause__, OSError)
    assert info.value.__cause__.errno == errno.ENOSPC
    assert list(out.iterdir()) == []
    [process] = started
    assert process.returncode is not None


def test_a_bad_recipient_is_refused_before_the_tool_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("pyrage")
    _, marker = _planned(tmp_path, monkeypatch, 'echo "SELECT 1;"\n')
    with pytest.raises(InvalidArgumentsError):
        transfer.iter_dump(CONN, Explicit("wpuser", SECRET), recipients=["not-a-key"])
    time.sleep(0.2)
    assert not marker.exists()


def test_a_missing_encryption_extra_is_named_before_the_tool_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, marker = _planned(tmp_path, monkeypatch, 'echo "SELECT 1;"\n')
    monkeypatch.setitem(sys.modules, "pyrage", None)
    with pytest.raises(MissingDependencyError) as info:
        transfer.iter_dump(CONN, Explicit("wpuser", SECRET), recipients=["age1whatever"])
    assert info.value.extra == "encryption"
    time.sleep(0.2)
    assert not marker.exists()


@pytest.mark.parametrize(
    ("head", "family", "sandboxed"),
    [
        (
            b"-- MySQL dump 10.13  Distrib 8.4.11, for Linux (x86_64)\n--\n",
            ServerFamily.MYSQL,
            False,
        ),
        (
            b"-- MySQL dump 10.19  Distrib 10.2.44-MariaDB, for debian\n",
            ServerFamily.MARIADB,
            False,
        ),
        (
            b"/*M!999999\\- enable the sandbox mode */ \n-- MariaDB dump 10.19-11.4.13-MariaDB\n",
            ServerFamily.MARIADB,
            True,
        ),
        (
            b"-- MySQL dump 10.13  Distrib 8.4.11, for Linux (x86_64)\n--\n"
            b"-- Host: 127.0.0.1    Database: d\n"
            b"-- ------------------------------------------------------\n"
            b"-- Server version\t8.4.11\n\n",
            ServerFamily.MYSQL,
            False,
        ),
        (
            b"-- MySQL dump 10.13  Distrib 8.4.11, for Linux (x86_64)\n--\n"
            b"-- Host: 127.0.0.1    Database: d\n"
            b"-- ------------------------------------------------------\n"
            b"-- Server version\t11.4.13-MariaDB-ubu2404\n\n",
            ServerFamily.MARIADB,
            False,
        ),
        (
            b"/*M!999999\\- enable the sandbox mode */ \n"
            b"-- MariaDB dump 10.19-11.4.13-MariaDB, for debian-linux-gnu (x86_64)\n--\n"
            b"-- Host: 127.0.0.1    Database: d\n"
            b"-- ------------------------------------------------------\n"
            b"-- Server version\t8.4.11\n\n",
            ServerFamily.MYSQL,
            True,
        ),
        (b"-- Server version\t11.4.13-MariaDB\nCREATE TABLE t (x INT);\n", None, False),
        (b"CREATE TABLE t (x INT);\n", None, False),
        (b"", None, False),
    ],
    ids=[
        "mysql-banner",
        "old-mariadb-banner",
        "mariadb-banner-sandboxed",
        "mysql-tool-mysql-server",
        "mysql-tool-mariadb-server",
        "mariadb-tool-mysql-server",
        "server-line-without-banner",
        "not-a-dump",
        "empty",
    ],
)
def test_header_detection(head: bytes, family: ServerFamily | None, sandboxed: bool) -> None:
    header = transfer._header(head, encrypted=False)
    assert (header.family, header.sandboxed) == (family, sandboxed)


def loader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> subprocess.Popen[bytes]:
    tool = fake(tmp_path, monkeypatch, "mysql", body)
    return transfer._start(tool, ["--database=wp_site"], CREDS, CONN, for_load=True)


def test_load_feeds_everything_to_the_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    received = tmp_path / "received"
    process = loader(tmp_path, monkeypatch, f"cat > {received}\n")
    count = transfer._pump_load(
        process, b"SELECT 1;\n", io.BytesIO(b"SELECT 2;\n"), password=SECRET
    )
    assert count == 20
    assert received.read_bytes() == b"SELECT 1;\nSELECT 2;\n"


def test_empty_source_loads_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    process = loader(tmp_path, monkeypatch, "cat > /dev/null\n")
    assert transfer._pump_load(process, b"", io.BytesIO(b""), password=SECRET) == 0


def test_a_failing_client_raises_transfer_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    process = loader(
        tmp_path,
        monkeypatch,
        'cat > /dev/null; echo "ERROR 1273 at line 26: Unknown collation" >&2; exit 1\n',
    )
    with pytest.raises(TransferError) as info:
        transfer._pump_load(process, b"SELECT 1;\n", io.BytesIO(b""), password=SECRET)
    assert info.value.exit_code == 1
    assert "Unknown collation" in info.value.stderr


def test_a_client_that_dies_early_does_not_hang(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    process = loader(tmp_path, monkeypatch, "exit 4\n")
    big = io.BytesIO(b"x" * 10_000_000)
    with pytest.raises(TransferError) as info:
        transfer._pump_load(process, b"", big, password=SECRET)
    assert info.value.exit_code == 4


class _CountingReader(io.BytesIO):
    """Records how much of the source the engine pulled."""

    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.pulled = 0

    def read(self, size: int | None = -1) -> bytes:
        block = super().read(size)
        self.pulled += len(block)
        return block


def test_load_streams_instead_of_reading_the_source_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    process = loader(tmp_path, monkeypatch, "head -c 1 > /dev/null; exit 4\n")
    source = _CountingReader(b"x" * 50_000_000)
    with pytest.raises(TransferError):
        transfer._pump_load(process, b"", source, password=SECRET)
    assert source.pulled < 5_000_000


def test_iterable_and_stream_sources_are_read_alike() -> None:
    reader = transfer._as_reader([b"ab", b"", b"cd"])
    assert reader.read(3) + reader.read(10) == b"abcd"


def _load_planned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str, **tool_changes: Any
) -> Verdict:
    """A fake load client, planned as ready; returns the plan's verdict."""
    tool = dataclasses.replace(fake(tmp_path, monkeypatch, "mysql", body), **tool_changes)
    verdict = Verdict("load", (Finding(Code.CROSS_FAMILY_DUMP, "planned"),))
    monkeypatch.setattr(
        transfer,
        "_load_plan",
        lambda *_, **__: transfer._Plan(verdict, CREDS, tool, SERVER),
    )
    return verdict


def _sealed(size: int) -> tuple[bytes, str]:
    """``size`` bytes of plaintext, age-encrypted: (ciphertext, identity)."""
    from l3io.wp.database import encryption

    identity, recipient = encryption.generate_identity()
    out = io.BytesIO()
    encryption.encrypt(io.BytesIO(b"x" * size), out, [recipient])
    return out.getvalue(), identity


def test_an_encrypted_load_into_a_client_that_exits_early_does_not_hang(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("pyrage")
    _load_planned(tmp_path, monkeypatch, "head -c 100 > /dev/null; exit 5\n")
    sealed, identity = _sealed(8 * 1024 * 1024)
    outcome: list[BaseException] = []

    def run() -> None:
        try:
            transfer.load(
                CONN, Explicit("wpuser", SECRET), io.BytesIO(sealed), identities=[identity]
            )
        except BaseException as exc:  # noqa: BLE001 - inspected on the test's thread
            outcome.append(exc)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout=20)
    assert not worker.is_alive(), "load hung after the client exited"
    [error] = outcome
    assert isinstance(error, TransferError)
    assert error.exit_code == 5


def test_an_unopenable_path_source_starts_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(transfer, "_load_plan", lambda *_, **__: pytest.fail("planned a load"))
    monkeypatch.setattr(transfer, "_start", lambda *_, **__: pytest.fail("started a load"))
    missing = tmp_path / "missing.sql"
    with pytest.raises(InvalidArgumentsError) as info:
        transfer.load(CONN, Explicit("wpuser", SECRET), missing)
    assert str(missing) in str(info.value)
    assert "No such file or directory" in str(info.value)
    assert isinstance(info.value.__cause__, FileNotFoundError)


@pytest.mark.parametrize("make_source", [io.BytesIO, lambda data: iter([data])])
def test_check_load_refuses_a_stream_source_without_reading_it(
    monkeypatch: pytest.MonkeyPatch, make_source: Any
) -> None:
    monkeypatch.setattr(transfer, "_load_plan", lambda *_, **__: pytest.fail("planned a load"))
    monkeypatch.setattr(transfer, "_prepare", lambda *_, **__: pytest.fail("read the source"))
    source = make_source(b"-- MySQL dump 10.13\n")
    with pytest.raises(InvalidArgumentsError, match="only as a path") as info:
        transfer.check_load(CONN, Explicit("wpuser", SECRET), source=source)
    assert SECRET not in str(info.value)
    if isinstance(source, io.BytesIO):
        assert source.tell() == 0


class _FailingReader(io.RawIOBase):
    """Serves ``data`` up to ``limit`` bytes, then fails like a dying disk."""

    def __init__(self, data: bytes, limit: int) -> None:
        self._data = data
        self._limit = limit
        self._pos = 0

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        if self._pos >= self._limit:
            raise OSError(errno.EIO, "Input/output error")
        size = min(len(buffer), self._limit - self._pos, len(self._data) - self._pos)
        buffer[:size] = self._data[self._pos : self._pos + size]
        self._pos += size
        return size


@pytest.mark.parametrize("encrypted", [False, True])
def test_a_source_failing_mid_stream_is_a_transfer_error_and_reaps_the_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, encrypted: bool
) -> None:
    verdict = _load_planned(tmp_path, monkeypatch, "cat > /dev/null\n")
    started = _recording_start(monkeypatch)
    identities = None
    data = b"x" * 1_000_000
    if encrypted:
        pytest.importorskip("pyrage")
        data, identity = _sealed(len(data))
        identities = [identity]
    source = io.BufferedReader(_FailingReader(data, 300_000))
    with pytest.raises(TransferError) as info:
        transfer.load(CONN, Explicit("wpuser", SECRET), source, identities=identities)
    assert isinstance(info.value.__cause__, OSError)
    assert info.value.__cause__.errno == errno.EIO
    assert info.value.verdict == verdict
    assert info.value.exit_code is None
    [process] = started
    assert process.returncode == -signal.SIGKILL


def test_an_iterable_source_failing_mid_stream_kills_the_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _load_planned(tmp_path, monkeypatch, "cat > /dev/null\n")
    started = _recording_start(monkeypatch)

    def chunks() -> Iterable[bytes]:
        yield b"x" * 100_000
        yield b"y" * 100_000
        msg = "the upstream connection dropped"
        raise RuntimeError(msg)

    with pytest.raises(RuntimeError, match="upstream connection dropped"):
        transfer.load(CONN, Explicit("wpuser", SECRET), chunks())
    [process] = started
    assert process.returncode == -signal.SIGKILL


def test_one_large_chunk_is_read_in_linear_time() -> None:
    size = 64 * 1024 * 1024
    reader = transfer._as_reader([b"x" * size])
    began = time.monotonic()
    total = sum(len(block) for block in iter(lambda: reader.read(transfer.CHUNK), b""))
    assert total == size
    assert time.monotonic() - began < 5


def test_a_wrong_identity_loads_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("pyrage")
    from l3io.wp.database import encryption

    monkeypatch.setattr(transfer, "_load_plan", lambda *_, **__: pytest.fail("planned a load"))
    monkeypatch.setattr(transfer, "_start", lambda *_, **__: pytest.fail("started a load"))
    sealed, _ = _sealed(1000)
    other, _ = encryption.generate_identity()
    with pytest.raises(DecryptionError):
        transfer.load(CONN, Explicit("wpuser", SECRET), io.BytesIO(sealed), identities=[other])


SANDBOXED = (
    b"/*M!999999\\- enable the sandbox mode */\n-- MariaDB dump 10.19-11.4.13-MariaDB\nSELECT 1;\n"
)


@pytest.mark.parametrize(
    ("tool_changes", "expected"),
    [
        (
            {"family": ServerFamily.MARIADB, "version": (10, 2, 44)},
            SANDBOXED.split(b"\n", 1)[1],
        ),
        ({}, SANDBOXED),
    ],
    ids=["old-mariadb-client-strips", "mysql-client-keeps"],
)
def test_load_strips_the_sandbox_line_only_for_a_client_that_cannot_read_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool_changes: dict[str, Any],
    expected: bytes,
) -> None:
    received = tmp_path / "received"
    _load_planned(tmp_path, monkeypatch, f"cat > {received}\n", **tool_changes)
    result = transfer.load(CONN, Explicit("wpuser", SECRET), io.BytesIO(SANDBOXED))
    assert received.read_bytes() == expected
    assert result.bytes == len(expected)


def test_loading_an_empty_source_succeeds_with_nothing_delivered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _load_planned(tmp_path, monkeypatch, "cat > /dev/null\n")
    result = transfer.load(CONN, Explicit("wpuser", SECRET), io.BytesIO(b""))
    assert result.bytes == 0


class _Trickle(io.RawIOBase):
    """An unbuffered stream that returns at most three bytes per read."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        block, self._data = self._data[:3], self._data[3:]
        return block


def _trickle(data: bytes) -> IO[bytes]:
    return cast("IO[bytes]", _Trickle(data))


def test_the_header_is_detected_through_short_reads() -> None:
    from l3io.wp.database import encryption

    with ExitStack() as cleanup:
        age, *_ = transfer._prepare(_trickle(encryption.AGE_HEADER + b"\n-> X25519"), None, cleanup)
        sandbox, *_ = transfer._prepare(_trickle(SANDBOXED), None, cleanup)
    assert age.encrypted
    assert age.needs_identity
    assert sandbox.sandboxed
    assert sandbox.family is ServerFamily.MARIADB


def test_no_client_tool_is_a_blocker_naming_those_tried(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_client, "find_tool", lambda purpose, family: None)
    server = parse_version("8.4.6")
    tool, findings = transfer._tool_findings(_client.PURPOSE_DUMP, server)
    assert tool is None
    [finding] = findings
    assert finding.code is Code.CLIENT_TOOL_MISSING
    assert finding.fields["tools"] == ", ".join(
        _client.candidates(_client.PURPOSE_DUMP, server.family)
    )


def test_a_tool_from_the_other_family_or_older_is_skew(monkeypatch: pytest.MonkeyPatch) -> None:
    for family, version in ((ServerFamily.MARIADB, (11, 4, 13)), (ServerFamily.MYSQL, (8, 0, 40))):
        tool = _client.ClientTool(
            "mysqldump", "/usr/bin/mysqldump", family, version, ".".join(map(str, version))
        )
        monkeypatch.setattr(_client, "find_tool", lambda purpose, fam, tool=tool: tool)
        found, findings = transfer._tool_findings(_client.PURPOSE_DUMP, parse_version("8.4.6"))
        assert found is tool
        assert [f.code for f in findings] == [Code.CLIENT_SERVER_SKEW]


def test_a_matching_tool_has_no_findings(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = _client.ClientTool(
        "mysqldump", "/usr/bin/mysqldump", ServerFamily.MYSQL, (8, 4, 6), "8.4.6"
    )
    monkeypatch.setattr(_client, "find_tool", lambda purpose, family: tool)
    assert transfer._tool_findings(_client.PURPOSE_DUMP, parse_version("8.4.6")) == (tool, [])


def test_no_dev_fd_is_a_blocker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(transfer, "DEV_FD", tmp_path / "absent")
    findings = transfer._platform_and_option_findings((), _client.DUMP_OPTIONS)
    assert [f.code for f in findings] == [Code.PLATFORM_UNSUPPORTED]
