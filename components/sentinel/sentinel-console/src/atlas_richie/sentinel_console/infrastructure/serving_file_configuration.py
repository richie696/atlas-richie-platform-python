"""TOML configuration-file resolution for the Console serve entry point.

The file carries only non-secret operational parameters: the bind address,
the HTTP port and the worker count.  Secrets and deployment-injected values
(database locators, key rings, operator code) stay in the process
environment, so a configuration file can never widen what a deployment
exposes.  File values are never injected into os.environ; instead the
serve entry point exports the *resolved* bind address, because the
import-time loopback security gates read the binding from the environment.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path

BIND_HOST_ENVIRONMENT = "SENTINEL_CONSOLE_BIND_HOST"
PORT_ENVIRONMENT = "SENTINEL_CONSOLE_PORT"
WORKERS_ENVIRONMENT = "SENTINEL_CONSOLE_WORKERS"
DEFAULT_BIND_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_WORKERS = 1

_ALLOWED_FILE_KEYS = ("bind_host", "port", "workers")


@dataclass(frozen=True)
class ServingConfiguration:
    """Resolved serve parameters after command line, environment, file, defaults."""

    bind_host: str
    port: int
    workers: int


def parse_port_text(value: str) -> int:
    """Validate one decimal port string; identical to the historical env parsing."""
    if not value.isascii() or not value.isdecimal() or len(value) > 5:
        raise ValueError("Console port is invalid")
    port = int(value)
    if not 1 <= port <= 65_535:
        raise ValueError("Console port is invalid")
    return port


def parse_worker_count_text(value: str) -> int:
    """Validate one decimal worker-count string; identical to the historical parsing."""
    if not value.isascii() or not value.isdecimal() or len(value) > 5:
        raise ValueError("Console worker count is invalid")
    workers = int(value)
    if workers < 1:
        raise ValueError("Console worker count is invalid")
    return workers


def read_serving_file(path: Path) -> Mapping[str, object]:
    """Read and schema-check one TOML serving configuration file.

    Unknown keys are rejected so a typo fails startup with the file path
    instead of silently falling back to a default value.
    """
    if not path.is_file():
        raise ValueError(f"Console configuration file does not exist: {path}")
    try:
        with path.open("rb") as handle:
            document = tomllib.load(handle)
    except tomllib.TOMLDecodeError as error:
        raise ValueError(
            f"Console configuration file is not valid TOML: {path} ({error})"
        ) from None
    except OSError as error:
        raise ValueError(
            f"Console configuration file is not readable: {path} ({error})"
        ) from None
    unknown = sorted(key for key in document if key not in _ALLOWED_FILE_KEYS)
    if unknown:
        allowed = ", ".join(_ALLOWED_FILE_KEYS)
        raise ValueError(
            f"Console configuration file {path}: unknown keys "
            f"{', '.join(unknown)}; allowed keys are {allowed}"
        )
    return document


def _validate_bind_host(value: object, origin: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"Console bind host is invalid ({origin})")
    return value


def _validate_port(value: object, origin: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= 65_535
    ):
        raise ValueError(f"Console port is invalid ({origin})")
    return value


def _validate_worker_count(value: object, origin: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"Console worker count is invalid ({origin})")
    return value


def resolve_serving_configuration(
    *,
    cli_bind_host: str | None = None,
    cli_port: int | None = None,
    cli_workers: int | None = None,
    config_path: Path | None = None,
    environ: Mapping[str, str],
) -> ServingConfiguration:
    """Resolve serve parameters with the frozen precedence.

    For every parameter: the command line beats the environment, the
    environment beats the configuration file, and the file beats the
    built-in default.  The environment therefore remains the deployment
    injection channel that can always override the file.
    """
    file_values: Mapping[str, object] = (
        read_serving_file(config_path) if config_path is not None else {}
    )

    if cli_bind_host is not None:
        bind_host = _validate_bind_host(cli_bind_host, "command line")
    elif BIND_HOST_ENVIRONMENT in environ:
        bind_host = _validate_bind_host(
            environ[BIND_HOST_ENVIRONMENT], "environment"
        )
    elif "bind_host" in file_values:
        bind_host = _validate_bind_host(
            file_values["bind_host"], f"file {config_path}"
        )
    else:
        bind_host = DEFAULT_BIND_HOST

    if cli_port is not None:
        port = _validate_port(cli_port, "command line")
    elif PORT_ENVIRONMENT in environ:
        port = parse_port_text(environ[PORT_ENVIRONMENT])
    elif "port" in file_values:
        port = _validate_port(file_values["port"], f"file {config_path}")
    else:
        port = DEFAULT_PORT

    if cli_workers is not None:
        workers = _validate_worker_count(cli_workers, "command line")
    elif WORKERS_ENVIRONMENT in environ:
        workers = parse_worker_count_text(environ[WORKERS_ENVIRONMENT])
    elif "workers" in file_values:
        workers = _validate_worker_count(
            file_values["workers"], f"file {config_path}"
        )
    else:
        workers = DEFAULT_WORKERS

    return ServingConfiguration(bind_host=bind_host, port=port, workers=workers)


def export_resolved_bind_host(
    configuration: ServingConfiguration, environ: MutableMapping[str, str]
) -> None:
    """Publish the resolved bind address to the process environment.

    The loopback security gates (the non-Secure cookie policy and the
    code-free bootstrap authorization) read SENTINEL_CONSOLE_BIND_HOST when
    route modules import.  Exporting the resolved value — after the
    environment has already had its chance to win the precedence — keeps
    those gates truthful when the binding comes from the file or the command
    line.  This publishes the final decision, never a raw file value, and is
    the only place the serving configuration writes to the environment.
    """
    environ[BIND_HOST_ENVIRONMENT] = configuration.bind_host


__all__ = [
    "BIND_HOST_ENVIRONMENT",
    "DEFAULT_BIND_HOST",
    "DEFAULT_PORT",
    "DEFAULT_WORKERS",
    "PORT_ENVIRONMENT",
    "ServingConfiguration",
    "WORKERS_ENVIRONMENT",
    "export_resolved_bind_host",
    "parse_port_text",
    "parse_worker_count_text",
    "read_serving_file",
    "resolve_serving_configuration",
]
