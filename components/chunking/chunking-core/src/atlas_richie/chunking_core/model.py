"""Immutable chunking data contracts.

Ported from `cn.richie696.component.chunking.model` (Java). Character intervals
are half-open `[char_start, char_end)` and always relative to the original input
string, so callers can map any chunk back to their source document.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from ._text import is_blank


class Strategy(StrEnum):
    """The nine chunking strategies; values match the Java enum names."""

    FIXED = "FIXED"
    RECURSIVE = "RECURSIVE"
    TOKEN = "TOKEN"
    PARAGRAPH = "PARAGRAPH"
    SENTENCE = "SENTENCE"
    MARKDOWN = "MARKDOWN"
    HTML = "HTML"
    PAGE = "PAGE"
    SEMANTIC = "SEMANTIC"


class ChunkingSignal(StrEnum):
    """Diagnostics emitted when a strategy had to deviate from its ideal cut."""

    HARD_TRUNCATED = "HARD_TRUNCATED"
    SEPARATOR_NOT_FOUND = "SEPARATOR_NOT_FOUND"
    TOKEN_LIMIT_FORCED = "TOKEN_LIMIT_FORCED"
    SEMANTIC_FALLBACK = "SEMANTIC_FALLBACK"
    INVALID_SEMANTIC_BOUNDARY = "INVALID_SEMANTIC_BOUNDARY"


DEFAULT_SEPARATORS: tuple[str, ...] = ("\n\n", "\n", "。", "！", "？", ". ", " ")


@dataclass(frozen=True, slots=True)
class Chunk:
    """One immutable slice of the input text."""

    ordinal: int
    text: str
    char_start: int
    char_end: int

    def __post_init__(self) -> None:
        if (
            self.ordinal < 0
            or not self.text
            or is_blank(self.text)
            or self.char_start < 0
            or self.char_end < self.char_start
        ):
            raise ValueError("非法 Chunk")


@dataclass(frozen=True, slots=True)
class ChunkingRule:
    """Immutable rule snapshot; persist `rule_id` + `version` to reproduce a cut."""

    rule_id: str
    version: str
    strategy: Strategy
    max_characters: int
    overlap_characters: int
    separators: tuple[str, ...] = DEFAULT_SEPARATORS

    def __post_init__(self) -> None:
        if (
            not self.rule_id
            or is_blank(self.rule_id)
            or not self.version
            or is_blank(self.version)
            or self.overlap_characters < 0
            or self.overlap_characters >= self.max_characters
        ):
            raise ValueError("非法切片规则")
        if self.separators is None:
            object.__setattr__(self, "separators", DEFAULT_SEPARATORS)
        else:
            object.__setattr__(self, "separators", tuple(self.separators))

    @classmethod
    def recursive_defaults(cls, max_characters: int, overlap_characters: int) -> ChunkingRule:
        return cls(
            "default-recursive", "1", Strategy.RECURSIVE, max_characters, overlap_characters
        )

    def with_strategy(self, strategy: Strategy) -> ChunkingRule:
        return ChunkingRule(
            self.rule_id,
            self.version,
            strategy,
            self.max_characters,
            self.overlap_characters,
            self.separators,
        )


@dataclass(frozen=True, slots=True)
class ChunkingDiagnostics:
    """Per-run diagnostics; `output_chunks` is reconciled with the actual count."""

    input_characters: int = 0
    output_chunks: int = 0
    requested_strategy: Strategy | None = None
    applied_strategy: Strategy | None = None
    signals: frozenset[ChunkingSignal] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.input_characters < 0 or self.output_chunks < 0:
            raise ValueError("inputCharacters 和 outputChunks 不能为负数")
        object.__setattr__(self, "signals", frozenset(self.signals or ()))

    @property
    def hard_truncated(self) -> bool:
        return ChunkingSignal.HARD_TRUNCATED in self.signals

    def has_signal(self, signal: ChunkingSignal) -> bool:
        return signal in self.signals


@dataclass(frozen=True, slots=True)
class ChunkingResult:
    """Immutable chunk sequence plus diagnostics."""

    chunks: tuple[Chunk, ...] = ()
    diagnostics: ChunkingDiagnostics = field(default_factory=ChunkingDiagnostics)

    def __post_init__(self) -> None:
        object.__setattr__(self, "chunks", tuple(self.chunks))
        diagnostics = self.diagnostics
        if diagnostics is None:
            diagnostics = ChunkingDiagnostics(0, len(self.chunks))
        elif diagnostics.output_chunks != len(self.chunks):
            diagnostics = ChunkingDiagnostics(
                diagnostics.input_characters,
                len(self.chunks),
                diagnostics.requested_strategy,
                diagnostics.applied_strategy,
                diagnostics.signals,
            )
        object.__setattr__(self, "diagnostics", diagnostics)


__all__ = [
    "DEFAULT_SEPARATORS",
    "Chunk",
    "ChunkingDiagnostics",
    "ChunkingResult",
    "ChunkingRule",
    "ChunkingSignal",
    "Strategy",
]
