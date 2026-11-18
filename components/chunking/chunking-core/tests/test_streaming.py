"""Streaming chunking session tests.

Behaviour is additionally pinned by a 120-session randomised differential run
against the compiled Java `StreamingChunker` (byte-identical chunk sequences,
including a double-`finish()` idempotence probe).
"""

from __future__ import annotations

import pytest

from atlas_richie.chunking_core import (
    ChunkingRule,
    DefaultChunkingService,
    Strategy,
    StreamingChunker,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def service() -> DefaultChunkingService:
    return DefaultChunkingService()


def _chunker(service, strategy=Strategy.FIXED, max_chars=5, overlap=0, **kwargs):
    return StreamingChunker(
        service, ChunkingRule("r", "1", strategy, max_chars, overlap), **kwargs
    )


class TestSessionLifecycle:
    def test_accept_below_threshold_emits_nothing(self, service) -> None:
        chunker = _chunker(service)
        assert chunker.accept("abc") == []
        assert chunker.pending_characters == 3

    def test_finish_flushes_tail(self, service) -> None:
        chunker = _chunker(service)
        chunker.accept("abc")
        flushed = chunker.finish()
        assert [(c.ordinal, c.char_start, c.char_end, c.text) for c in flushed] == [
            (0, 0, 3, "abc")
        ]

    def test_finish_is_idempotent(self, service) -> None:
        chunker = _chunker(service)
        chunker.accept("abc")
        assert len(chunker.finish()) == 1
        assert chunker.finish() == []
        assert chunker.finish() == []

    def test_accept_after_finish_raises(self, service) -> None:
        chunker = _chunker(service)
        chunker.finish()
        with pytest.raises(RuntimeError, match="已结束"):
            chunker.accept("more")

    def test_abort_discards_tail_and_closes(self, service) -> None:
        chunker = _chunker(service)
        chunker.accept("abc")
        chunker.abort()
        assert chunker.finished is True
        assert chunker.finish() == []
        with pytest.raises(RuntimeError):
            chunker.accept("more")

    def test_blank_and_none_sections_short_circuit(self, service) -> None:
        chunker = _chunker(service)
        assert chunker.accept(None) == []
        assert chunker.accept("") == []
        assert chunker.accept("   \t ") == []
        assert chunker.pending_characters == 0
        assert chunker.finish() == []


class TestConstructionGuards:
    def test_semantic_without_advisor_rejected_by_factory(self, service) -> None:
        with pytest.raises(NotImplementedError, match="SEMANTIC"):
            _chunker(service, strategy=Strategy.SEMANTIC)

    def test_semantic_with_advisor_rejected_as_non_streaming(self) -> None:
        class _Advisor:
            def boundaries(self, content: str) -> list[int]:
                return []

        service = DefaultChunkingService(semantic_boundary_advisor=_Advisor())
        with pytest.raises(ValueError, match="不支持流式"):
            _chunker(service, strategy=Strategy.SEMANTIC)

    def test_pending_limit_below_max_rejected(self, service) -> None:
        with pytest.raises(ValueError, match="至少容纳一个 Chunk"):
            _chunker(service, max_chars=10, max_pending_characters=9)

    def test_service_without_strategy_resolver_rejected(self) -> None:
        class _Plain:
            def chunk(self, content, rule=None):
                raise AssertionError("should not be reached")

        with pytest.raises(ValueError, match="策略工厂"):
            StreamingChunker(_Plain(), ChunkingRule("r", "1", Strategy.FIXED, 5, 0))

    def test_default_pending_limit_is_max_plus_overlap(self, service) -> None:
        chunker = _chunker(service, max_chars=5, overlap=2)
        assert chunker._max_pending == 7


class TestCoordinatesAndOverlap:
    def test_zero_overlap_is_contiguous_without_separator(self, service) -> None:
        """When the buffer empties, no '\\n' is inserted between sections."""
        chunker = _chunker(service, max_chars=5, overlap=0)
        emitted = [*chunker.accept("abcde"), *chunker.accept("fghij"), *chunker.finish()]
        assert [(c.ordinal, c.char_start, c.char_end, c.text) for c in emitted] == [
            (0, 0, 5, "abcde"),
            (1, 5, 10, "fghij"),
        ]

    def test_inserted_separator_counts_toward_global_offsets(self, service) -> None:
        """With a retained overlap tail, accept inserts '\\n' and it IS counted.

        Session text is "abcde" + "\\n" + "fghij" = 11 characters, so the final
        chunk ends at 11 — not at the 10 characters the caller supplied.
        """
        chunker = _chunker(service, max_chars=5, overlap=2)
        emitted = [*chunker.accept("abcde"), *chunker.accept("fghij"), *chunker.finish()]
        assert [(c.ordinal, c.char_start, c.char_end, c.text) for c in emitted] == [
            (0, 0, 5, "abcde"),
            (1, 3, 8, "de\nfg"),
            (2, 6, 11, "fghij"),
        ]

    def test_adjacent_intersection_equals_configured_overlap(self, service) -> None:
        chunker = _chunker(service, max_chars=5, overlap=2)
        emitted = [*chunker.accept("abcde"), *chunker.accept("fghij")]
        first, second = emitted[0], emitted[1]
        intersection = max(0, min(first.char_end, second.char_end) - max(first.char_start, second.char_start))
        assert intersection == 2

    def test_ordinals_are_continuous_across_drains(self, service) -> None:
        chunker = _chunker(service, max_chars=4, overlap=1)
        emitted = []
        for section in ["abcdefgh", "ijklmnop", "qrstuvwx"]:
            emitted.extend(chunker.accept(section))
        emitted.extend(chunker.finish())
        assert [c.ordinal for c in emitted] == list(range(len(emitted)))
        assert len(emitted) > 3, "the fixture should span several drains"

    def test_every_strategy_streams(self, service) -> None:
        text_sections = ["# Title\nbody text here", "another paragraph.\n\nmore content!"]
        for strategy in Strategy:
            if strategy is Strategy.SEMANTIC:
                continue
            chunker = _chunker(service, strategy=strategy, max_chars=12, overlap=3)
            emitted = []
            for section in text_sections:
                emitted.extend(chunker.accept(section))
            emitted.extend(chunker.finish())
            assert emitted, f"{strategy} produced nothing"
            assert [c.ordinal for c in emitted] == list(range(len(emitted)))


class TestBufferBound:
    def test_large_section_does_not_grow_buffer_unboundedly(self, service) -> None:
        """The drain loop always reduces pending below max_characters.

        The inherited `max_pending` guard is therefore defensive rather than
        reachable: the constructor already requires max_pending >= max_characters,
        and the loop exits only when pending < max_characters. Java has the same
        redundancy. This pins the bounded-buffer behaviour, not the guard.
        """
        chunker = _chunker(service, max_chars=5, overlap=4)
        chunker.accept("x" * 500)
        assert chunker.pending_characters < 5
