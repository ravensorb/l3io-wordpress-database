"""WordPress database operations, each checked before it runs.

``l3io`` and ``l3io.wp`` are a PEP 420 namespace shared with
``l3io-wordpress-config`` and ``l3io-wordpress-backup``; this is the only
``__init__.py`` above this directory (AD-27).

The identifier helpers are public because AD-28 requires grant-target escaping
to go through one shared function: dependents import ``quote_grant_database``
from here rather than reimplementing it.
"""

from __future__ import annotations

from ._client import ClientTool
from ._version import __version__
from .connection import DEFAULT_PORT, Connection
from .credentials import (
    AwsSecretsManager,
    CredentialChain,
    CredentialSource,
    Environment,
    Explicit,
    ResolvedCredentials,
)
from .encryption import (
    check_passphrase,
    check_recipients,
    decrypt,
    encrypt,
    generate_identity,
)
from .errors import (
    AccessDeniedError,
    AuthenticationFailedError,
    ConfigUnreadableError,
    ConfigurationError,
    CorruptDumpError,
    CredentialsAbsentError,
    CredentialsUnobtainableError,
    DatabaseError,
    DatabaseUnreachableError,
    DecryptionError,
    InvalidArgumentsError,
    InvalidDatabaseNameError,
    InvalidIdentifierError,
    MissingConfigValueError,
    MissingDependencyError,
    ProvisioningError,
    RefusedError,
    RegionNotKnownError,
    TransferError,
)
from .facade import Database
from .identifiers import (
    quote_grant_database,
    quote_identifier,
    validate_database_name,
    validate_user_name,
)
from .inspection import Survey, inspect, schema_version, survey
from .provision import (
    EnsureResult,
    OperationResult,
    check_drop_database,
    check_drop_user,
    check_ensure,
    check_revoke,
    check_rotate_password,
    drop_database,
    drop_user,
    ensure,
    revoke,
    rotate_password,
)
from .server import ServerFamily, ServerInfo
from .state import ConnectionState
from .transfer import (
    DumpStream,
    TransferResult,
    check_dump,
    check_load,
    dump,
    iter_dump,
    load,
)
from .verdict import Code, Finding, Severity, Verdict
from .versions import SUPPORTED_FROM, SchemaVersion, release_for
from .wpconfig import DEFAULT_TABLE_PREFIX, WpConfigFile

__all__ = [
    "AccessDeniedError",
    "AuthenticationFailedError",
    "AwsSecretsManager",
    "ClientTool",
    "Code",
    "ConfigUnreadableError",
    "ConfigurationError",
    "Connection",
    "ConnectionState",
    "CorruptDumpError",
    "CredentialChain",
    "CredentialSource",
    "CredentialsAbsentError",
    "CredentialsUnobtainableError",
    "DEFAULT_PORT",
    "DEFAULT_TABLE_PREFIX",
    "Database",
    "DatabaseError",
    "DatabaseUnreachableError",
    "DecryptionError",
    "DumpStream",
    "EnsureResult",
    "Environment",
    "Explicit",
    "Finding",
    "InvalidArgumentsError",
    "InvalidDatabaseNameError",
    "InvalidIdentifierError",
    "MissingConfigValueError",
    "MissingDependencyError",
    "OperationResult",
    "ProvisioningError",
    "RefusedError",
    "RegionNotKnownError",
    "ResolvedCredentials",
    "SUPPORTED_FROM",
    "SchemaVersion",
    "ServerFamily",
    "ServerInfo",
    "Severity",
    "Survey",
    "TransferError",
    "TransferResult",
    "Verdict",
    "WpConfigFile",
    "__version__",
    "check_drop_database",
    "check_drop_user",
    "check_dump",
    "check_ensure",
    "check_load",
    "check_passphrase",
    "check_recipients",
    "check_revoke",
    "check_rotate_password",
    "decrypt",
    "drop_database",
    "drop_user",
    "dump",
    "encrypt",
    "ensure",
    "generate_identity",
    "inspect",
    "iter_dump",
    "load",
    "quote_grant_database",
    "quote_identifier",
    "release_for",
    "revoke",
    "rotate_password",
    "schema_version",
    "survey",
    "validate_database_name",
    "validate_user_name",
]
