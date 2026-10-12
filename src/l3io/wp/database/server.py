"""Which server this is, and what the session's own account may do."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

#: Floors: MariaDB 10.1 rejects ALTER USER, which provisioning needs.
_FLOOR = {"mysql": (8, 0, 0), "mariadb": (10, 2, 0)}

#: Upstream end of life, per (family, major, minor) series. Data, not logic:
#: extend it as series retire.
_END_OF_LIFE: frozenset[tuple[str, int, int]] = frozenset(
    {
        ("mysql", 5, 7),
        ("mysql", 8, 0),
        ("mariadb", 10, 1),
        ("mariadb", 10, 2),
        ("mariadb", 10, 3),
        ("mariadb", 10, 4),
        ("mariadb", 10, 5),
    }
)

_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)")


class ServerFamily(StrEnum):
    """The two server families this package supports."""

    MYSQL = "mysql"
    MARIADB = "mariadb"


@dataclass(frozen=True, slots=True)
class ServerInfo:
    """A server's family and version."""

    family: ServerFamily
    version: tuple[int, int, int]
    version_text: str

    @property
    def is_supported(self) -> bool:
        return self.version >= _FLOOR[self.family.value]

    @property
    def is_end_of_life(self) -> bool:
        major, minor, _ = self.version
        return (self.family.value, major, minor) in _END_OF_LIFE or not self.is_supported


def parse_version(text: str) -> ServerInfo:
    """Interpret ``SELECT VERSION()``."""
    match = _VERSION.match(text)
    if match is None:
        msg = f"unrecognised server version {text!r}"
        raise ValueError(msg)
    major, minor, patch = (int(g) for g in match.groups())
    family = ServerFamily.MARIADB if "mariadb" in text.lower() else ServerFamily.MYSQL
    return ServerInfo(family, (major, minor, patch), text)


def detect_server(cursor: Any) -> ServerInfo:
    """Ask the server what it is."""
    cursor.execute("SELECT VERSION()")
    return parse_version(str(cursor.fetchone()[0]))


def grantee(user: str, host: str) -> str:
    """The ``GRANTEE`` form ``information_schema`` uses."""
    return f"'{user}'@'{host}'"


@dataclass(frozen=True, slots=True)
class Privileges:
    """What the session's own account holds on one database."""

    names: frozenset[str]
    grantable: bool
    unverified: bool

    def has(self, name: str) -> bool:
        return self.grantable if name == "GRANT OPTION" else name in self.names


def account_privileges(cursor: Any, database: str) -> Privileges:
    """Global and database-level privileges of the session's own account.

    ``unverified`` is set when a role is active: ``information_schema`` lists
    only directly granted privileges, so a role-held privilege would read as
    missing.
    """
    cursor.execute("SELECT CURRENT_USER()")
    user, _, host = str(cursor.fetchone()[0]).rpartition("@")
    cursor.execute("SELECT CURRENT_ROLE()")
    role = cursor.fetchone()[0]
    unverified = role is not None and str(role).upper() != "NONE"

    who = grantee(user, host)
    cursor.execute(
        "SELECT PRIVILEGE_TYPE, IS_GRANTABLE FROM information_schema.USER_PRIVILEGES "
        "WHERE GRANTEE = %s",
        (who,),
    )
    rows = list(cursor.fetchall())
    cursor.execute(
        "SELECT PRIVILEGE_TYPE, IS_GRANTABLE FROM information_schema.SCHEMA_PRIVILEGES "
        "WHERE GRANTEE = %s AND %s LIKE TABLE_SCHEMA",
        (who, database),
    )
    rows += list(cursor.fetchall())
    names = frozenset(str(r[0]) for r in rows)
    grantable = any(str(r[1]).upper() == "YES" for r in rows)
    return Privileges(names, grantable, unverified)
