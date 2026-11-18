"""pytest integration for the shared test helpers.

Import this module only from test code: it imports pytest. The package's
`__init__` deliberately exposes only the framework-free helpers so that importing
`atlas_richie.testing` never requires pytest.
"""

from __future__ import annotations

import pytest

from .network import tcp_reachable


def skip_unless_reachable(
    url: str, service: str, *, default_port: int = 6379, env_hint: str | None = None
) -> None:
    """Skip the calling test when a service's TCP port is not open.

    Use inside a fixture so the whole dependent group skips cleanly instead of
    erroring on machines without the service (and in CI, which has none).
    """
    if tcp_reachable(url, default_port=default_port):
        return
    hint = f"; set {env_hint} or start {service}" if env_hint else f"; start {service}"
    pytest.skip(f"{service} not reachable at {url}{hint}")


__all__ = ["skip_unless_reachable"]
