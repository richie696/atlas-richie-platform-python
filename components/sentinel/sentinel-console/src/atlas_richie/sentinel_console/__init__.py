"""Independent Sentinel control-plane Console service."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .app import build_app

__all__ = ["build_app"]


def __getattr__(name: str) -> Any:
    """Load the ASGI factory only when an application entrypoint requests it."""
    if name == "build_app":
        from .app import build_app

        return build_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
