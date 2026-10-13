"""Where a WordPress database lives and who connects to it.

AD-3: one immutable site descriptor. The original had two writers for a single
value -- ``db_host``'s setter parsed ``host:port`` and derived ``_db_port``,
while ``db_port`` had its own independent setter, so assigning ``db_host``
after ``db_port`` silently discarded the port. Parsed once, frozen, no setters.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import InvalidArgumentsError
from .identifiers import validate_database_name

DEFAULT_PORT = 3306


def _split_db_host(db_host: str) -> tuple[str, int]:
    """Split WordPress's ``DB_HOST`` (``host`` or ``host:port``)."""
    if not db_host:
        msg = "DB_HOST must not be empty"
        raise InvalidArgumentsError(msg)
    host, separator, port_text = db_host.partition(":")
    if separator and port_text:
        try:
            return host, int(port_text)
        except ValueError as exc:
            msg = f"DB_HOST port {port_text!r} is not an integer"
            raise InvalidArgumentsError(msg) from exc
    return host, DEFAULT_PORT


@dataclass(frozen=True, slots=True)
class Connection:
    """Where one WordPress database lives. Carries no credentials."""

    host: str
    database: str
    port: int = DEFAULT_PORT

    def __post_init__(self) -> None:
        if not self.host:
            msg = "host must not be empty"
            raise InvalidArgumentsError(msg)
        if not isinstance(self.port, int) or not (0 < self.port < 65536):
            msg = f"port must be an integer between 1 and 65535, not {self.port!r}"
            raise InvalidArgumentsError(msg)
        validate_database_name(self.database)

    @classmethod
    def from_db_host(cls, db_host: str, database: str) -> Connection:
        """Build from WordPress's ``DB_HOST``, which may carry ``host:port``."""
        host, port = _split_db_host(db_host)
        return cls(host=host, database=database, port=port)
