"""Command-line entry point for the separately installed Console service."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Sequence

from .infrastructure.persistence.bootstrap_authorization_file_authority import (
    BootstrapAuthorizationConfiguration,
)
from .infrastructure.persistence.first_run_composition import (
    FirstRunSqlIdentityConfiguration,
    build_first_run_sql_identity_app,
)
from .infrastructure.persistence.setup_window_configuration import (
    SetupWindowConfiguration,
)

_BIND_HOST_ENV = "SENTINEL_CONSOLE_BIND_HOST"
_PORT_ENV = "SENTINEL_CONSOLE_PORT"
_DEFAULT_BIND_HOST = "127.0.0.1"
_DEFAULT_PORT = 8000


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ASGI server or an explicit local setup-window operation."""
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "serve":
            return _serve()
        return _operate_setup_window(arguments.action)
    except Exception as error:
        print(f"sentinel-console: {error}", file=sys.stderr)
        return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sentinel-console")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="run the Console ASGI service")
    setup = commands.add_parser(
        "setup-window", help="inspect or explicitly change first-run availability"
    )
    setup.add_argument("action", choices=("status", "open", "close"))
    return parser


def _serve() -> int:
    configuration = FirstRunSqlIdentityConfiguration.from_environment()
    host = os.environ.get(_BIND_HOST_ENV, _DEFAULT_BIND_HOST)
    port = _parse_port(os.environ.get(_PORT_ENV, str(_DEFAULT_PORT)))
    if not host or host != host.strip():
        raise ValueError("Console bind host is invalid")
    try:
        import uvicorn
    except ImportError:
        raise RuntimeError(
            "install atlas-richie-sentinel-console[server] to run the CLI"
        ) from None

    app = build_first_run_sql_identity_app(configuration)
    # Keep the immediate peer visible to the app-owned CIDR resolver.
    uvicorn.run(app, host=host, port=port, proxy_headers=False)
    return 0


def _operate_setup_window(action: str) -> int:
    configuration = SetupWindowConfiguration.from_environment()
    store = configuration.create_store()
    snapshot = asyncio.run(store.read_snapshot())
    if action == "status":
        print("setup-window=open" if snapshot.is_open else "setup-window=closed")
        return 0

    if action == "open":
        # Refuse to open the browser grant without the operator credential source.
        BootstrapAuthorizationConfiguration.from_environment()
        if snapshot.is_open:
            print("setup-window=already-open")
            return 0
        asyncio.run(
            store.set_setup_window_open(
                True, expected_revision=snapshot.revision
            )
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


def main_entry() -> None:
    """Console-script adapter that returns the command status to the shell."""
    raise SystemExit(main())


__all__ = ["main", "main_entry"]
