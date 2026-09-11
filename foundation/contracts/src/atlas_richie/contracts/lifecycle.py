"""Minimal lifecycle protocols shared across components."""

from typing import Protocol


class AsyncCloseable(Protocol):
    """A resource whose close operation can be awaited and is idempotent."""

    async def aclose(self) -> None:
        """Release resources without raising for repeated close calls."""
