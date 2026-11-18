"""解析事件 → 切分结果的桥接模型。

对位 Java `cn.richie696.component.chunking.parser` 的 `SourceSpan` /
`ChunkedSection` / `ChunkingEvent`。

`SourceSpan` 是 RAG 溯源的关键：每个 chunk 都记住它来自哪个 section 的哪段
字符区间，引用/回链才能定位到原文，而不是只有一段无出处的文本。
"""

from __future__ import annotations

from dataclasses import dataclass

from atlas_richie.chunking_core import ChunkingResult
from atlas_richie.document_parser import (
    DocumentParseException,
    DocumentSegment,
    DocumentSummary,
)


@dataclass(frozen=True, slots=True)
class SourceSpan:
    section_index: int
    section: DocumentSegment
    char_start: int
    char_end: int

    def __post_init__(self) -> None:
        if (
            self.section_index < 0
            or self.section is None
            or self.char_start < 0
            or self.char_end < self.char_start
            or self.char_end > len(self.section.text)
        ):
            raise ValueError("非法来源区间")

    @property
    def text(self) -> str:
        return self.section.text[self.char_start : self.char_end]


@dataclass(frozen=True, slots=True)
class ChunkedSection:
    section_index: int
    file_name: str
    source: DocumentSegment | None
    result: ChunkingResult
    source_spans: tuple[SourceSpan, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_spans", tuple(self.source_spans or ()))

    @classmethod
    def whole_section(
        cls,
        section_index: int,
        file_name: str,
        source: DocumentSegment | None,
        result: ChunkingResult,
    ) -> ChunkedSection:
        """Span covering the entire section, used when per-chunk spans are absent."""
        spans = (
            ()
            if source is None
            else (SourceSpan(section_index, source, 0, len(source.text)),)
        )
        return cls(section_index, file_name, source, result, spans)


class ChunkingEvent:
    """桥接事件基类。终态恒为 Finished 或 Failed 之一。"""

    __slots__ = ()


@dataclass(frozen=True, slots=True)
class Section(ChunkingEvent):
    value: ChunkedSection


@dataclass(frozen=True, slots=True)
class Finished(ChunkingEvent):
    summary: DocumentSummary
    total_sections: int
    emitted_chunks: int


@dataclass(frozen=True, slots=True)
class Failed(ChunkingEvent):
    error: DocumentParseException | Exception


__all__ = [
    "SourceSpan",
    "ChunkedSection",
    "ChunkingEvent",
    "Section",
    "Finished",
    "Failed",
]