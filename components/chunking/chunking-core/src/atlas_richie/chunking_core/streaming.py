"""Incremental streaming chunking sessions.

Ported from `cn.richie696.component.chunking.StreamingChunker` (Java). Reuses the
batch strategies' `boundary_at_or_before`, so no strategy changes were needed.

Coordinate contract (important): `accept` inserts a `'\n'` between non-empty
sections to avoid gluing them together, and that separator **is counted in the
global offsets**. Chunk coordinates are therefore relative to the text the
session saw (original sections plus inserted separators), not to a naive
concatenation of the caller's sections.

Overlap correctness: each drain consumes only `end - overlap_characters`, leaving
the overlap tail in the buffer as the prefix of the next chunk. The intersection
of adjacent chunks is thus exactly the configured overlap, rather than an
implicit "previous tail + new text" overlap.
"""

from __future__ import annotations

from ._text import is_blank
from .model import Chunk, ChunkingResult, ChunkingRule
from .strategies import ChunkingStrategy


class StreamingChunker:
    """A single-document streaming session over a batch chunking service."""

    def __init__(
        self,
        service,
        rule: ChunkingRule,
        max_pending_characters: int | None = None,
    ) -> None:
        if service is None or rule is None:
            raise ValueError("chunkingService and rule must not be null")
        resolver = getattr(service, "strategy", None)
        if resolver is None:
            raise ValueError("流式切片需要由策略工厂驱动的 ChunkingService")
        strategy: ChunkingStrategy = resolver(rule)
        if not strategy.supports_streaming:
            raise ValueError(f"策略不支持流式切片: {rule.strategy}")
        boundary = getattr(strategy, "boundary_at_or_before", None)
        if boundary is None:
            raise ValueError(f"策略不支持流式切片: {rule.strategy}")

        limit = (
            max_pending_characters
            if max_pending_characters is not None
            else rule.max_characters + rule.overlap_characters
        )
        if limit < rule.max_characters:
            raise ValueError("maxPendingCharacters 必须至少容纳一个 Chunk")

        self._service = service
        self._rule = rule
        self._strategy = strategy
        self._max_pending = limit
        self._pending = ""
        self._next_ordinal = 0
        self._pending_start_offset = 0
        self._last_emitted_end = 0
        self._finished = False

    @property
    def finished(self) -> bool:
        return self._finished

    @property
    def pending_characters(self) -> int:
        return len(self._pending)

    def accept(self, section: str | None) -> list[Chunk]:
        """Append a section and emit every chunk whose boundary is now determined."""
        self._ensure_open()
        if section is None or is_blank(section):
            return []
        if self._pending:
            self._pending += "\n"
        self._pending += section
        return self._drain()

    def finish(self) -> list[Chunk]:
        """Flush the tail. Idempotent: only the first call produces output."""
        if self._finished:
            return []
        self._finished = True
        if not self._pending:
            return []
        output = self._map_emitted(self._service.chunk(self._pending, self._rule))
        self._pending_start_offset += len(self._pending)
        self._pending = ""
        return output

    def abort(self) -> None:
        """Discard the unemitted tail and close the session."""
        self._finished = True
        self._pending_start_offset += len(self._pending)
        self._pending = ""

    def _drain(self) -> list[Chunk]:
        output: list[Chunk] = []
        while len(self._pending) >= self._rule.max_characters:
            end = self._strategy.boundary_at_or_before(
                self._pending, self._rule, self._rule.max_characters
            )
            if end <= 0:
                end = self._rule.max_characters
            output.extend(
                self._map_emitted(self._service.chunk(self._pending[:end], self._rule))
            )
            # Keep the overlap tail buffered as the next chunk's prefix; consume at
            # least one character so overlap == end cannot spin forever.
            consumed = max(1, end - self._rule.overlap_characters)
            self._pending = self._pending[consumed:]
            self._pending_start_offset += consumed
        if len(self._pending) > self._max_pending:
            raise RuntimeError(f"流式切片缓冲区超过上限: {self._max_pending}")
        return output

    def _map_emitted(self, result: ChunkingResult) -> list[Chunk]:
        output: list[Chunk] = []
        for chunk in result.chunks:
            start = self._pending_start_offset + chunk.char_start
            end = self._pending_start_offset + chunk.char_end
            # A tail chunk already emitted by a previous drain can reappear in the
            # next local slice because of the retained overlap; drop it.
            if end <= self._last_emitted_end:
                continue
            output.append(Chunk(self._next_ordinal, chunk.text, start, end))
            self._next_ordinal += 1
            self._last_emitted_end = max(self._last_emitted_end, end)
        return output

    def _ensure_open(self) -> None:
        if self._finished:
            raise RuntimeError("流式切片会话已结束，不能继续接收内容")


__all__ = ["StreamingChunker"]
