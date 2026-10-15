"""Outcomes of inspecting a database's state.

"Does this database exist?" answered with a bare boolean, from a method that
catches every exception and returns ``False``, makes "absent", "wrong password"
and "host unreachable" indistinguishable -- and since the caller's next move is
to create objects using *administrative* credentials, collapsing those cases is
the dangerous part, not a cosmetic one.
"""

from __future__ import annotations

from enum import StrEnum


class ConnectionState(StrEnum):
    """Why an attempt to use a database succeeded or failed."""

    READY = "ready"
    """Connected, authenticated, and the database is usable."""

    DATABASE_ABSENT = "database_absent"
    """Authenticated, but the target database does not exist.

    Only observable once the account itself exists: the server authenticates
    before it resolves the database, so a site with neither reports
    :attr:`AUTHENTICATION_FAILED` instead. Verified against MySQL 8.0.
    """

    ACCESS_DENIED = "access_denied"
    """Authenticated, but this account may not use the target database."""

    AUTHENTICATION_FAILED = "authentication_failed"
    """The server was reached and rejected the credentials."""

    UNREACHABLE = "unreachable"
    """The server could not be reached."""

    CREDENTIALS_UNOBTAINABLE = "credentials_unobtainable"
    """Credentials could not be obtained, so nothing was attempted."""

    @property
    def is_ready(self) -> bool:
        """Whether the database is usable as configured."""
        return self is ConnectionState.READY

    @property
    def needs_provisioning(self) -> bool:
        """Whether provisioning with administrative credentials could fix this.

        Authentication failure counts. Before first provisioning the WordPress
        account does not exist yet, so inspecting as that account *must* fail --
        treating that as a refusal to provision would reject the single most
        common case this package exists for: a database created by
        ``wp db create`` or a MySQL container's ``MYSQL_DATABASE``, with no user
        yet. The administrator is the authority on what exists, not the failed
        login of an account that is the whole point of the operation.
        """
        return self in {
            ConnectionState.DATABASE_ABSENT,
            ConnectionState.AUTHENTICATION_FAILED,
            ConnectionState.ACCESS_DENIED,
        }

    @property
    def blocks_provisioning(self) -> bool:
        """Whether provisioning cannot proceed, whatever credentials are held.

        An unreachable server or unobtainable credentials say nothing about
        what exists, so nothing may be created on the strength of them.
        """
        return self in {
            ConnectionState.UNREACHABLE,
            ConnectionState.CREDENTIALS_UNOBTAINABLE,
        }
