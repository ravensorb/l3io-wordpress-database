"""Create and inspect WordPress MySQL databases and their users, idempotently.

The identifier helpers are public because AD-28 requires grant-target escaping
to go through one shared function rather than being reimplemented inline.
``l3io-wordpress-backup`` depends on this package and should import
``quote_grant_database`` from here instead of rewriting it.

This is the only ``__init__.py`` above this directory in the distribution:
``l3io`` and ``l3io.wp`` are a PEP 420 native namespace shared with
``l3io-wordpress-config`` and ``l3io-wordpress-backup`` (AD-27).
"""

from __future__ import annotations

from ._version import __version__
from .connection import DEFAULT_PORT, WpConnection
from .credentials import ResolvedCredentials, WpCredentials
from .database import EnsureResult, WpDatabase
from .errors import (
    AccessDeniedError,
    AuthenticationFailedError,
    ConfigUnreadableError,
    ConfigurationError,
    CredentialsUnobtainableError,
    DatabaseUnreachableError,
    InvalidArgumentsError,
    InvalidDatabaseNameError,
    InvalidIdentifierError,
    MissingConfigValueError,
    MissingDependencyError,
    ProvisioningError,
    RegionNotKnownError,
    WpDatabaseError,
)
from .identifiers import (
    quote_grant_database,
    quote_identifier,
    validate_database_name,
    validate_user_name,
)
from .state import ConnectionState
from .versions import SUPPORTED_FROM, WpDatabaseVersion, release_for
from .wpconfig import DEFAULT_TABLE_PREFIX, WpConfigSource

__all__ = [
    "AccessDeniedError",
    "AuthenticationFailedError",
    "ConfigUnreadableError",
    "ConfigurationError",
    "ConnectionState",
    "CredentialsUnobtainableError",
    "DEFAULT_PORT",
    "DEFAULT_TABLE_PREFIX",
    "DatabaseUnreachableError",
    "EnsureResult",
    "InvalidArgumentsError",
    "InvalidDatabaseNameError",
    "InvalidIdentifierError",
    "MissingConfigValueError",
    "MissingDependencyError",
    "ProvisioningError",
    "RegionNotKnownError",
    "ResolvedCredentials",
    "SUPPORTED_FROM",
    "WpConfigSource",
    "WpConnection",
    "WpCredentials",
    "WpDatabase",
    "WpDatabaseError",
    "WpDatabaseVersion",
    "__version__",
    "quote_grant_database",
    "quote_identifier",
    "release_for",
    "validate_database_name",
    "validate_user_name",
]
