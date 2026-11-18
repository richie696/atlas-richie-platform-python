"""pytest integration for the shared test helpers.

Import this module only from test code: it imports pytest. The package's
`__init__` deliberately exposes only the framework-free helpers so that importing
`atlas_richie.testing` never requires pytest.
"""

from __future__ import annotations

from typing import Callable

import pytest

from .network import tcp_reachable


def skip_unless_reachable(
    url: str,
    service: str,
    *,
    default_port: int = 6379,
    env_hint: str | None = None,
    probe: Callable[[str], bool] | None = None,
) -> None:
    """Skip the calling test when a service is not usable.

    Use inside a fixture so the whole dependent group skips cleanly instead of
    erroring on machines without the service (and in CI, which has none).

    An open TCP port is not enough: a server that requires authentication, or
    lacks a needed extension, is reachable but unusable. Pass `probe` to check
    readiness (e.g. a Redis PING); a probe that raises counts as not ready.
    """
    if tcp_reachable(url, default_port=default_port) and _ready(probe, url):
        return
    hint = f"; set {env_hint} or start {service}" if env_hint else f"; start {service}"
    pytest.skip(f"{service} not reachable at {url}{hint}")


def _ready(probe: Callable[[str], bool] | None, url: str) -> bool:
    if probe is None:
        return True
    try:
        return bool(probe(url))
    except Exception:  # noqa: BLE001 — an unusable server must skip, not error
        return False


__all__ = ["skip_unless_reachable"]
