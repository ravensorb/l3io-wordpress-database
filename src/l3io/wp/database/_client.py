"""The MySQL and MariaDB client programs: finding them, and running them without
exposing a password. Internal.

A password never appears in an argument vector, a child's environment, or a file
on disk (spec §2.4). The client reads its options from an anonymous pipe named
``--defaults-file=/dev/fd/N`` and placed first, which also stops it reading
``~/.my.cnf``. MySQL clients still read ``~/.mylogin.cnf`` after that, so login
paths are suppressed: ``MYSQL_TEST_LOGIN_FILE`` points at nothing for every
client, and MySQL 8.4+ also gets ``--no-login-paths`` (probe V2; MariaDB has no
login-path file). The child environment holds nothing else that could redirect
or authenticate it.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass

from .connection import Connection
from .credentials import ResolvedCredentials
from .errors import InvalidArgumentsError
from .server import ServerFamily

PURPOSE_DUMP = "dump"
PURPOSE_LOAD = "load"

_CANDIDATES: dict[str, dict[ServerFamily, tuple[str, ...]]] = {
    PURPOSE_DUMP: {
        ServerFamily.MARIADB: ("mariadb-dump", "mysqldump"),
        ServerFamily.MYSQL: ("mysqldump",),
    },
    PURPOSE_LOAD: {
        ServerFamily.MARIADB: ("mariadb", "mysql"),
        ServerFamily.MYSQL: ("mysql",),
    },
}

_MARIADB_VERSION = re.compile(r"(?:Distrib|from) (\d+)\.(\d+)\.(\d+)-MariaDB")
_MYSQL_VERSION = re.compile(r"\bVer (\d+)\.(\d+)\.(\d+)")

#: First MariaDB client release, per series, that reads the sandbox line MariaDB
#: dumps begin with (MDEV-33727). MySQL clients read it as a comment (probe V1).
#: A series absent here and older than the newest listed is treated as unable.
_SANDBOX_SINCE: dict[tuple[int, int], int] = {
    (10, 5): 25,
    (10, 6): 18,
    (10, 11): 8,
    (11, 0): 6,
    (11, 1): 5,
    (11, 2): 4,
    (11, 4): 2,
}

_NO_LOGIN_FILE = "/nonexistent/l3io-wordpress-database/no-login-file"

_MAX_VALUE_BYTES = 1024

#: Options a caller may add. Anything touching credentials, option files, the
#: host or an output file is refused by omission.
DUMP_OPTIONS = frozenset(
    {
        "--routines",
        "--events",
        "--skip-triggers",
        "--ignore-table",
        "--no-data",
        "--skip-extended-insert",
        "--where",
        "--max-allowed-packet",
    }
)
LOAD_OPTIONS = frozenset({"--binary-mode", "--max-allowed-packet"})


@dataclass(frozen=True, slots=True)
class ClientTool:
    """One client program, and what it is."""

    name: str
    path: str
    family: ServerFamily
    version: tuple[int, int, int]
    version_text: str

    @property
    def label(self) -> str:
        return f"{self.name} {self.version_text}"

    @property
    def understands_sandbox_line(self) -> bool:
        if self.family is ServerFamily.MYSQL:
            return True
        series = self.version[:2]
        if series > max(_SANDBOX_SINCE):
            return True
        since = _SANDBOX_SINCE.get(series)
        return since is not None and self.version[2] >= since


def parse_client_version(name: str, path: str, text: str) -> ClientTool:
    """Interpret a client program's ``--version`` output."""
    match = _MARIADB_VERSION.search(text)
    family = ServerFamily.MARIADB
    if match is None:
        match = _MYSQL_VERSION.search(text)
        family = ServerFamily.MYSQL
    if match is None:
        msg = f"unrecognised client version {text.strip()!r}"
        raise ValueError(msg)
    major, minor, patch = (int(g) for g in match.groups())
    return ClientTool(name, path, family, (major, minor, patch), text.strip())


def child_env() -> dict[str, str]:
    """The entire environment a client program gets.

    No ``HOME``, ``MYSQL_PWD``, ``MYSQL_HOST`` or ``MYSQL_TCP_PORT``: nothing
    inherited can authenticate or redirect it.
    """
    return {
        "PATH": os.environ.get("PATH", os.defpath),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "MYSQL_TEST_LOGIN_FILE": _NO_LOGIN_FILE,
    }


def candidates(purpose: str, family: ServerFamily) -> tuple[str, ...]:
    """Program names to try for this server: its own family's first."""
    other = ServerFamily.MYSQL if family is ServerFamily.MARIADB else ServerFamily.MARIADB
    names = (*_CANDIDATES[purpose][family], *_CANDIDATES[purpose][other])
    return tuple(dict.fromkeys(names))


def find_tool(purpose: str, family: ServerFamily) -> ClientTool | None:
    """The best client program on ``PATH`` for this server, or ``None``."""
    for name in candidates(purpose, family):
        path = shutil.which(name)
        if path is None:
            continue
        try:
            done = subprocess.run(  # noqa: S603 - an absolute path found on PATH, fixed argument
                [path, "--version"],
                capture_output=True,
                text=True,
                timeout=15,
                env=child_env(),
                check=False,
            )
            return parse_client_version(name, path, done.stdout or done.stderr)
        except (OSError, subprocess.SubprocessError, ValueError):
            continue
    return None


def _quote(field: str, value: str) -> str:
    """An option-file value: quoted, with backslash, quote and newline escaped (V5).

    MariaDB reads an option line longer than its fixed buffer (about 4 KiB) as
    two lines, quoted or not, so an overlong value would smuggle in an option of
    the caller's choosing. Values are capped well below that. No message here
    may carry the value, and no refusal may chain the encoder's exception, whose
    ``object`` is the value itself.
    """
    if "\x00" in value:
        msg = "a connection value cannot contain a NUL character"
        raise InvalidArgumentsError(msg)
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    try:
        size = len(escaped.encode())
    except UnicodeEncodeError:
        size = None
    if size is None:
        msg = f"the {field} is not valid UTF-8 text"
        raise InvalidArgumentsError(msg)
    if size > _MAX_VALUE_BYTES:
        msg = f"the {field} is longer than {_MAX_VALUE_BYTES} bytes once escaped"
        raise InvalidArgumentsError(msg)
    return f'"{escaped}"'


def option_file_text(credentials: ResolvedCredentials, connection: Connection) -> str:
    """The ``[client]`` options a program reads from the pipe."""
    return (
        "[client]\n"
        f"user={_quote('user', credentials.username)}\n"
        f"password={_quote('password', credentials.password)}\n"
        f"host={_quote('host', connection.host)}\n"
        f"port={connection.port}\n"
        "protocol=TCP\n"
    )


@contextmanager
def option_pipe(credentials: ResolvedCredentials, connection: Connection) -> Iterator[int]:
    """A pipe holding the option file; yields its read end, closed on exit.

    Pass the fd with ``pass_fds`` and name it ``/dev/fd/N``. Nothing touches disk.
    """
    data = option_file_text(credentials, connection).encode()
    read_fd, write_fd = os.pipe()
    try:
        while data:
            data = data[os.write(write_fd, data) :]
    finally:
        os.close(write_fd)
    try:
        yield read_fd
    finally:
        os.close(read_fd)


def disallowed_options(options: Sequence[str], allowed: frozenset[str]) -> list[str]:
    """Caller options whose name is not on the allow-list."""
    return [o for o in options if o.split("=", 1)[0] not in allowed]


def _login_path_args(tool: ClientTool) -> list[str]:
    if tool.family is ServerFamily.MYSQL and tool.version >= (8, 4, 0):
        return ["--no-login-paths"]
    return []


def argv(tool: ClientTool, fd: int, args: Sequence[str]) -> list[str]:
    """The full argument vector: the option file first, then login-path suppression."""
    return [tool.path, f"--defaults-file=/dev/fd/{fd}", *_login_path_args(tool), *args]


def dump_args(tool: ClientTool, database: str, options: Sequence[str]) -> list[str]:
    """Consistent, streaming, binary-safe, without CREATE DATABASE/USE (V7)."""
    args = [
        "--single-transaction",
        "--quick",
        "--hex-blob",
        "--default-character-set=utf8mb4",
        "--no-tablespaces",
    ]
    if tool.family is ServerFamily.MYSQL:
        args.append("--set-gtid-purged=OFF")
    return [*args, *options, database]


def load_args(database: str, options: Sequence[str]) -> list[str]:
    return ["--default-character-set=utf8mb4", f"--database={database}", *options]
