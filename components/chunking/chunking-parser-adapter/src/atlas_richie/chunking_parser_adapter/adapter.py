"""把 document-parser 的事件流接成带溯源的 chunk 流。

对位 Java `ParserChunkingAdapter`。这是 parse → chunk → vector 链路中唯一的
桥：两个 core 互不依赖，由本包把它们接起来（必要时桥接、非必要不耦合）。

Java 侧桥的是 `ReadEvent`/`ReadResult` API；Python 侧 parser 交付的是
`ParseEvent`（Streaming / ImageStreaming / Finished / Failed），因此本适配器
桥接后者，语义一致：逐 section 切分、保留字符区间、终态携带汇总计数。

输出契约：事件流**恒以恰好一个终态事件结束**（Finished 或 Failed）。上游若
提前截断且未给终态，本适配器补一个 Finished，避免消费方悬挂。
"""

from __future__ import annotations

from typing import Iterable, Iterator

from atlas_richie.chunking_core import (
    ChunkingRule,
    ChunkingService,
    DefaultChunkingService,
)
from atlas_richie.document_parser import (
    DocumentSegment,
    DocumentSummary,
    Failed as ParseFailed,
    Finished as ParseFinished,
    ImageStreaming,
    ParseEvent,
    Streaming,
)

from .model import ChunkedSection, ChunkingEvent, Failed, Finished, Section, SourceSpan


class ParserChunkingAdapter:
    def __init__(self, service: ChunkingService | None = None) -> None:
        self._service = service if service is not None else DefaultChunkingService()

    @property
    def service(self) -> ChunkingService:
        return self._service

    def chunk_section(
        self,
        segment: DocumentSegment,
        *,
        section_index: int,
        file_name: str = "",
        rule: ChunkingRule | None = None,
    ) -> ChunkedSection:
        result = self._service.chunk(segment.text, rule)
        spans = tuple(
            SourceSpan(section_index, segment, chunk.char_start, chunk.char_end)
            for chunk in result.chunks
        )
        return ChunkedSection(section_index, file_name, segment, result, spans)

    def chunk_events(
        self,
        events: Iterable[ParseEvent],
        rule: ChunkingRule | None = None,
        *,
        file_name: str = "",
    ) -> Iterator[ChunkingEvent]:
        """`file_name` is supplied by the caller: parser events carry a section
        path in `source_name`, not the originating file name."""
        section_index = 0
        emitted_chunks = 0
        for event in events:
            if isinstance(event, Streaming):
                section = self.chunk_section(
                    event.segment,
                    section_index=section_index,
                    file_name=file_name,
                    rule=rule,
                )
                section_index += 1
                emitted_chunks += len(section.result.chunks)
                yield Section(section)
            elif isinstance(event, ImageStreaming):
                # 图片不参与文本切分；计数由上游 Finished 携带。
                continue
            elif isinstance(event, ParseFinished):
                yield Finished(event.summary, section_index, emitted_chunks)
                return
            elif isinstance(event, ParseFailed):
                yield Failed(event.error)
                return
        yield Finished(DocumentSummary(), section_index, emitted_chunks)


__all__ = ["ParserChunkingAdapter"]