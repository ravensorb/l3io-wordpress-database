"""Command line entry point.

The library never configures logging; this does, because it owns the process.
No option takes a password value: an argument vector is visible to every user
on the machine. Passwords come from environment variables, wp-config.php, AWS,
or a prompt on a terminal.
"""

from __future__ import annotations

import argparse
import dataclasses
import getpass
import json
import logging
import os
import sys
from collections.abc import Mapping
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any

import structlog

from ._version import __version__
from .connection import Connection
from .credentials import AwsSecretsManager, CredentialSource, Explicit
from .errors import (
    ConfigurationError,
    CredentialsAbsentError,
    CredentialsUnobtainableError,
    DatabaseError,
    DatabaseUnreachableError,
    InvalidArgumentsError,
    InvalidIdentifierError,
    MissingDependencyError,
    RefusedError,
)
from .inspection import inspect, schema_version, survey
from .provision import (
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
from .transfer import check_dump, check_load, dump, load
from .verdict import Code, Verdict


class Exit(IntEnum):
    """Process exit codes. Part of the CLI contract."""

    OK = 0
    FAILED = 1
    USAGE = 2
    REFUSED = 3
    CREDENTIALS = 4
    UNREACHABLE = 5
    NOT_READY = 7


_NEEDS_WP = {"inspect", "schema-version", "ensure", "rotate-password", "dump", "load"}
_NEEDS_ADMIN = {"survey", "ensure", "rotate-password", "revoke", "drop-user", "drop-database"}
_NAMED_USER = {"revoke", "drop-user"}
_CONFIRM = {"revoke", "drop-user", "drop-database"}
_CHECKABLE = ["ensure", "rotate-password", "revoke", "drop-user", "drop-database", "dump", "load"]
_TRANSFER = {"dump", "load"}


def _add_operation_options(
    p: argparse.ArgumentParser, operation: str, *, check: bool = False
) -> None:
    site = p.add_argument_group("site")
    site.add_argument("--wp-config", help="path to wp-config.php (needs the 'wpconfig' extra)")
    site.add_argument("--db-host", help="database host, optionally host:port")
    site.add_argument("--db-name", help="database name")
    if operation in _NEEDS_WP:
        wp = p.add_argument_group("WordPress account (or --wp-config)")
        wp.add_argument("--db-user", help="WordPress database user")
        wp.add_argument("--db-password-env", metavar="VAR", help="variable holding its password")
    if operation in _NEEDS_ADMIN:
        admin = p.add_argument_group("administrative account (required)")
        admin.add_argument("--admin-user", help="administrative user")
        admin.add_argument(
            "--admin-password-env", metavar="VAR", help="variable holding its password"
        )
        admin.add_argument("--admin-aws-secret-id", help="AWS secret holding the admin credentials")
        admin.add_argument("--admin-aws-region", help="AWS region of that secret")
    if operation in {"survey", "ensure", "rotate-password", *_NAMED_USER}:
        p.add_argument("--user-host", default="%", help="host part of the account (default: %%)")
    if operation in _NAMED_USER:
        p.add_argument("--user", required=True, help="the account to act on")
    if operation in _CONFIRM:
        p.add_argument("--confirm", required=True, metavar="NAME", help="repeat the target's name")
    if operation == "survey":
        p.add_argument(
            "--wordpress-user", help="also report this account's existence and privileges"
        )
    if operation in {"survey", "schema-version"}:
        p.add_argument(
            "--table-prefix", help="WordPress $table_prefix (default: from wp-config, else wp_)"
        )
    if operation == "dump":
        # A check writes and encrypts nothing, so it takes neither option.
        if not check:
            p.add_argument("--output", required=True, help="file to write, or - for stdout")
            p.add_argument(
                "--recipient",
                action="append",
                default=[],
                help="age or SSH public key (repeatable)",
            )
            p.add_argument(
                "--passphrase-file",
                metavar="PATH",
                help="file holding the age passphrase (never pass the secret on argv)",
            )
            p.add_argument(
                "--ask-passphrase",
                action="store_true",
                help="prompt on a terminal for the age passphrase",
            )
        p.add_argument(
            "--option",
            action="append",
            default=[],
            help="extra dump option (allow-listed, repeatable); join it with '=': "
            "--option=--ignore-table=wp_site.wp_logs",
        )
    if operation == "load":
        p.add_argument("--input", required=True, help="dump file to read, or - for stdin")
        p.add_argument(
            "--identity", action="append", default=[], help="age identity file (repeatable)"
        )
        p.add_argument(
            "--identity-passphrase-env",
            metavar="VAR",
            help="variable holding the identity files' passphrase",
        )
        p.add_argument(
            "--passphrase-file",
            metavar="PATH",
            help="file holding the age passphrase (never pass the secret on argv)",
        )
        p.add_argument(
            "--ask-passphrase",
            action="store_true",
            help="prompt on a terminal for the age passphrase",
        )
        p.add_argument(
            "--replace", metavar="NAME", help="repeat the target's name to load over its tables"
        )
        p.add_argument(
            "--allow-unsandboxed",
            action="store_true",
            help="strip MariaDB's sandbox line for an older client",
        )
        p.add_argument(
            "--option",
            action="append",
            default=[],
            help="extra client option (allow-listed, repeatable); join it with '=': "
            "--option=--binary-mode",
        )


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="l3io-wordpress-database",
        description="WordPress database operations, each checked before it runs.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--log-level", default="INFO", help="logging level (default: INFO)")
    parser.add_argument("--log-format", choices=["console", "json"], default="console")
    sub = parser.add_subparsers(dest="operation", required=True)
    for name in ["survey", "inspect", "schema-version", *_CHECKABLE]:
        _add_operation_options(sub.add_parser(name), name)
    check = sub.add_parser("check", help="run an operation's check only")
    check_sub = check.add_subparsers(dest="checked", required=True)
    for name in _CHECKABLE:
        _add_operation_options(check_sub.add_parser(name), name, check=True)
    return parser


def _configure_logging(level: str, fmt: str) -> None:
    numeric = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
    logging.basicConfig(level=numeric, format="%(message)s", stream=sys.stderr)
    renderer: Any = (
        structlog.processors.JSONRenderer() if fmt == "json" else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )


def _password(var: str | None, who: str) -> str:
    if var is not None:
        value = os.environ.get(var)
        if value is None:
            msg = f"{var} is not set"
            raise CredentialsUnobtainableError(msg)
        return value
    if sys.stdin.isatty():
        return getpass.getpass(f"password for {who}: ")
    msg = f"no password source for {who}: give the -env option or run on a terminal"
    raise CredentialsUnobtainableError(msg)


def _site(args: argparse.Namespace) -> tuple[Connection, Any]:
    if args.wp_config:
        if args.db_host or args.db_name:
            msg = "give either --wp-config or --db-host/--db-name, not both"
            raise InvalidArgumentsError(msg)
        from .wpconfig import WpConfigFile

        config = WpConfigFile(args.wp_config)
        return config.connection(), config
    if not (args.db_host and args.db_name):
        msg = "give --wp-config, or both --db-host and --db-name"
        raise InvalidArgumentsError(msg)
    return Connection.from_db_host(args.db_host, args.db_name), None


def _wordpress(args: argparse.Namespace, config: Any) -> CredentialSource:
    if config is not None and not getattr(args, "db_user", None):
        return config  # type: ignore[no-any-return]
    if not getattr(args, "db_user", None):
        msg = "give --wp-config or --db-user"
        raise InvalidArgumentsError(msg)
    return Explicit(args.db_user, _password(args.db_password_env, args.db_user))


def _admin(args: argparse.Namespace) -> CredentialSource:
    if args.admin_aws_secret_id:
        if args.admin_user:
            msg = "give either --admin-user or --admin-aws-secret-id, not both"
            raise InvalidArgumentsError(msg)
        return AwsSecretsManager(args.admin_aws_secret_id, args.admin_aws_region)
    if not args.admin_user:
        msg = "administrative credentials are required: give --admin-user or --admin-aws-secret-id"
        raise InvalidArgumentsError(msg)
    return Explicit(args.admin_user, _password(args.admin_password_env, args.admin_user))


def _jsonable(obj: Any) -> Any:
    """Convert a result to JSON-ready data.

    Not ``dataclasses.asdict``: it deep-copies values, and a Finding's fields
    are a read-only mapping that cannot be copied.
    """
    if isinstance(obj, Verdict):
        return {
            "operation": obj.operation,
            "ok": obj.ok,
            "findings": [
                {
                    "code": str(f.code),
                    "severity": str(f.severity),
                    "message": f.message,
                    "fields": dict(f.fields),
                }
                for f in obj.findings
            ],
        }
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, Enum):
        return str(obj.value)
    if isinstance(obj, Mapping):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (set, frozenset)):
        return sorted(_jsonable(v) for v in obj)
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


def _identities(args: argparse.Namespace) -> list[str]:
    from .encryption import read_identity

    passphrase = (
        _password(args.identity_passphrase_env, "the identity files")
        if args.identity_passphrase_env
        else None
    )
    return [read_identity(path, passphrase) for path in args.identity]


def _passphrase(args: argparse.Namespace) -> str | None:
    """Age content passphrase from a file or a TTY prompt — never from argv."""
    path = getattr(args, "passphrase_file", None)
    ask = bool(getattr(args, "ask_passphrase", False))
    if path is not None and ask:
        msg = "supply --passphrase-file or --ask-passphrase, not both"
        raise InvalidArgumentsError(msg)
    if path is not None:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            msg = f"cannot read the passphrase file {path!r}: {exc.strerror}"
            raise InvalidArgumentsError(msg) from exc
        secret = text.rstrip("\n")
        if not secret:
            msg = f"passphrase file {path!r} is empty"
            raise InvalidArgumentsError(msg)
        return secret
    if ask:
        if not sys.stdin.isatty():
            msg = "no passphrase source: give --passphrase-file or run on a terminal"
            raise CredentialsUnobtainableError(msg)
        return getpass.getpass("age passphrase: ")
    return None


def _emit(value: Any, stream: Any = None) -> None:
    print(json.dumps(_jsonable(value), indent=2), file=stream or sys.stdout)


def _run(args: argparse.Namespace) -> int:
    operation = args.checked if args.operation == "check" else args.operation
    connection, config = _site(args)
    prefix = getattr(args, "table_prefix", None) or (config.table_prefix if config else "wp_")

    if args.operation == "check":
        # Never resolved for a transfer: only the provisioning checks use the admin account.
        admin = Explicit("", "") if operation in _TRANSFER else _admin(args)
        checks: dict[str, Any] = {
            "ensure": lambda: check_ensure(
                connection, admin, _wordpress(args, config), user_host=args.user_host
            ),
            "rotate-password": lambda: check_rotate_password(
                connection, admin, _wordpress(args, config), user_host=args.user_host
            ),
            "revoke": lambda: check_revoke(
                connection, admin, args.user, user_host=args.user_host, confirm=args.confirm
            ),
            "drop-user": lambda: check_drop_user(
                connection, admin, args.user, user_host=args.user_host, confirm=args.confirm
            ),
            "drop-database": lambda: check_drop_database(connection, admin, confirm=args.confirm),
            "dump": lambda: check_dump(connection, _wordpress(args, config), options=args.option),
            "load": lambda: check_load(
                connection,
                _wordpress(args, config),
                source=None if args.input == "-" else args.input,
                replace=args.replace,
                identities=_identities(args) or None,
                passphrase=_passphrase(args),
                options=args.option,
                allow_unsandboxed=args.allow_unsandboxed,
            ),
        }
        verdict = checks[operation]()
        _emit(verdict)
        return Exit.OK if verdict.ok else _refusal_exit(verdict)

    if operation == "inspect":
        state = inspect(connection, _wordpress(args, config))
        _emit({"state": str(state)})
        return Exit.OK if state.is_ready else Exit.NOT_READY
    if operation == "schema-version":
        version = schema_version(connection, _wordpress(args, config), prefix)
        _emit(
            {
                "db_version": getattr(version, "db_version", None),
                "release": getattr(version, "release", None),
            }
        )
        return Exit.OK
    if operation == "survey":
        _emit(
            survey(
                connection,
                _admin(args),
                wordpress_user=args.wordpress_user,
                user_host=args.user_host,
                table_prefix=prefix,
            )
        )
        return Exit.OK
    if operation == "ensure":
        _emit(ensure(connection, _admin(args), _wordpress(args, config), user_host=args.user_host))
        return Exit.OK
    if operation == "rotate-password":
        _emit(
            rotate_password(
                connection, _admin(args), _wordpress(args, config), user_host=args.user_host
            )
        )
        return Exit.OK
    if operation == "revoke":
        _emit(
            revoke(
                connection, _admin(args), args.user, user_host=args.user_host, confirm=args.confirm
            )
        )
        return Exit.OK
    if operation == "drop-user":
        _emit(
            drop_user(
                connection, _admin(args), args.user, user_host=args.user_host, confirm=args.confirm
            )
        )
        return Exit.OK
    if operation == "dump":
        target = sys.stdout.buffer if args.output == "-" else args.output
        recipients = args.recipient or None
        passphrase = _passphrase(args)
        if recipients and passphrase is not None:
            msg = "supply --recipient or a passphrase option, not both"
            raise InvalidArgumentsError(msg)
        result = dump(
            connection,
            _wordpress(args, config),
            target,
            recipients=recipients,
            passphrase=passphrase,
            options=args.option,
        )
        # With the dump on stdout, the result must not be mixed into it.
        _emit(result, stream=sys.stderr if args.output == "-" else sys.stdout)
        return Exit.OK
    if operation == "load":
        source = sys.stdin.buffer if args.input == "-" else args.input
        identities = _identities(args) or None
        passphrase = _passphrase(args)
        if identities and passphrase is not None:
            msg = "supply --identity or a passphrase option, not both"
            raise InvalidArgumentsError(msg)
        _emit(
            load(
                connection,
                _wordpress(args, config),
                source,
                replace=args.replace,
                identities=identities,
                passphrase=passphrase,
                options=args.option,
                allow_unsandboxed=args.allow_unsandboxed,
            )
        )
        return Exit.OK
    _emit(drop_database(connection, _admin(args), confirm=args.confirm))
    return Exit.OK


def _refusal_exit(verdict: Verdict) -> Exit:
    if Code.UNREACHABLE in verdict.codes:
        return Exit.UNREACHABLE
    if Code.CREDENTIALS_UNOBTAINABLE in verdict.codes:
        return Exit.CREDENTIALS
    return Exit.REFUSED


def main(argv: list[str] | None = None) -> int:
    """Run the command line interface."""
    args = build_parser().parse_args(argv)
    _configure_logging(args.log_level, args.log_format)
    try:
        return _run(args)
    except RefusedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return _refusal_exit(exc.verdict)
    except (CredentialsUnobtainableError, CredentialsAbsentError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return Exit.CREDENTIALS
    except DatabaseUnreachableError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return Exit.UNREACHABLE
    except (
        InvalidArgumentsError,
        InvalidIdentifierError,
        MissingDependencyError,
        ConfigurationError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return Exit.USAGE
    except DatabaseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return Exit.FAILED
