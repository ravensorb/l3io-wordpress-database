"""Export and import against a real server with that server's own client tools.

Runs only inside `make test-transfer ENGINE=<image>` (L3IO_TRANSFER_CONTAINER).
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path

import pymysql
import pytest

from l3io.wp.database import Connection, Explicit, _client, ensure
from l3io.wp.database.credentials import ResolvedCredentials
from l3io.wp.database.errors import CorruptDumpError, DecryptionError, RefusedError, TransferError
from l3io.wp.database.server import ServerFamily
from l3io.wp.database.transfer import check_dump, check_load, dump, iter_dump, load
from l3io.wp.database.verdict import Code

pytestmark = [
    pytest.mark.transfer,
    pytest.mark.skipif(
        not os.environ.get("L3IO_TRANSFER_CONTAINER"), reason="runs inside make test-transfer"
    ),
]

HOST = os.environ.get("DB_HOST", "127.0.0.1")
PORT = int(os.environ.get("DB_PORT", "3306"))
ENGINE = os.environ.get("L3IO_ENGINE", "")
ROOT = Explicit("root", os.environ.get("DB_ADMIN_PASSWORD", "root"))


def sql(*statements: str, database: str | None = None) -> list[tuple[object, ...]]:
    conn = pymysql.connect(
        host=HOST, port=PORT, user="root", password="root", database=database, charset="utf8mb4"
    )
    rows: list[tuple[object, ...]] = []
    with conn, conn.cursor() as cur:
        for statement in statements:
            cur.execute(statement)
            rows = list(cur.fetchall())
        conn.commit()
    return rows


@pytest.fixture
def names() -> Iterator[tuple[str, str]]:
    token = uuid.uuid4().hex[:8]
    source, target = f"src_{token}", f"dst_{token}"
    sql(
        f"CREATE DATABASE `{source}` CHARACTER SET utf8mb4",
        f"CREATE DATABASE `{target}` CHARACTER SET utf8mb4",
        f"CREATE TABLE `{source}`.`wp_options` (option_id INT PRIMARY KEY, "
        "option_name VARCHAR(191), option_value LONGBLOB, note VARCHAR(50) CHARACTER SET utf8mb4)",
        f"INSERT INTO `{source}`.`wp_options` VALUES (1, 'db_version', UNHEX('00FF10E2'), 'héllo 🐬')",  # noqa: S608, E501
    )
    yield source, target
    sql(
        f"DROP DATABASE IF EXISTS `{source}`",
        f"DROP DATABASE IF EXISTS `{target}`",
        f"DROP USER IF EXISTS 'u_{token}'@'%'",
    )


def bulk(database: str) -> None:
    """1,000 rows of 2 KB, so a dump is still running after its first chunk."""
    digits = " UNION ALL ".join(f"SELECT {d} AS d" for d in range(10))
    sql(
        f"INSERT INTO `{database}`.`wp_options` "  # noqa: S608 - test fixture
        "SELECT 2 + a.d * 100 + b.d * 10 + c.d, 'bulk', REPEAT('y', 2000), 'z' "
        f"FROM ({digits}) a, ({digits}) b, ({digits}) c"
    )


def checksum(database: str) -> object:
    return sql(f"CHECKSUM TABLE `{database}`.`wp_options`")[0][1]


def site(name: str) -> Connection:
    return Connection(host=HOST, port=PORT, database=name)


def test_round_trip_into_a_differently_named_database(
    names: tuple[str, str], tmp_path: Path
) -> None:
    source, target = names
    path = tmp_path / "site.sql"
    result = dump(site(source), ROOT, path)
    assert result.bytes == path.stat().st_size > 0
    assert b"CREATE DATABASE" not in path.read_bytes()
    load(site(target), ROOT, path)
    assert checksum(target) == checksum(source)


def test_stream_and_iterator_forms(names: tuple[str, str]) -> None:
    source, target = names
    buffer = io.BytesIO()
    dump(site(source), ROOT, buffer)
    chunks = list(iter_dump(site(source), ROOT))
    assert b"".join(chunks).count(b"INSERT INTO") == buffer.getvalue().count(b"INSERT INTO")
    load(site(target), ROOT, iter(chunks))
    assert checksum(target) == checksum(source)


def test_dump_of_an_absent_database_is_refused() -> None:
    with pytest.raises(RefusedError) as info:
        dump(site("no_such_db_x"), ROOT, io.BytesIO())
    assert Code.DATABASE_ABSENT in info.value.verdict.codes


def test_load_into_a_non_empty_database_needs_replace(names: tuple[str, str]) -> None:
    source, target = names
    data = io.BytesIO()
    dump(site(source), ROOT, data)
    with pytest.raises(RefusedError) as info:
        load(site(source), ROOT, io.BytesIO(data.getvalue()))
    assert Code.DATABASE_NOT_EMPTY in info.value.verdict.codes
    with pytest.raises(RefusedError) as info:
        load(site(source), ROOT, io.BytesIO(data.getvalue()), replace=target)
    assert Code.CONFIRMATION_MISMATCH in info.value.verdict.codes
    before = checksum(source)
    sql(f"INSERT INTO `{source}`.`wp_options` VALUES (99, 'stale', NULL, NULL)")  # noqa: S608
    assert checksum(source) != before
    load(site(source), ROOT, io.BytesIO(data.getvalue()), replace=source)
    assert checksum(source) == before


def test_a_disallowed_option_is_refused(names: tuple[str, str]) -> None:
    verdict = check_dump(site(names[0]), ROOT, options=["--result-file=/tmp/x"])
    assert Code.OPTION_NOT_ALLOWED in verdict.codes


def test_views_and_triggers_are_warned_about(names: tuple[str, str]) -> None:
    source, _ = names
    sql(f"CREATE VIEW `{source}`.`v` AS SELECT option_id FROM `{source}`.`wp_options`")  # noqa: S608
    verdict = check_dump(site(source), ROOT)
    assert verdict.ok
    assert Code.STORED_OBJECTS_PRESENT in verdict.codes


def test_cross_family_source_is_warned_about(names: tuple[str, str], tmp_path: Path) -> None:
    other = (
        b"-- MariaDB dump 10.19-11.4.13-MariaDB, for debian-linux-gnu (x86_64)\n"
        if not ENGINE.startswith("mariadb")
        else b"-- MySQL dump 10.13  Distrib 8.4.11, for Linux (x86_64)\n"
    )
    path = tmp_path / "other.sql"
    path.write_bytes(other + b"SELECT 1;\n")
    verdict = check_load(site(names[1]), ROOT, source=path)
    assert Code.CROSS_FAMILY_DUMP in verdict.codes


def test_sandbox_line_against_this_client(names: tuple[str, str], tmp_path: Path) -> None:
    """Only MariaDB 10.2's client in the matrix cannot read the sandbox line (V1)."""
    path = tmp_path / "sandboxed.sql"
    path.write_bytes(b"/*M!999999\\- enable the sandbox mode */ \nSELECT 1;\n")
    verdict = check_load(site(names[1]), ROOT, source=path)
    expected = ENGINE == "mariadb:10.2"
    assert (Code.INCOMPATIBLE_DUMP_SOURCE in verdict.codes) is expected
    if expected:
        load(site(names[1]), ROOT, path, allow_unsandboxed=True)
    else:
        load(site(names[1]), ROOT, path)


SECRET = "transfer-only-secret-value"


def wordpress_site(name: str, password: str) -> tuple[Connection, Explicit]:
    user = f"u_{name[-8:]}"
    wp = Explicit(user, password)
    ensure(site(name), ROOT, wp)
    return site(name), wp


def test_no_password_in_argv_environment_or_temp_files(names: tuple[str, str]) -> None:
    conn, wp = wordpress_site(names[0], SECRET)
    bulk(names[0])
    temp = Path(tempfile.gettempdir())
    before = set(temp.iterdir())
    stream = iter_dump(conn, wp)
    first = next(stream)
    cmdline = Path(f"/proc/{stream.pid}/cmdline").read_bytes()
    environ = Path(f"/proc/{stream.pid}/environ").read_bytes()
    options = re.search(rb"--defaults-file=/dev/fd/(\d+)\x00", cmdline)
    assert options is not None
    options_target = str(Path(f"/proc/{stream.pid}/fd/{int(options[1])}").readlink())
    rest = b"".join(stream)
    assert first and rest is not None
    assert options_target.startswith("pipe:")
    assert SECRET.encode() not in cmdline
    assert SECRET.encode() not in environ
    assert b"MYSQL_PWD" not in environ
    assert set(temp.iterdir()) == before


def plant_hostile_home(home: Path, *, my_cnf: bool = True) -> None:
    """A login file for user ``nobody`` (MySQL only) and, optionally, a hostile ``.my.cnf``."""
    login = home / ".mylogin.cnf"
    shutil.copyfile(Path(__file__).parent / "fixtures" / "hostile.mylogin.cnf", login)
    login.chmod(0o600)
    if my_cnf:
        (home / ".my.cnf").write_text("[client]\nuser=nobody\npassword=wrong\nhost=10.255.255.1\n")


def test_hostile_my_cnf_and_mylogin_cnf_change_nothing(
    names: tuple[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plant_hostile_home(tmp_path)
    real_env = _client.child_env
    monkeypatch.setattr(_client, "child_env", lambda: {**real_env(), "HOME": str(tmp_path)})
    result = dump(site(names[0]), ROOT, io.BytesIO())
    assert result.bytes > 0


def test_the_planted_login_file_is_read_without_suppression(tmp_path: Path) -> None:
    """The control for the test above: without suppression the client takes user nobody."""
    if ENGINE.startswith("mariadb"):
        pytest.skip("MariaDB clients have no login-path file to suppress")
    plant_hostile_home(tmp_path, my_cnf=False)
    tool = _client.find_tool(_client.PURPOSE_DUMP, ServerFamily.MYSQL)
    assert tool is not None
    env = {k: v for k, v in _client.child_env().items() if k != "MYSQL_TEST_LOGIN_FILE"}
    credentials = ResolvedCredentials("someone", "unused")
    with _client.option_pipe(credentials, site("unused")) as fd:
        done = subprocess.run(  # noqa: S603 - a found client tool, fixed arguments
            [tool.path, f"--defaults-file=/dev/fd/{fd}", "--print-defaults"],
            capture_output=True,
            text=True,
            env={**env, "HOME": str(tmp_path)},
            pass_fds=(fd,),
            check=True,
        )
    assert "--user=nobody" in done.stdout.split()


@pytest.mark.parametrize(
    "password", ["q'uo\"te", "back\\slash", "hash#semi;", "ab);cd", " spaced "]
)
def test_awkward_password_dumps(names: tuple[str, str], password: str) -> None:
    conn, wp = wordpress_site(names[0], password)
    assert dump(conn, wp, io.BytesIO()).bytes > 0


def test_encrypted_round_trip(names: tuple[str, str], tmp_path: Path) -> None:
    pytest.importorskip("pyrage")
    from l3io.wp.database import encryption

    identity, recipient = encryption.generate_identity()
    path = tmp_path / "site.sql.age"
    dump(site(names[0]), ROOT, path, recipients=[recipient])
    assert path.read_bytes().startswith(encryption.AGE_HEADER)
    with pytest.raises(RefusedError) as info:
        load(site(names[1]), ROOT, path)
    assert Code.IDENTITY_REQUIRED in info.value.verdict.codes
    load(site(names[1]), ROOT, path, identities=[identity])
    assert checksum(names[1]) == checksum(names[0])


def test_wrong_identity_loads_nothing(names: tuple[str, str], tmp_path: Path) -> None:
    pytest.importorskip("pyrage")
    from l3io.wp.database import encryption

    _, recipient = encryption.generate_identity()
    other, _ = encryption.generate_identity()
    path = tmp_path / "site.sql.age"
    dump(site(names[0]), ROOT, path, recipients=[recipient])
    with pytest.raises(DecryptionError):
        load(site(names[1]), ROOT, path, identities=[other])
    tables = sql(
        f"SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = '{names[1]}'"  # noqa: S608
    )
    assert tables[0][0] == 0


def test_truncated_encrypted_dump_is_corrupt(names: tuple[str, str], tmp_path: Path) -> None:
    pytest.importorskip("pyrage")
    from l3io.wp.database import encryption

    identity, recipient = encryption.generate_identity()
    path = tmp_path / "site.sql.age"
    dump(site(names[0]), ROOT, path, recipients=[recipient])
    path.write_bytes(path.read_bytes()[:-40])
    with pytest.raises(CorruptDumpError):
        load(site(names[1]), ROOT, path, identities=[identity])


def test_a_dump_killed_mid_stream_raises(names: tuple[str, str]) -> None:
    bulk(names[0])
    stream = iter_dump(site(names[0]), ROOT)
    next(stream)
    os.kill(stream.pid, 9)
    with pytest.raises(TransferError):
        list(stream)
