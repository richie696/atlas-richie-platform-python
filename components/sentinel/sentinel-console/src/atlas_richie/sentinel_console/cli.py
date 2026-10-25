"""Command-line entry point for the separately installed Console service."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import ssl
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.engine import make_url
from starlette.applications import Starlette

from .application.expire_incident_history import ExpireIncidentHistory
from .application.metrics_ingest_ports import MetricsReporterBinding
from .application.recover_built_in_admin_password import (
    RecoverBuiltInAdminPassword,
)
from .infrastructure.persistence.bootstrap_authorization_file_authority import (
    BootstrapAuthorizationConfiguration,
    loopback_bootstrap_without_code_allowed,
)
from .infrastructure.persistence.database_runtime import (
    create_database_engine_from_locator,
)
from .infrastructure.persistence.first_run_composition import (
    FirstRunSqlIdentityConfiguration,
    build_first_run_sql_identity_app,
)
from .infrastructure.persistence.incident_event_adapter import (
    SQLAlchemyIncidentEventAdapter,
)
from .infrastructure.persistence.metrics_collector_composition import (
    build_metrics_collector_app,
)
from .infrastructure.persistence.metrics_reporter_admin_composition import (
    build_metrics_reporter_admin,
)
from .infrastructure.persistence.runtime_database_locator_configuration import (
    RuntimeDatabaseLocatorConfiguration,
)
from .infrastructure.persistence.setup_window_configuration import (
    SetupWindowConfiguration,
)
from .operator_documentation import available_documents, read_document

_BIND_HOST_ENV = "SENTINEL_CONSOLE_BIND_HOST"
_PORT_ENV = "SENTINEL_CONSOLE_PORT"
_WORKERS_ENV = "SENTINEL_CONSOLE_WORKERS"
_DEFAULT_BIND_HOST = "127.0.0.1"
_DEFAULT_PORT = 8000
_DEFAULT_WORKERS = 1
_WORKER_HEALTHCHECK_TIMEOUT_SECONDS = 30
_METRICS_BIND_HOST_ENV = "SENTINEL_CONSOLE_METRICS_BIND_HOST"
_METRICS_PORT_ENV = "SENTINEL_CONSOLE_METRICS_PORT"
_METRICS_SERVER_CERTIFICATE_ENV = "SENTINEL_CONSOLE_METRICS_SERVER_CERTIFICATE"
_METRICS_SERVER_PRIVATE_KEY_ENV = "SENTINEL_CONSOLE_METRICS_SERVER_PRIVATE_KEY"
_METRICS_CLIENT_CA_CERTIFICATE_ENV = "SENTINEL_CONSOLE_METRICS_CLIENT_CA_CERTIFICATE"
_DEFAULT_METRICS_BIND_HOST = "127.0.0.1"
_DEFAULT_METRICS_PORT = 8443


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ASGI server or an explicit local setup-window operation."""
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "serve":
            return _serve()
        if arguments.command == "serve-metrics":
            return _serve_metrics()
        if arguments.command == "metrics-reporter":
            return _manage_metrics_reporter(arguments)
        if arguments.command == "account" and arguments.action == "recover-admin":
            return _recover_built_in_admin_password()
        if arguments.command == "incident-events" and arguments.action == "expire":
            return _expire_incident_history()
        if arguments.command == "docs":
            return _show_documentation(arguments.document)
        return _operate_setup_window(arguments.action)
    except Exception as error:  # noqa: BLE001 - CLI boundary converts startup errors to exit status.
        print(f"sentinel-console: {error}", file=sys.stderr)
        return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sentinel-console")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="run the Console ASGI service")
    commands.add_parser(
        "serve-metrics", help="run the isolated mutual-TLS Metrics V2 Collector"
    )
    reporter = commands.add_parser(
        "metrics-reporter", help="manage Metrics V2 reporter enrollment"
    )
    reporter_operations = reporter.add_subparsers(dest="action", required=True)
    enroll = reporter_operations.add_parser(
        "enroll", help="enroll a reporter certificate fingerprint and scope"
    )
    enroll.add_argument("--principal", required=True)
    enroll.add_argument("--certificate-sha256", required=True)
    enroll.add_argument("--reporter-id", required=True)
    enroll.add_argument("--environment-id", required=True)
    enroll.add_argument("--app-id", required=True)
    enroll.add_argument("--instance-id", required=True)
    enroll.add_argument("--process-id", required=True)
    revoke = reporter_operations.add_parser(
        "revoke", help="revoke a reporter by certificate principal"
    )
    revoke.add_argument("--principal", required=True)
    account = commands.add_parser(
        "account", help="recover access to the built-in administrator account"
    )
    account_operations = account.add_subparsers(dest="action", required=True)
    account_operations.add_parser(
        "recover-admin",
        help="set a new password for the built-in admin from the local terminal",
    )
    incidents = commands.add_parser(
        "incident-events", help="maintain retained Incident Event history"
    )
    incident_operations = incidents.add_subparsers(dest="action", required=True)
    incident_operations.add_parser(
        "expire", help="delete Incident Event rows past their durable expiry"
    )
    docs = commands.add_parser(
        "docs", help="show the installed Console operator documentation"
    )
    docs.add_argument(
        "document",
        nargs="?",
        choices=tuple(name for name, _ in available_documents()),
        help="document to print (omit to list available documents)",
    )
    setup = commands.add_parser(
        "setup-window", help="inspect or explicitly change first-run availability"
    )
    setup.add_argument("action", choices=("status", "open", "close"))
    return parser


def _show_documentation(document: str | None) -> int:
    """Print a bundled guide or list the available installed references."""
    if document is None:
        print("Available Sentinel Console documentation:")
        for name, description in available_documents():
            print(f"  {name:<12} {description}")
        print("Use `sentinel-console docs <name>` to print a document.")
        return 0

    print(read_document(document), end="")
    return 0


def _serve() -> int:
    host = os.environ.get(_BIND_HOST_ENV, _DEFAULT_BIND_HOST)
    port = _parse_port(os.environ.get(_PORT_ENV, str(_DEFAULT_PORT)))
    workers = _parse_worker_count(os.environ.get(_WORKERS_ENV, str(_DEFAULT_WORKERS)))
    if not host or host != host.strip():
        raise ValueError("Console bind host is invalid")

    # Validate deployment configuration before Uvicorn starts or forks workers.
    FirstRunSqlIdentityConfiguration.from_environment()
    try:
        import uvicorn
    except ImportError:
        raise RuntimeError(
            "install atlas-richie-sentinel-console[server] to run the CLI"
        ) from None

    # Keep the immediate peer visible to the app-owned CIDR resolver.
    # Uvicorn requires an import string for worker processes. Each worker then
    # creates its own app and lifecycle while sharing the deployment SQL store.
    uvicorn.run(
        "atlas_richie.sentinel_console.cli:create_application",
        factory=True,
        host=host,
        port=port,
        workers=workers,
        proxy_headers=False,
        # First-run requests perform network policy checks and database schema
        # migrations before a selected runtime engine exists. Uvicorn's short
        # default can otherwise kill a worker while that bounded setup request
        # is still in flight.
        timeout_worker_healthcheck=_WORKER_HEALTHCHECK_TIMEOUT_SECONDS,
    )
    return 0


def create_application() -> Starlette:
    """Create one first-run ASGI app in the process that serves it.

    Uvicorn calls this factory independently in each worker. Deployment-owned
    file authorities must therefore be on a shared local POSIX filesystem and
    SQL authorities must point to the same database; NFS and multi-host sharing
    are outside this factory's contract.
    """
    configuration = FirstRunSqlIdentityConfiguration.from_environment()
    return build_first_run_sql_identity_app(configuration)


def _serve_metrics() -> int:
    """Run an isolated ASGI Collector whose listener requires client TLS."""
    host = os.environ.get(_METRICS_BIND_HOST_ENV, _DEFAULT_METRICS_BIND_HOST)
    port = _parse_port(os.environ.get(_METRICS_PORT_ENV, str(_DEFAULT_METRICS_PORT)))
    if not host or host != host.strip():
        raise ValueError("Metrics Collector bind host is invalid")

    certificate_path = _required_absolute_file(_METRICS_SERVER_CERTIFICATE_ENV)
    private_key_path = _required_absolute_file(_METRICS_SERVER_PRIVATE_KEY_ENV)
    client_ca_path = _required_absolute_file(_METRICS_CLIENT_CA_CERTIFICATE_ENV)
    postgresql_root_certificate = _optional_absolute_file(
        "SENTINEL_CONSOLE_POSTGRESQL_ROOT_CERTIFICATE"
    )
    mysql_root_certificate = _optional_absolute_file(
        "SENTINEL_CONSOLE_MYSQL_ROOT_CERTIFICATE"
    )
    locator_configuration = RuntimeDatabaseLocatorConfiguration.from_environment()
    app = build_metrics_collector_app(
        locator_configuration,
        postgresql_root_certificate=(
            str(postgresql_root_certificate)
            if postgresql_root_certificate is not None
            else None
        ),
        mysql_ssl_context=ssl.create_default_context(
            cafile=(
                str(mysql_root_certificate)
                if mysql_root_certificate is not None
                else None
            )
        ),
    )

    try:
        import anyio
        from anycorn import serve
        from anycorn.config import Config
    except ImportError:
        raise RuntimeError(
            "install atlas-richie-sentinel-console[collector] to run the Metrics Collector"
        ) from None

    server_configuration = Config()
    server_configuration.bind = [f"{host}:{port}"]
    server_configuration.certfile = str(certificate_path)
    server_configuration.keyfile = str(private_key_path)
    server_configuration.ca_certs = str(client_ca_path)
    server_configuration.verify_mode = ssl.CERT_REQUIRED
    server_configuration.alpn_protocols = ["h2", "http/1.1"]
    anyio.run(serve, app, server_configuration)
    return 0


def _manage_metrics_reporter(arguments: argparse.Namespace) -> int:
    """Run one durable reporter identity operation using the selected SQL DB."""
    locator_configuration = RuntimeDatabaseLocatorConfiguration.from_environment()
    postgresql_root_certificate = _optional_absolute_file(
        "SENTINEL_CONSOLE_POSTGRESQL_ROOT_CERTIFICATE"
    )
    mysql_root_certificate = _optional_absolute_file(
        "SENTINEL_CONSOLE_MYSQL_ROOT_CERTIFICATE"
    )
    management, runtime_provider = build_metrics_reporter_admin(
        locator_configuration,
        postgresql_root_certificate=(
            str(postgresql_root_certificate)
            if postgresql_root_certificate is not None
            else None
        ),
        mysql_ssl_context=ssl.create_default_context(
            cafile=(
                str(mysql_root_certificate)
                if mysql_root_certificate is not None
                else None
            )
        ),
    )

    async def operate() -> int:
        try:
            if not await runtime_provider.start():
                raise RuntimeError("Console runtime database is not configured")
            if arguments.action == "enroll":
                binding = MetricsReporterBinding(
                    certificate_principal=arguments.principal,
                    certificate_sha256=arguments.certificate_sha256,
                    reporter_id=arguments.reporter_id,
                    environment_id=arguments.environment_id,
                    app_id=arguments.app_id,
                    instance_id=arguments.instance_id,
                    process_id=arguments.process_id,
                )
                await management.enroll(binding)
                print("reporter-enrolled")
                return 0

            if await management.revoke(arguments.principal):
                print("reporter-revoked")
                return 0
            print("reporter-not-found")
            return 1
        finally:
            await runtime_provider.dispose()

    return asyncio.run(operate())


def _expire_incident_history() -> int:
    """Run one incident-expiration pass without applying database migrations."""
    locator_configuration = RuntimeDatabaseLocatorConfiguration.from_environment()
    postgresql_root_certificate = _optional_absolute_file(
        "SENTINEL_CONSOLE_POSTGRESQL_ROOT_CERTIFICATE"
    )
    mysql_root_certificate = _optional_absolute_file(
        "SENTINEL_CONSOLE_MYSQL_ROOT_CERTIFICATE"
    )

    async def operate() -> int:
        locator = await locator_configuration.create_store().read()
        if locator is None:
            raise RuntimeError("Console runtime database is not configured")
        engine = create_database_engine_from_locator(
            locator,
            postgresql_root_certificate=(
                str(postgresql_root_certificate)
                if postgresql_root_certificate is not None
                else None
            ),
            mysql_ssl_context=ssl.create_default_context(
                cafile=(
                    str(mysql_root_certificate)
                    if mysql_root_certificate is not None
                    else None
                )
            ),
        )

        async def resolve_engine() -> AsyncEngine:
            return engine

        try:
            retention = ExpireIncidentHistory(
                SQLAlchemyIncidentEventAdapter(resolve_engine)
            )
            return await retention.execute(datetime.now(UTC))
        finally:
            await engine.dispose()

    expired_count = asyncio.run(operate())
    print(f"expired-incidents={expired_count}")
    return 0


def _recover_built_in_admin_password() -> int:
    """Recover the built-in admin through a confirmed local terminal session."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise RuntimeError("administrator recovery requires an interactive terminal")
    locator_configuration = RuntimeDatabaseLocatorConfiguration.from_environment()
    postgresql_root_certificate = _optional_absolute_file(
        "SENTINEL_CONSOLE_POSTGRESQL_ROOT_CERTIFICATE"
    )
    mysql_root_certificate = _optional_absolute_file(
        "SENTINEL_CONSOLE_MYSQL_ROOT_CERTIFICATE"
    )

    async def operate() -> int:
        locator = await locator_configuration.create_store().read()
        if locator is None:
            raise RuntimeError("Console runtime database is not configured")

        database = make_url(locator.database_url)
        if database.get_backend_name() == "sqlite":
            target = f"{database.drivername}://{database.database}"
        else:
            host = database.host or "(socket/default)"
            port = f":{database.port}" if database.port is not None else ""
            name = f"/{database.database}" if database.database else ""
            target = f"{database.get_backend_name()}://{host}{port}{name}"
        print(f"Database target: {target}")
        if input("Type RECOVER to reset the built-in admin password: ") != "RECOVER":
            print("recovery-cancelled")
            return 1

        password = getpass.getpass("New admin password (8–32 characters): ")
        confirmation = getpass.getpass("Confirm new admin password: ")
        if password != confirmation:
            raise ValueError("password confirmation does not match")

        engine = create_database_engine_from_locator(
            locator,
            postgresql_root_certificate=(
                str(postgresql_root_certificate)
                if postgresql_root_certificate is not None
                else None
            ),
            mysql_ssl_context=ssl.create_default_context(
                cafile=(
                    str(mysql_root_certificate)
                    if mysql_root_certificate is not None
                    else None
                )
            ),
        )
        try:
            from .infrastructure.persistence.built_in_admin_password_recovery_store import (
                LocalBuiltInAdminPasswordRecoveryStore,
            )
            from .infrastructure.security.password_hash import PasswordHashService

            recovery = RecoverBuiltInAdminPassword(
                store=LocalBuiltInAdminPasswordRecoveryStore(engine),
                password_hasher=PasswordHashService(),
            )
            result = await recovery.execute(
                password=password,
                now=datetime.now(UTC),
                event_id=str(uuid4()),
                request_id=str(uuid4()),
            )
        finally:
            await engine.dispose()

        print(
            f"admin-password-recovered username={result.username} "
            f"revoked-sessions={result.revoked_sessions}"
        )
        return 0

    return asyncio.run(operate())


def _required_absolute_file(environment_name: str) -> Path:
    value = os.environ.get(environment_name)
    if not value:
        raise ValueError("Metrics Collector TLS configuration is incomplete")
    path = Path(value)
    if not path.is_absolute() or not path.is_file():
        raise ValueError("Metrics Collector TLS file must be an existing absolute path")
    try:
        with path.open("rb"):
            pass
    except OSError:
        raise ValueError("Metrics Collector TLS file is not readable") from None
    return path


def _optional_absolute_file(environment_name: str) -> Path | None:
    value = os.environ.get(environment_name)
    if value is None:
        return None
    path = Path(value)
    if not path.is_absolute() or not path.is_file():
        raise ValueError(
            "configured database CA file must be an existing absolute path"
        )
    try:
        with path.open("rb"):
            pass
    except OSError:
        raise ValueError("configured database CA file is not readable") from None
    return path


def _operate_setup_window(action: str) -> int:
    configuration = SetupWindowConfiguration.from_environment()
    store = configuration.create_store()
    snapshot = asyncio.run(store.read_snapshot())
    if action == "status":
        print("setup-window=open" if snapshot.is_open else "setup-window=closed")
        return 0

    if action == "open":
        # Refuse to open the browser grant without the operator credential source.
        BootstrapAuthorizationConfiguration.from_environment(
            allow_loopback_without_code=loopback_bootstrap_without_code_allowed(
                os.environ
            )
        )
        if snapshot.is_open:
            print("setup-window=already-open")
            return 0
        asyncio.run(
            store.set_setup_window_open(True, expected_revision=snapshot.revision)
        )
        print("setup-window=open")
        return 0

    asyncio.run(store.close_setup_window_if_open())
    print("setup-window=closed")
    return 0


def _parse_port(value: str) -> int:
    if not value.isascii() or not value.isdecimal() or len(value) > 5:
        raise ValueError("Console port is invalid")
    port = int(value)
    if not 1 <= port <= 65_535:
        raise ValueError("Console port is invalid")
    return port


def _parse_worker_count(value: str) -> int:
    if not value.isascii() or not value.isdecimal() or len(value) > 5:
        raise ValueError("Console worker count is invalid")
    workers = int(value)
    if workers < 1:
        raise ValueError("Console worker count is invalid")
    return workers


def main_entry() -> None:
    """Console-script adapter that returns the command status to the shell."""
    raise SystemExit(main())


__all__ = ["create_application", "main", "main_entry"]
