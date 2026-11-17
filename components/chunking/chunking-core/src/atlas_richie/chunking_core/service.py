"""Chunking services: deterministic batch entry point and semantic orchestration.

Ported from `cn.richie696.component.chunking` (Java). The Spring auto-configuration
and properties classes are deliberately not ported; construction is explicit.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from ._text import is_blank, is_han, is_punctuation, is_whitespace
from .model import (
    Chunk,
    ChunkingDiagnostics,
    ChunkingResult,
    ChunkingRule,
    ChunkingSignal,
    Strategy,
)
from .spi import SemanticBoundaryAdvisor, TokenCounter
from .strategies import ChunkingStrategyFactory, SemanticChunkingStrategy


class SemanticFailureMode(StrEnum):
    """What to do when the boundary advisor raises."""

    FAIL_FAST = "FAIL_FAST"
    FALLBACK_TO_DETERMINISTIC = "FALLBACK_TO_DETERMINISTIC"


@dataclass(frozen=True, slots=True)
class SemanticChunkingOptions:
    failure_mode: SemanticFailureMode = SemanticFailureMode.FAIL_FAST

    @classmethod
    def defaults(cls) -> SemanticChunkingOptions:
        return cls(SemanticFailureMode.FAIL_FAST)


class SemanticBoundaryException(RuntimeError):
    """The semantic boundary advisor failed and fail-fast was requested."""


class ChunkingService(Protocol):
    def chunk(self, content: str, rule: ChunkingRule | None = None) -> ChunkingResult: ...


def approximate_token_counter() -> TokenCounter:
    """Default estimator: one token per Han character, ~4 characters per Latin token.

    Production callers should inject a model-specific `TokenCounter`; this exists
    so the service is usable without any tokenizer dependency.
    """

    class _Approximate:
        def count(self, text: str) -> int:
            if not text:
                return 0
            tokens = 0
            latin_run = 0
            for character in text:
                if is_han(character):
                    tokens += 1
                    latin_run = 0
                elif is_whitespace(character) or is_punctuation(character):
                    tokens += 0 if latin_run == 0 else max(1, (latin_run + 3) // 4)
                    latin_run = 0
                else:
                    latin_run += 1
            return tokens + (0 if latin_run == 0 else max(1, (latin_run + 3) // 4))

    return _Approximate()


class SemanticChunkingService:
    """Cuts at advisor-suggested boundaries, then length-controls each segment.

    The advisor's offsets are normalised (filtered to `0 < value < len(content)`,
    deduplicated, sorted); the final segment always extends to the end of the
    content so no tail is lost. Each segment is chunked by the deterministic
    fallback and its local offsets are translated back to global coordinates.
    """

    def __init__(self, fallback: ChunkingService, advisor: SemanticBoundaryAdvisor) -> None:
        if fallback is None or advisor is None:
            raise ValueError("fallback and advisor must not be null")
        self._fallback = fallback
        self._advisor = advisor

    def chunk(
        self,
        content: str,
        rule: ChunkingRule,
        options: SemanticChunkingOptions | None = None,
    ) -> ChunkingResult:
        options = options or SemanticChunkingOptions.defaults()
        if rule.strategy is not Strategy.SEMANTIC:
            raise ValueError("SemanticChunkingService 仅接受 SEMANTIC 规则")
        if not content or is_blank(content):
            return ChunkingResult(
                (),
                ChunkingDiagnostics(
                    len(content) if content else 0, 0, rule.strategy, rule.strategy, frozenset()
                ),
            )
        try:
            raw_boundaries = self._advisor.boundaries(content)
        except Exception as error:  # noqa: BLE001 — advisor is caller-supplied code
            return self._on_advisor_failure(content, rule, options, error)

        boundaries = self._normalize_boundaries(raw_boundaries, len(content))
        if not boundaries:
            invalid_only = bool(raw_boundaries)
            return self._deterministic_fallback(
                content,
                rule,
                frozenset({ChunkingSignal.INVALID_SEMANTIC_BOUNDARY}) if invalid_only else frozenset(),
            )

        chunks: list[Chunk] = []
        start = 0
        for boundary in boundaries:
            self._append_segment(chunks, content, start, boundary, rule)
            start = boundary
        self._append_segment(chunks, content, start, len(content), rule)
        return ChunkingResult(
            tuple(chunks),
            ChunkingDiagnostics(
                len(content), len(chunks), rule.strategy, rule.strategy, frozenset()
            ),
        )

    def _on_advisor_failure(
        self,
        content: str,
        rule: ChunkingRule,
        options: SemanticChunkingOptions,
        error: Exception,
    ) -> ChunkingResult:
        if options.failure_mode is SemanticFailureMode.FAIL_FAST:
            if isinstance(error, SemanticBoundaryException):
                raise error
            raise SemanticBoundaryException("语义边界服务调用失败") from error
        return self._deterministic_fallback(
            content, rule, frozenset({ChunkingSignal.SEMANTIC_FALLBACK})
        )

    def _deterministic_fallback(
        self, content: str, semantic_rule: ChunkingRule, additional: frozenset[ChunkingSignal]
    ) -> ChunkingResult:
        result = self._fallback.chunk(content, semantic_rule.with_strategy(Strategy.RECURSIVE))
        signals = frozenset(result.diagnostics.signals | additional)
        return ChunkingResult(
            result.chunks,
            ChunkingDiagnostics(
                len(content),
                len(result.chunks),
                semantic_rule.strategy,
                Strategy.RECURSIVE,
                signals,
            ),
        )

    @staticmethod
    def _normalize_boundaries(raw: list[int] | None, content_length: int) -> list[int]:
        if not raw:
            return []
        return sorted({value for value in raw if value is not None and 0 < value < content_length})

    def _append_segment(
        self, output: list[Chunk], content: str, start: int, end: int, semantic_rule: ChunkingRule
    ) -> None:
        if end <= start:
            return
        result = self._fallback.chunk(
            content[start:end], semantic_rule.with_strategy(Strategy.RECURSIVE)
        )
        for chunk in result.chunks:
            output.append(
                Chunk(len(output), chunk.text, chunk.char_start + start, chunk.char_end + start)
            )


class DefaultChunkingService:
    """Batch chunking entry point with the eight deterministic strategies.

    SEMANTIC is registered only when an advisor is supplied. The semantic
    strategy's fallback is this service itself, but `SemanticChunkingService`
    always derives a RECURSIVE rule first, so no recursion occurs.
    """

    def __init__(
        self,
        default_rule: ChunkingRule | None = None,
        token_counter: TokenCounter | None = None,
        min_chunk_characters: int = 80,
        max_chunks_per_document: int = 10_000,
        semantic_boundary_advisor: SemanticBoundaryAdvisor | None = None,
    ) -> None:
        self._default_rule = default_rule or ChunkingRule.recursive_defaults(1_600, 160)
        counter = token_counter if token_counter is not None else approximate_token_counter()
        if min_chunk_characters < 0 or max_chunks_per_document <= 0:
            raise ValueError("minChunkCharacters 和 maxChunksPerDocument 配置非法")
        self._factory = ChunkingStrategyFactory(
            counter, min_chunk_characters, max_chunks_per_document
        )
        if semantic_boundary_advisor is not None:
            self._factory.register(
                SemanticChunkingStrategy(
                    SemanticChunkingService(self, semantic_boundary_advisor)
                )
            )

    @property
    def default_rule(self) -> ChunkingRule:
        return self._default_rule

    def chunk(self, content: str, rule: ChunkingRule | None = None) -> ChunkingResult:
        rule = rule if rule is not None else self._default_rule
        if not content or is_blank(content):
            return ChunkingResult(
                (),
                ChunkingDiagnostics(
                    len(content) if content else 0, 0, rule.strategy, rule.strategy, frozenset()
                ),
            )
        return self._factory.select(rule.strategy).chunk(content, rule)

    def strategy(self, rule: ChunkingRule):
        """Expose the selected strategy (e.g. to query `supports_streaming`)."""
        return self._factory.select(rule.strategy)


__all__ = [
    "ChunkingService",
    "DefaultChunkingService",
    "SemanticBoundaryException",
    "SemanticChunkingOptions",
    "SemanticChunkingService",
    "SemanticFailureMode",
    "approximate_token_counter",
]
