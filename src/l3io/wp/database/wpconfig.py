"""Read connection details out of a WordPress ``wp-config.php``.

An adapter over ``l3io-wordpress-config``, which lives behind the ``wpconfig`` extra.
Per AD-1 the adapter *holds* the config object and exposes only what this
package needs, rather than subclassing it -- subclassing would make every
method of the underlying type public here automatically, so the declared
surface would leak by construction and ``__all__`` could not bound it.

Three properties of the upstream API matter enough to state:

* An absent key returns a ``MISSING`` sentinel, not ``None``. ``MISSING`` is
  falsy, so ``if config.get("DB_PASSWORD"):`` cannot distinguish "not defined"
  from a legitimately empty value. Every read here tests ``is MISSING``.
* PHP types are preserved, so ``define('DB_PORT', 3306)`` is an ``int`` while
  ``define('DB_PASSWORD', '3306')`` stays a ``str``. Values are coerced
  deliberately rather than assumed to be strings.
* ``$table_prefix`` is a PHP *variable*, not a ``define()``, and lives in a
  separate namespace: ``get_variable("table_prefix")``. ``get("table_prefix")``
  correctly returns ``MISSING``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from .connection import Connection, WpConnection
from .credentials import ResolvedCredentials, WpCredentials
from .errors import (
    ConfigUnreadableError,
    CredentialsAbsentError,
    MissingConfigValueError,
    MissingDependencyError,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from l3io.wp.config import WpConfigFile as UpstreamConfigFile

_log = structlog.get_logger(__name__)

#: WordPress's own default when ``$table_prefix`` is not set.
DEFAULT_TABLE_PREFIX = "wp_"


class WpConfigSource:
    """The database settings of one ``wp-config.php``."""

    __slots__ = ("_config", "_missing", "_path")

    def __init__(self, path: str | Path) -> None:
        """Open a configuration file.

        Raises:
            MissingDependencyError: the ``wpconfig`` extra is not installed.
            ConfigUnreadableError: the file could not be read.
        """
        self._path = str(path)

        # AD-8: the optional dependency is imported inside the code that uses
        # it, so a base install never pays for it.
        try:
            from l3io.wp.config import MISSING, WpConfigError
            from l3io.wp.config import WpConfigFile as UpstreamConfigFile
        except ImportError as exc:
            raise MissingDependencyError(
                extra="wpconfig", distribution="l3io-wordpress-config"
            ) from exc

        self._missing = MISSING
        try:
            self._config: UpstreamConfigFile = UpstreamConfigFile(filename=self._path)
        except WpConfigError as exc:
            # AD-14: the upstream exception type must not cross this boundary.
            raise ConfigUnreadableError(self._path, str(exc)) from exc

    @property
    def path(self) -> str:
        """The configuration file this source reads."""
        return self._path

    @property
    def table_prefix(self) -> str:
        """WordPress's ``$table_prefix``, or its default when unset.

        Read through the variable accessor, not ``get()`` -- the prefix is a
        PHP variable assignment and is absent from the ``define()`` namespace.
        """
        value = self._config.get_variable("table_prefix")
        if value is self._missing:
            _log.debug(
                "table_prefix not set; using WordPress default",
                path=self._path,
                default=DEFAULT_TABLE_PREFIX,
            )
            return DEFAULT_TABLE_PREFIX
        return str(value)

    def credentials(self) -> WpCredentials:
        """The WordPress database account declared in the configuration."""
        return WpCredentials.from_username_and_password(
            username=self._require("DB_USER"),
            password=self._require("DB_PASSWORD"),
        )

    def connection(self) -> WpConnection:
        """An immutable descriptor of the database this configuration points at."""
        return WpConnection.from_db_host(
            db_host=self._require("DB_HOST"),
            db_name=self._require("DB_NAME"),
            credentials=self.credentials(),
        )

    def _require(self, key: str) -> str:
        """Read a defined setting as text, or say which one is missing.

        Absence is tested with ``is MISSING`` rather than by falsiness, so a
        setting defined as an empty string is reported as present -- which it
        is, and which a truthiness test would silently call absent.
        """
        value: Any = self._config.get(key)
        if value is self._missing:
            raise MissingConfigValueError(key, self._path)
        # Types are preserved upstream, so an unquoted numeric value arrives as
        # an int and a bool arrives as a bool. Everything this package consumes
        # is textual, so coerce explicitly rather than assuming.
        return value if isinstance(value, str) else str(value)

    def __repr__(self) -> str:
        return f"WpConfigSource(path={self._path!r})"


class WpConfigFile:
    """A site's ``wp-config.php``: a credential source, and where its database lives.

    Needs the ``wpconfig`` extra.
    """

    __slots__ = ("_config", "_missing", "_path")

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        try:
            from l3io.wp.config import MISSING, WpConfigError
            from l3io.wp.config import WpConfigFile as _Upstream
        except ImportError as exc:
            raise MissingDependencyError(
                extra="wpconfig", distribution="l3io-wordpress-config"
            ) from exc
        self._missing = MISSING
        try:
            self._config: Any = _Upstream(filename=self._path)
        except WpConfigError as exc:
            raise ConfigUnreadableError(self._path, str(exc)) from exc

    @property
    def path(self) -> str:
        return self._path

    @property
    def source(self) -> str:
        return f"wp-config:{self._path}"

    @property
    def table_prefix(self) -> str:
        """WordPress's ``$table_prefix``, or ``wp_`` when unset."""
        value = self._config.get_variable("table_prefix")
        return DEFAULT_TABLE_PREFIX if value is self._missing else str(value)

    def resolve(self) -> ResolvedCredentials:
        user, password = self._get("DB_USER"), self._get("DB_PASSWORD")
        if user is None and password is None:
            msg = f"{self._path} defines neither DB_USER nor DB_PASSWORD"
            raise CredentialsAbsentError(msg, sources=(self.source,))
        return ResolvedCredentials(
            self._require("DB_USER", user),
            self._require("DB_PASSWORD", password),
            self.source,
        )

    def connection(self) -> Connection:
        """Where the configured database lives."""
        host = self._require("DB_HOST", self._get("DB_HOST"))
        name = self._require("DB_NAME", self._get("DB_NAME"))
        return Connection.from_db_host(host, name)

    def _require(self, key: str, value: str | None) -> str:
        """Return a value read by ``_get``, or raise naming the missing key."""
        if value is None:
            raise MissingConfigValueError(key, self._path)
        return value

    def _get(self, key: str) -> str | None:
        value: Any = self._config.get(key)
        if value is self._missing:
            return None
        return value if isinstance(value, str) else str(value)

    def __repr__(self) -> str:
        return f"WpConfigFile(path={self._path!r})"
