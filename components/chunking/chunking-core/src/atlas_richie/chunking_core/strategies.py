"""Chunking strategies.

Ported from `cn.richie696.component.chunking.strategy` (Java). The character
window algorithm, separator precedence, small-tail merging and diagnostics are
reproduced exactly, including two behaviours that are easy to "fix" by accident:

- a separator boundary may extend past the requested cap (the match only has to
  *start* at or before `cap - 1`);
- small-tail merging re-slices the ORIGINAL content, so the merged chunk keeps
  the whitespace that sat between the two pieces.
"""

from __future__ import annotations

import sys
from typing import Protocol

from ._text import is_whitespace
from .model import (
    Chunk,
    ChunkingDiagnostics,
    ChunkingResult,
    ChunkingRule,
    ChunkingSignal,
    Strategy,
)
from .spi import TokenCounter


class ChunkLimitExceededError(RuntimeError):
    """Raised when a single document would produce more chunks than allowed."""


class ChunkingStrategy(Protocol):
    """One strategy implementation, selected by `ChunkingRule.strategy`."""

    def type(self) -> Strategy: ...

    def chunk(self, content: str, rule: ChunkingRule) -> ChunkingResult: ...

    @property
    def supports_streaming(self) -> bool: ...


class _Support:
    """Shared chunk construction, small-tail merging and diagnostics."""

    def __init__(self, min_chunk_characters: int, max_chunks_per_document: int) -> None:
        self._min_chunk_characters = min_chunk_characters
        self._max_chunks_per_document = max_chunks_per_document

    def append(self, chunks: list[Chunk], content: str, raw_start: int, raw_end: int) -> None:
        start = raw_start
        while start < raw_end and is_whitespace(content[start]):
            start += 1
        end = raw_end
        while end > start and is_whitespace(content[end - 1]):
            end -= 1
        if start == end:
            return
        if len(chunks) >= self._max_chunks_per_document:
            raise ChunkLimitExceededError(
                f"单文档 Chunk 数超过上限: {self._max_chunks_per_document}"
            )
        chunks.append(Chunk(len(chunks), content[start:end], start, end))

    def normalize_small_tail(
        self, chunks: list[Chunk], maximum_characters: int, content: str
    ) -> list[Chunk]:
        if len(chunks) < 2 or self._min_chunk_characters == 0:
            return list(chunks)
        tail = chunks[-1]
        previous = chunks[-2]
        if (
            len(tail.text) >= self._min_chunk_characters
            or len(previous.text) + 1 + len(tail.text) > maximum_characters
        ):
            return list(chunks)
        merged = list(chunks[:-2])
        start, end = previous.char_start, tail.char_end
        merged.append(Chunk(len(merged), content[start:end], start, end))
        return merged

    def result(
        self,
        content: str,
        rule: ChunkingRule,
        chunks: list[Chunk],
        signals: frozenset[ChunkingSignal],
    ) -> ChunkingResult:
        return ChunkingResult(
            tuple(chunks),
            ChunkingDiagnostics(
                len(content), len(chunks), rule.strategy, rule.strategy, signals
            ),
        )


def _last_boundary(text: str, separators: tuple[str, ...] | list[str], limit: int) -> int:
    """End offset of the last separator match starting at or before `limit - 1`."""
    capped = max(1, min(limit, len(text)))
    if capped == len(text):
        return capped
    for separator in separators:
        if not separator:
            continue
        # rfind's end bound is exclusive, so widening it by len(separator) lets a
        # match START at capped - 1 and still extend past the cap — matching Java.
        index = text.rfind(separator, 0, capped - 1 + len(separator))
        if index >= 0:
            return index + len(separator)
    return capped


class _CharacterStrategy:
    """Base for strategies that cut on a character window."""

    reports_missing_boundary = True

    def __init__(self, support: _Support) -> None:
        self._support = support

    @property
    def supports_streaming(self) -> bool:
        return True

    def boundary_at_or_before(self, text: str, rule: ChunkingRule, limit: int) -> int:
        raise NotImplementedError

    def chunk(self, content: str, rule: ChunkingRule) -> ChunkingResult:
        chunks: list[Chunk] = []
        start = 0
        hard_truncated = False
        length = len(content)
        while start < length:
            candidate_end = min(length, start + rule.max_characters)
            end = candidate_end
            if candidate_end < length:
                boundary = self.boundary_at_or_before(
                    content[start:candidate_end], rule, rule.max_characters
                )
                if boundary > 0:
                    end = start + boundary
                if self.reports_missing_boundary and boundary >= candidate_end - start:
                    hard_truncated = True
            self._support.append(chunks, content, start, end)
            if end >= length:
                break
            start = max(start + 1, end - rule.overlap_characters)
        normalized = self._support.normalize_small_tail(chunks, rule.max_characters, content)
        signals = (
            frozenset({ChunkingSignal.HARD_TRUNCATED, ChunkingSignal.SEPARATOR_NOT_FOUND})
            if hard_truncated
            else frozenset()
        )
        return self._support.result(content, rule, normalized, signals)


class FixedChunkingStrategy(_CharacterStrategy):
    """S1: pure character windows, no separator lookup; the stable fallback."""

    reports_missing_boundary = False

    def type(self) -> Strategy:
        return Strategy.FIXED

    def boundary_at_or_before(self, text: str, rule: ChunkingRule, limit: int) -> int:
        return max(1, min(limit, len(text)))


class RecursiveChunkingStrategy(_CharacterStrategy):
    """S2: caller-declared separator precedence; the default strategy."""

    def type(self) -> Strategy:
        return Strategy.RECURSIVE

    def boundary_at_or_before(self, text: str, rule: ChunkingRule, limit: int) -> int:
        return _last_boundary(text, rule.separators, limit)


class _SeparatorStrategy(_CharacterStrategy):
    """Base for strategies with a fixed built-in separator set."""

    separators: tuple[str, ...] = ()

    def boundary_at_or_before(self, text: str, rule: ChunkingRule, limit: int) -> int:
        return _last_boundary(text, self.separators, limit)


class ParagraphChunkingStrategy(_SeparatorStrategy):
    """S4: blank lines then single newlines."""

    separators = ("\n\n", "\n")

    def type(self) -> Strategy:
        return Strategy.PARAGRAPH


class SentenceChunkingStrategy(_SeparatorStrategy):
    """S5: common Chinese and English sentence terminators."""

    separators = ("。", "！", "？", ". ", "! ", "? ")

    def type(self) -> Strategy:
        return Strategy.SENTENCE


class MarkdownChunkingStrategy(_SeparatorStrategy):
    """S6: heading prefixes and fenced blocks before plain newlines."""

    separators = ("\n# ", "\n## ", "\n### ", "\n```", "\n\n", "\n")

    def type(self) -> Strategy:
        return Strategy.MARKDOWN


class HtmlChunkingStrategy(_SeparatorStrategy):
    """S7: common HTML closing tags. Does not parse or sanitise a DOM."""

    separators = ("</h1>", "</h2>", "</h3>", "</p>", "</li>", "</tr>", "<br>", "<br/>")

    def type(self) -> Strategy:
        return Strategy.HTML


class PageChunkingStrategy(_SeparatorStrategy):
    """S8: form feed then blank lines. The component does not know page numbers."""

    separators = ("\f", "\n\n")

    def type(self) -> Strategy:
        return Strategy.PAGE


class TokenChunkingStrategy:
    """S3: binary-searches the widest window within the rule's token budget."""

    def __init__(self, token_counter: TokenCounter, support: _Support) -> None:
        if token_counter is None:
            raise ValueError("tokenCounter must not be null")
        self._token_counter = token_counter
        self._support = support

    def type(self) -> Strategy:
        return Strategy.TOKEN

    @property
    def supports_streaming(self) -> bool:
        return True

    def chunk(self, content: str, rule: ChunkingRule) -> ChunkingResult:
        chunks: list[Chunk] = []
        start = 0
        hard_truncated = False
        length = len(content)
        while start < length:
            end = self._max_end_within_token_limit(content, start, rule.max_characters)
            if end <= start:
                end = min(length, start + 1)
                hard_truncated = True
            self._support.append(chunks, content, start, end)
            if end >= length:
                break
            overlap = max(0, min(rule.overlap_characters, end - start - 1))
            start = max(start + 1, end - overlap)
        normalized = self._support.normalize_small_tail(chunks, sys.maxsize, content)
        signals = (
            frozenset({ChunkingSignal.HARD_TRUNCATED, ChunkingSignal.TOKEN_LIMIT_FORCED})
            if hard_truncated
            else frozenset()
        )
        return self._support.result(content, rule, normalized, signals)

    def boundary_at_or_before(self, content: str, rule: ChunkingRule, limit: int) -> int:
        capped = max(1, min(limit, len(content)))
        window = content[:capped]
        end = self._max_end_within_token_limit(window, 0, rule.max_characters)
        return min(1, len(window)) if end <= 0 else end

    def _max_end_within_token_limit(self, content: str, start: int, max_tokens: int) -> int:
        low = start + 1
        high = len(content)
        best = start
        while low <= high:
            middle = low + (high - low) // 2
            if self._token_counter.count(content[start:middle]) <= max_tokens:
                best = middle
                low = middle + 1
            else:
                high = middle - 1
        return best


class _SemanticDelegate(Protocol):
    def chunk(self, content: str, rule: ChunkingRule) -> ChunkingResult: ...


class SemanticChunkingStrategy:
    """S9: delegates to the semantic service; needs full context, so no streaming."""

    def __init__(self, delegate: _SemanticDelegate) -> None:
        if delegate is None:
            raise ValueError("delegate must not be null")
        self._delegate = delegate

    def type(self) -> Strategy:
        return Strategy.SEMANTIC

    @property
    def supports_streaming(self) -> bool:
        return False

    def chunk(self, content: str, rule: ChunkingRule) -> ChunkingResult:
        return self._delegate.chunk(content, rule)


class ChunkingStrategyFactory:
    """Routes a rule to its strategy; one implementation per strategy type."""

    def __init__(
        self,
        token_counter: TokenCounter,
        min_chunk_characters: int,
        max_chunks_per_document: int,
    ) -> None:
        support = _Support(min_chunk_characters, max_chunks_per_document)
        self._strategies: dict[Strategy, ChunkingStrategy] = {}
        for strategy in (
            FixedChunkingStrategy(support),
            RecursiveChunkingStrategy(support),
            TokenChunkingStrategy(token_counter, support),
            ParagraphChunkingStrategy(support),
            SentenceChunkingStrategy(support),
            MarkdownChunkingStrategy(support),
            HtmlChunkingStrategy(support),
            PageChunkingStrategy(support),
        ):
            self.register(strategy)

    def register(self, strategy: ChunkingStrategy) -> None:
        if strategy is None:
            raise ValueError("strategy must not be null")
        kind = strategy.type()
        if kind in self._strategies:
            raise ValueError(f"切片策略重复注册: {kind}")
        self._strategies[kind] = strategy

    def select(self, kind: Strategy) -> ChunkingStrategy:
        strategy = self._strategies.get(kind)
        if strategy is None:
            raise NotImplementedError(
                f"未注册切片策略: {kind}；SEMANTIC 策略需要提供 SemanticBoundaryAdvisor"
            )
        return strategy


__all__ = [
    "ChunkLimitExceededError",
    "ChunkingStrategy",
    "ChunkingStrategyFactory",
    "FixedChunkingStrategy",
    "HtmlChunkingStrategy",
    "MarkdownChunkingStrategy",
    "PageChunkingStrategy",
    "ParagraphChunkingStrategy",
    "RecursiveChunkingStrategy",
    "SemanticChunkingStrategy",
    "SentenceChunkingStrategy",
    "TokenChunkingStrategy",
]
