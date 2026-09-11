"""Cooperative MCP cancellation values independent of a framework task runtime."""

from __future__ import annotations

from threading import Event


class McpInvocationCancelled(Exception):
    """A handler explicitly observed that its remote caller cancelled the request."""


class CancellationToken:
    """A thread-safe, cooperative cancellation signal owned by one MCP invocation."""

    def __init__(self) -> None:
        self._event = Event()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def throw_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise McpInvocationCancelled("MCP invocation was cancelled")
