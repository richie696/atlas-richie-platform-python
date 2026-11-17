"""Chunking contract tests.

Expectations are ported from the Java module's own test suite
(`DefaultChunkingServiceTest`, `DefaultChunkingServiceApproximateTokenCounterTest`,
`SemanticChunkingServiceTest`) so the two implementations are pinned to the same
behaviour rather than to whatever the Python port happens to do.
"""

from __future__ import annotations

import pytest

from atlas_richie.chunking_core import (
    Chunk,
    ChunkingDiagnostics,
    ChunkingResult,
    ChunkingRule,
    ChunkingSignal,
    ChunkLimitExceededError,
    DefaultChunkingService,
    SemanticBoundaryException,
    SemanticChunkingOptions,
    SemanticChunkingService,
    SemanticFailureMode,
    Strategy,
    approximate_token_counter,
)

pytestmark = pytest.mark.unit


def assert_chunk_invariants(chunks: tuple[Chunk, ...], original: str) -> None:
    assert chunks
    for expected_ordinal, chunk in enumerate(chunks):
        assert chunk.ordinal == expected_ordinal, "ordinal must increase by 1 from 0"
        assert chunk.text
        assert 0 <= chunk.char_start <= chunk.char_end
        assert original[chunk.char_start : chunk.char_end] == chunk.text, (
            "text must equal the source slice [char_start, char_end)"
        )


@pytest.fixture
def service() -> DefaultChunkingService:
    return DefaultChunkingService()


class TestStrategyMatrix:
    def test_fixed_respects_max_characters(self, service: DefaultChunkingService) -> None:
        text = "This is a long sentence with no special characters at all, just plain ASCII."
        result = service.chunk(text, ChunkingRule("r", "1", Strategy.FIXED, 12, 0))
        assert_chunk_invariants(result.chunks, text)
        assert all(len(c.text) <= 12 for c in result.chunks)
        assert result.diagnostics.hard_truncated is False
        assert result.diagnostics.input_characters == len(text)

    def test_token_skips_boundary_check(self, service: DefaultChunkingService) -> None:
        text = "abcdefghijklmnopqrstuvwxyz0123456789"
        result = service.chunk(text, ChunkingRule("r", "1", Strategy.TOKEN, 8, 0))
        assert_chunk_invariants(result.chunks, text)

    def test_paragraph_splits_on_blank_lines(self, service: DefaultChunkingService) -> None:
        text = "First paragraph content.\n\nSecond paragraph content.\n\nThird paragraph content."
        result = service.chunk(text, ChunkingRule("r", "1", Strategy.PARAGRAPH, 24, 0))
        assert_chunk_invariants(result.chunks, text)
        assert len(result.chunks) >= 3

    def test_sentence_preserves_boundaries(self, service: DefaultChunkingService) -> None:
        text = "第一段内容。第二段内容。第三段内容。Fourth sentence here. Fifth sentence there."
        result = service.chunk(text, ChunkingRule("r", "1", Strategy.SENTENCE, 10, 0))
        assert_chunk_invariants(result.chunks, text)
        assert len(result.chunks) >= 5

    def test_markdown_prefers_header_boundaries(self, service: DefaultChunkingService) -> None:
        text = "# Intro\nintro body\n\n## Section A\nsection a body\n\n## Section B\nsection b body"
        result = service.chunk(text, ChunkingRule("r", "1", Strategy.MARKDOWN, 30, 0))
        assert_chunk_invariants(result.chunks, text)
        assert len(result.chunks) >= 2

    def test_html_splits_on_tags(self, service: DefaultChunkingService) -> None:
        text = "<p>First paragraph here.</p>\n<p>Second paragraph here.</p>\n<li>First item</li>\n<li>Second item</li>"
        result = service.chunk(text, ChunkingRule("r", "1", Strategy.HTML, 35, 0))
        assert_chunk_invariants(result.chunks, text)

    def test_page_splits_on_form_feed(self, service: DefaultChunkingService) -> None:
        text = "Page 1 content.\fPage 2 content.\fPage 3 content."
        result = service.chunk(text, ChunkingRule("r", "1", Strategy.PAGE, 14, 0))
        assert_chunk_invariants(result.chunks, text)
        assert len(result.chunks) >= 2

    def test_recursive_uses_rule_separators(self, service: DefaultChunkingService) -> None:
        text = "alpha::beta::gamma::delta::epsilon::zeta"
        result = service.chunk(text, ChunkingRule("r", "1", Strategy.RECURSIVE, 12, 0, ("::",)))
        assert_chunk_invariants(result.chunks, text)
        assert len(result.chunks) >= 3

    def test_semantic_without_advisor_is_rejected(self, service: DefaultChunkingService) -> None:
        with pytest.raises(NotImplementedError, match="SEMANTIC"):
            service.chunk("anything", ChunkingRule("r", "1", Strategy.SEMANTIC, 12, 0))

    def test_preserves_input_offsets(self, service: DefaultChunkingService) -> None:
        text = "alpha beta gamma"
        result = service.chunk(text, ChunkingRule.recursive_defaults(8, 0))
        assert_chunk_invariants(result.chunks, text)


class TestEdgeCases:
    def test_none_content_returns_empty_with_zero_length(self, service: DefaultChunkingService) -> None:
        result = service.chunk(None, ChunkingRule.recursive_defaults(10, 0))  # type: ignore[arg-type]
        assert result.chunks == ()
        assert result.diagnostics.input_characters == 0
        assert result.diagnostics.hard_truncated is False

    def test_blank_content_preserves_raw_length(self, service: DefaultChunkingService) -> None:
        result = service.chunk("   \n\t  ", ChunkingRule.recursive_defaults(10, 0))
        assert result.chunks == ()
        assert result.diagnostics.input_characters == len("   \n\t  ")

    @pytest.mark.parametrize(("overlap", "delta"), [(0, 0), (1, 1), (5, 5)])
    def test_overlap_controls_contiguity(
        self, service: DefaultChunkingService, overlap: int, delta: int
    ) -> None:
        text = "abcdefghijklmnopqrstuvwxyz"
        result = service.chunk(text, ChunkingRule("r", "1", Strategy.FIXED, 6, overlap))
        assert_chunk_invariants(result.chunks, text)
        for previous, current in zip(result.chunks, result.chunks[1:]):
            assert current.char_start == previous.char_end - delta

    def test_unmatchable_boundary_marks_hard_truncated(self, service: DefaultChunkingService) -> None:
        text = "A" * 50
        result = service.chunk(text, ChunkingRule("r", "1", Strategy.SENTENCE, 10, 0))
        assert_chunk_invariants(result.chunks, text)
        assert result.diagnostics.hard_truncated is True
        assert result.diagnostics.has_signal(ChunkingSignal.SEPARATOR_NOT_FOUND)
        assert result.diagnostics.input_characters == 50

    def test_strips_leading_and_trailing_whitespace(self, service: DefaultChunkingService) -> None:
        result = service.chunk("  hello world  ", ChunkingRule("r", "1", Strategy.FIXED, 30, 0))
        assert len(result.chunks) == 1
        only = result.chunks[0]
        assert only.text == "hello world"
        assert (only.char_start, only.char_end) == (2, 13)

    def test_default_rule_is_recursive_1600_160(self, service: DefaultChunkingService) -> None:
        result = service.chunk("a" * 1_601)
        assert len(result.chunks) == 2
        assert all(len(c.text) <= 1_600 for c in result.chunks)

    def test_exceeding_chunk_limit_fails_fast(self) -> None:
        limited = DefaultChunkingService(
            ChunkingRule.recursive_defaults(2, 0), approximate_token_counter(), 0, 1
        )
        with pytest.raises(ChunkLimitExceededError, match="1"):
            limited.chunk("abcdef")

    def test_fixed_exposes_diagnostics(self, service: DefaultChunkingService) -> None:
        text = "fixed diagnostics"
        result = service.chunk(text, ChunkingRule("r", "1", Strategy.FIXED, 100, 0))
        assert result.diagnostics.hard_truncated is False
        assert result.diagnostics.input_characters == len(text)

    def test_token_uses_custom_counter(self) -> None:
        counted: list[str] = []

        class _LenCounter:
            def count(self, text: str) -> int:
                counted.append(text)
                return len(text)

        custom = DefaultChunkingService(
            ChunkingRule.recursive_defaults(3, 0), _LenCounter(), 0, 100
        )
        result = custom.chunk("abcdef", ChunkingRule("token", "1", Strategy.TOKEN, 3, 0))
        assert counted
        assert all(len(c.text) <= 3 for c in result.chunks)

    def test_non_breaking_space_is_not_a_boundary(self, service: DefaultChunkingService) -> None:
        """Java's isWhitespace excludes U+00A0; Python's isspace() does not."""
        text = "alpha\u00a0beta"
        result = service.chunk(text, ChunkingRule("r", "1", Strategy.FIXED, 30, 0))
        assert len(result.chunks) == 1
        assert result.chunks[0].text == text
        assert (result.chunks[0].char_start, result.chunks[0].char_end) == (0, len(text))

    def test_nbsp_only_chunk_is_valid(self) -> None:
        """Java's String.isBlank() excludes U+00A0, so such a chunk is legal."""
        assert Chunk(0, "\u00a0", 0, 1).text == "\u00a0"

    def test_whitespace_only_chunk_is_invalid(self) -> None:
        with pytest.raises(ValueError):
            Chunk(0, " \t", 0, 2)

    def test_nbsp_followed_by_tab_does_not_raise(self, service: DefaultChunkingService) -> None:
        """Regression: trimming keeps the NBSP, so blankness must use Java semantics.

        Found by differential fuzzing against the Java core: `str.strip()` rejected
        the surviving U+00A0 chunk that Java accepts.
        """
        text = " # 6::Hw7v3oTs\t7内w-rxr世sKM世t<br/>5## ？5bJy? -A。\x0c、a9iJuAF4d。\x0ccnQs9zz! 试Vv！本\x0cNX```R容t7Fqem\u00a0\tYL测W</li>M容ILN！Sb! 一是G```e3t！ 容m文\n# 文qD第好8ZUPGarYF界"
        result = service.chunk(text, ChunkingRule("r", "1", Strategy.SENTENCE, 2, 1))
        assert_chunk_invariants(result.chunks, text)
        assert any(c.text == "\u00a0" for c in result.chunks)


class TestApproximateTokenCounter:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("你好世界", 4),
            ("hello", 2),
            ("hi 你好", 3),
            ("", 0),
            ("   ", 0),
            ("a", 1),
            ("！？。", 0),
        ],
    )
    def test_counts(self, text: str, expected: int) -> None:
        assert approximate_token_counter().count(text) == expected


class TestRuleAndChunkInvariants:
    def test_overlap_must_be_less_than_max(self) -> None:
        with pytest.raises(ValueError):
            ChunkingRule("r", "1", Strategy.FIXED, 5, 5)

    def test_blank_rule_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            ChunkingRule("  ", "1", Strategy.FIXED, 5, 0)

    def test_default_separators_applied(self) -> None:
        rule = ChunkingRule("r", "1", Strategy.RECURSIVE, 10, 0)
        assert rule.separators == ("\n\n", "\n", "。", "！", "？", ". ", " ")

    def test_recursive_defaults_factory(self) -> None:
        rule = ChunkingRule.recursive_defaults(100, 10)
        assert (rule.rule_id, rule.version, rule.strategy) == ("default-recursive", "1", Strategy.RECURSIVE)

    def test_chunk_rejects_blank_text(self) -> None:
        with pytest.raises(ValueError):
            Chunk(0, "   ", 0, 3)

    def test_chunk_rejects_inverted_interval(self) -> None:
        with pytest.raises(ValueError):
            Chunk(0, "abc", 5, 3)

    def test_result_reconciles_output_chunk_count(self) -> None:
        result = ChunkingResult((Chunk(0, "abc", 0, 3),), ChunkingDiagnostics(3, 99))
        assert result.diagnostics.output_chunks == 1


class _RecordingFallback:
    """Stands in for the deterministic service, as Mockito does in the Java tests."""

    def __init__(self, responses: list[ChunkingResult]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, Strategy]] = []

    def chunk(self, content: str, rule: ChunkingRule | None = None) -> ChunkingResult:
        self.calls.append((content, rule.strategy))
        return self._responses.pop(0)


class _Advisor:
    def __init__(self, boundaries: list[int] | None, error: Exception | None = None) -> None:
        self._boundaries = boundaries
        self._error = error

    def boundaries(self, content: str) -> list[int]:
        if self._error is not None:
            raise self._error
        return self._boundaries  # type: ignore[return-value]


class TestSemanticChunking:
    def test_empty_advice_delegates_to_recursive_fallback(self) -> None:
        fallback = _RecordingFallback([ChunkingResult((Chunk(0, "anything", 0, 8),))])
        service = SemanticChunkingService(fallback, _Advisor([]))
        result = service.chunk("anything", ChunkingRule("r", "1", Strategy.SEMANTIC, 12, 0))
        assert len(result.chunks) == 1
        assert fallback.calls == [("anything", Strategy.RECURSIVE)]
        assert result.diagnostics.applied_strategy is Strategy.RECURSIVE

    def test_multiple_boundaries_translate_to_global_offsets(self) -> None:
        content = "abcdefghijklmnopqrstuvwxyz"
        fallback = _RecordingFallback(
            [
                ChunkingResult((Chunk(0, "abcde", 0, 5),)),
                ChunkingResult((Chunk(0, "fghijkl", 0, 7),)),
                ChunkingResult((Chunk(0, "mnopqrstuvwxyz", 0, 14),)),
            ]
        )
        service = SemanticChunkingService(fallback, _Advisor([5, 12]))
        result = service.chunk(content, ChunkingRule("r", "1", Strategy.SEMANTIC, 12, 0))
        assert [(c.text, c.char_start, c.char_end) for c in result.chunks] == [
            ("abcde", 0, 5),
            ("fghijkl", 5, 12),
            ("mnopqrstuvwxyz", 12, 26),
        ]
        assert result.diagnostics.input_characters == 26
        assert result.diagnostics.hard_truncated is False

    def test_ordinals_are_globally_monotonic(self) -> None:
        content = "abcdefghijklmnopqrstuvwxyz"
        fallback = _RecordingFallback(
            [
                ChunkingResult((Chunk(0, "ab", 0, 2), Chunk(1, "cd", 2, 4), Chunk(2, "ef", 4, 6))),
                ChunkingResult((Chunk(0, "ghijkl", 0, 6),)),
                ChunkingResult((Chunk(0, "mn", 0, 2), Chunk(1, "opqrst", 2, 8))),
            ]
        )
        service = SemanticChunkingService(fallback, _Advisor([6, 12]))
        result = service.chunk(content, ChunkingRule("r", "1", Strategy.SEMANTIC, 12, 0))
        assert [c.ordinal for c in result.chunks] == [0, 1, 2, 3, 4, 5]
        assert [c.text for c in result.chunks] == ["ab", "cd", "ef", "ghijkl", "mn", "opqrst"]

    def test_out_of_range_boundary_falls_back_with_signal(self) -> None:
        fallback = _RecordingFallback([ChunkingResult((Chunk(0, "abcdef", 0, 6),))])
        service = SemanticChunkingService(fallback, _Advisor([100]))
        result = service.chunk("abcdef", ChunkingRule("r", "1", Strategy.SEMANTIC, 12, 0))
        assert len(result.chunks) == 1
        assert result.diagnostics.has_signal(ChunkingSignal.INVALID_SEMANTIC_BOUNDARY)

    def test_zero_boundary_is_filtered(self) -> None:
        fallback = _RecordingFallback([ChunkingResult((Chunk(0, "abcdef", 0, 6),))])
        service = SemanticChunkingService(fallback, _Advisor([0]))
        result = service.chunk("abcdef", ChunkingRule("r", "1", Strategy.SEMANTIC, 12, 0))
        assert len(result.chunks) == 1
        assert result.diagnostics.has_signal(ChunkingSignal.INVALID_SEMANTIC_BOUNDARY)

    def test_advisor_failure_is_fail_fast_by_default(self) -> None:
        service = SemanticChunkingService(_RecordingFallback([]), _Advisor(None, RuntimeError("boom")))
        with pytest.raises(SemanticBoundaryException):
            service.chunk("abcdef", ChunkingRule("r", "1", Strategy.SEMANTIC, 12, 0))

    def test_advisor_failure_can_degrade_deterministically(self) -> None:
        fallback = _RecordingFallback([ChunkingResult((Chunk(0, "abcdef", 0, 6),))])
        service = SemanticChunkingService(fallback, _Advisor(None, RuntimeError("boom")))
        result = service.chunk(
            "abcdef",
            ChunkingRule("r", "1", Strategy.SEMANTIC, 12, 0),
            SemanticChunkingOptions(SemanticFailureMode.FALLBACK_TO_DETERMINISTIC),
        )
        assert len(result.chunks) == 1
        assert result.diagnostics.has_signal(ChunkingSignal.SEMANTIC_FALLBACK)
        assert result.diagnostics.applied_strategy is Strategy.RECURSIVE

    def test_rejects_non_semantic_rule(self) -> None:
        service = SemanticChunkingService(_RecordingFallback([]), _Advisor([]))
        with pytest.raises(ValueError):
            service.chunk("abc", ChunkingRule("r", "1", Strategy.RECURSIVE, 12, 0))

    def test_end_to_end_with_real_fallback(self) -> None:
        content = "第一段内容。第二段内容。第三段内容。"

        class _FixedAdvisor:
            def boundaries(self, text: str) -> list[int]:
                return [6, 12]

        service = DefaultChunkingService(semantic_boundary_advisor=_FixedAdvisor())
        result = service.chunk(content, ChunkingRule("r", "1", Strategy.SEMANTIC, 12, 0))
        assert_chunk_invariants(result.chunks, content)
        assert result.diagnostics.requested_strategy is Strategy.SEMANTIC
