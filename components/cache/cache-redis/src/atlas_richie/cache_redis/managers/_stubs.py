"""NotImplementedError stubs for the `ProviderRegistrar` methods.

All methods are now real. This file remains as a placeholder for
future expansion; it is no longer imported by `redis_provider_registrar.py`.
"""

from __future__ import annotations

from typing import Any

from ..errors import StateError


def _not_implemented(method: str, milestone: str) -> StateError:
    return StateError(
        f"{method} is not yet implemented in atlas-richie-cache-redis. "
        f"Tracked in {milestone}."
    )


class _NotImplementedOps:
    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)

        def _raise(*args: Any, **kwargs: Any) -> Any:
            raise _not_implemented(
                f"{type(self).__name__}.{name}",
                "future R-###",
            )

        return _raise


class _NotImplementedFunction(_NotImplementedOps):
    pass


__all__: list[str] = []

