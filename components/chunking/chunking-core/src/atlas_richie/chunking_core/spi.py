"""Caller-supplied SPIs. The core defines contracts only; implementations are injected.

Keeping these as `Protocol`s means the core carries no tokenizer or model
dependency: a caller wires tiktoken, a model SDK, or an embedding service
without this package depending on any of them.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class TokenCounter(Protocol):
    """Counts model tokens for a text window.

    Contract: deterministic for the same input (caching recommended), returns 0
    for empty text rather than raising, stateless and safe to call concurrently.
    The TOKEN strategy calls it repeatedly during a binary search, so the same
    prefix may be counted many times.
    """

    def count(self, text: str) -> int: ...


@runtime_checkable
class SemanticBoundaryAdvisor(Protocol):
    """Suggests character offsets where a new semantic segment should start.

    Contract: offsets are 0-based relative to the full content and must satisfy
    `0 < value < len(content)`; out-of-range values are filtered by the core.
    Returning an empty sequence means "no opinion" and the core falls back to
    the deterministic RECURSIVE strategy. Ordering and deduplication are handled
    by the core, so the advisor need not sort.
    """

    def boundaries(self, content: str) -> list[int]: ...


__all__ = ["SemanticBoundaryAdvisor", "TokenCounter"]
