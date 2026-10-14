"""One object for one site: every operation with the connection bound."""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from typing import IO

from . import inspection, provision, transfer
from .connection import Connection
from .credentials import CredentialSource
from .inspection import Survey
from .provision import EnsureResult, OperationResult
from .state import ConnectionState
from .transfer import DumpStream, TransferResult
from .verdict import Verdict
from .versions import SchemaVersion


class Database:
    """Every operation against one :class:`Connection`.

    The free functions are the primary API; this binds one connection so a
    single object can serve one site.
    """

    __slots__ = ("_connection",)

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    @property
    def connection(self) -> Connection:
        """The site this object operates on."""
        return self._connection

    def survey(
        self,
        admin: CredentialSource,
        *,
        wordpress_user: str | None = None,
        user_host: str = "%",
        table_prefix: str = "wp_",
    ) -> Survey:
        return inspection.survey(
            self._connection,
            admin,
            wordpress_user=wordpress_user,
            user_host=user_host,
            table_prefix=table_prefix,
        )

    def inspect(self, credentials: CredentialSource) -> ConnectionState:
        return inspection.inspect(self._connection, credentials)

    def schema_version(
        self, credentials: CredentialSource, table_prefix: str = "wp_"
    ) -> SchemaVersion | None:
        return inspection.schema_version(self._connection, credentials, table_prefix)

    def check_ensure(
        self, admin: CredentialSource, wordpress: CredentialSource, *, user_host: str = "%"
    ) -> Verdict:
        return provision.check_ensure(self._connection, admin, wordpress, user_host=user_host)

    def ensure(
        self,
        admin: CredentialSource,
        wordpress: CredentialSource,
        *,
        user_host: str = "%",
        charset: str = "utf8mb4",
        collation: str = "utf8mb4_unicode_ci",
    ) -> EnsureResult:
        return provision.ensure(
            self._connection,
            admin,
            wordpress,
            user_host=user_host,
            charset=charset,
            collation=collation,
        )

    def check_rotate_password(
        self, admin: CredentialSource, wordpress: CredentialSource, *, user_host: str = "%"
    ) -> Verdict:
        return provision.check_rotate_password(
            self._connection, admin, wordpress, user_host=user_host
        )

    def rotate_password(
        self, admin: CredentialSource, wordpress: CredentialSource, *, user_host: str = "%"
    ) -> OperationResult:
        return provision.rotate_password(self._connection, admin, wordpress, user_host=user_host)

    def check_revoke(
        self, admin: CredentialSource, user: str, *, user_host: str = "%", confirm: str
    ) -> Verdict:
        return provision.check_revoke(
            self._connection, admin, user, user_host=user_host, confirm=confirm
        )

    def revoke(
        self, admin: CredentialSource, user: str, *, user_host: str = "%", confirm: str
    ) -> OperationResult:
        return provision.revoke(self._connection, admin, user, user_host=user_host, confirm=confirm)

    def check_drop_user(
        self, admin: CredentialSource, user: str, *, user_host: str = "%", confirm: str
    ) -> Verdict:
        return provision.check_drop_user(
            self._connection, admin, user, user_host=user_host, confirm=confirm
        )

    def drop_user(
        self, admin: CredentialSource, user: str, *, user_host: str = "%", confirm: str
    ) -> OperationResult:
        return provision.drop_user(
            self._connection, admin, user, user_host=user_host, confirm=confirm
        )

    def check_drop_database(self, admin: CredentialSource, *, confirm: str) -> Verdict:
        return provision.check_drop_database(self._connection, admin, confirm=confirm)

    def drop_database(self, admin: CredentialSource, *, confirm: str) -> OperationResult:
        return provision.drop_database(self._connection, admin, confirm=confirm)

    def check_dump(self, credentials: CredentialSource, *, options: Sequence[str] = ()) -> Verdict:
        return transfer.check_dump(self._connection, credentials, options=options)

    def iter_dump(
        self,
        credentials: CredentialSource,
        *,
        recipients: Sequence[str] | None = None,
        options: Sequence[str] = (),
    ) -> DumpStream:
        return transfer.iter_dump(
            self._connection, credentials, recipients=recipients, options=options
        )

    def dump(
        self,
        credentials: CredentialSource,
        to: IO[bytes] | str | os.PathLike[str],
        *,
        recipients: Sequence[str] | None = None,
        options: Sequence[str] = (),
    ) -> TransferResult:
        return transfer.dump(
            self._connection, credentials, to, recipients=recipients, options=options
        )

    def check_load(
        self,
        credentials: CredentialSource,
        *,
        source: str | os.PathLike[str] | None = None,
        replace: str | None = None,
        identities: Sequence[str] | None = None,
        options: Sequence[str] = (),
        allow_unsandboxed: bool = False,
    ) -> Verdict:
        return transfer.check_load(
            self._connection,
            credentials,
            source=source,
            replace=replace,
            identities=identities,
            options=options,
            allow_unsandboxed=allow_unsandboxed,
        )

    def load(
        self,
        credentials: CredentialSource,
        source: IO[bytes] | Iterable[bytes] | str | os.PathLike[str],
        *,
        replace: str | None = None,
        identities: Sequence[str] | None = None,
        options: Sequence[str] = (),
        allow_unsandboxed: bool = False,
    ) -> TransferResult:
        return transfer.load(
            self._connection,
            credentials,
            source,
            replace=replace,
            identities=identities,
            options=options,
            allow_unsandboxed=allow_unsandboxed,
        )

    def __repr__(self) -> str:
        return f"Database({self._connection!r})"
