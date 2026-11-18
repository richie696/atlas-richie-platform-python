"""parse → chunk 桥接契约测试。"""

from __future__ import annotations

import pytest

from atlas_richie.chunking_core import ChunkingRule, DefaultChunkingService, Strategy
from atlas_richie.chunking_parser_adapter import (
    ChunkedSection,
    Failed,
    Finished,
    ParserChunkingAdapter,
    Section,
    SourceSpan,
)
from atlas_richie.document_parser import (
    BytesSource,
    DocumentParseException,
    DocumentSegment,
    DocumentSummary,
    ImageSegment,
    ImageStreaming,
    ParserRouter,
    Streaming,
)
from atlas_richie.document_parser import Failed as ParseFailed
from atlas_richie.document_parser import Finished as ParseFinished

pytestmark = pytest.mark.unit


def _segment(text: str, **kwargs) -> DocumentSegment:
    return DocumentSegment(text=text, **kwargs)


class TestSourceSpan:
    def test_text_slice_matches_interval(self) -> None:
        segment = _segment("hello world")
        span = SourceSpan(0, segment, 6, 11)
        assert span.text == "world"

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"section_index": -1, "char_start": 0, "char_end": 1},
            {"section_index": 0, "char_start": -1, "char_end": 1},
            {"section_index": 0, "char_start": 3, "char_end": 2},
            {"section_index": 0, "char_start": 0, "char_end": 99},
        ],
    )
    def test_invalid_interval_rejected(self, kwargs) -> None:
        with pytest.raises(ValueError, match="非法来源区间"):
            SourceSpan(section=(_segment("abc")), **kwargs)

    def test_none_section_rejected(self) -> None:
        with pytest.raises(ValueError):
            SourceSpan(0, None, 0, 0)

    def test_empty_interval_allowed(self) -> None:
        assert SourceSpan(0, _segment("abc"), 2, 2).text == ""


class TestChunkSection:
    def test_spans_align_one_to_one_with_chunks(self) -> None:
        segment = _segment("第一段落。\n\n第二段落。\n\n第三段落。")
        adapter = ParserChunkingAdapter()
        section = adapter.chunk_section(segment, section_index=2, file_name="doc.txt")
        assert len(section.source_spans) == len(section.result.chunks)
        for chunk, span in zip(section.result.chunks, section.source_spans):
            assert span.section_index == 2
            assert span.section is segment
            assert (span.char_start, span.char_end) == (chunk.char_start, chunk.char_end)
            assert span.text == chunk.text

    def test_spans_reconstruct_the_source_text(self) -> None:
        text = "alpha beta gamma delta epsilon zeta eta theta"
        adapter = ParserChunkingAdapter()
        rule = ChunkingRule("r", "1", Strategy.FIXED, 12, 0)
        section = adapter.chunk_section(_segment(text), section_index=0, rule=rule)
        assert section.result.chunks, "必须真的切出多个 chunk"
        for chunk, span in zip(section.result.chunks, section.source_spans):
            assert text[span.char_start : span.char_end] == chunk.text

    def test_section_metadata_is_carried(self) -> None:
        segment = _segment("body", title="T", section_path="1.2")
        section = ParserChunkingAdapter().chunk_section(
            segment, section_index=0, file_name="f.md"
        )
        assert section.file_name == "f.md"
        assert section.source.title == "T"
        assert section.source.section_path == "1.2"

    def test_whole_section_span_covers_everything(self) -> None:
        segment = _segment("abcdef")
        result = DefaultChunkingService().chunk("abcdef")
        section = ChunkedSection.whole_section(1, "f", segment, result)
        assert section.source_spans == (SourceSpan(1, segment, 0, 6),)

    def test_whole_section_without_source_has_no_spans(self) -> None:
        result = DefaultChunkingService().chunk("abc")
        assert ChunkedSection.whole_section(0, "f", None, result).source_spans == ()

    def test_injected_service_is_used(self) -> None:
        class _Recording:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def chunk(self, content, rule=None):
                self.calls.append(content)
                return DefaultChunkingService().chunk(content, rule)

        service = _Recording()
        ParserChunkingAdapter(service).chunk_section(_segment("xyz"), section_index=0)
        assert service.calls == ["xyz"]


class TestEventStream:
    def _events(self, *texts: str):
        for index, text in enumerate(texts):
            yield Streaming(segment=_segment(text))
        yield ParseFinished(
            summary=DocumentSummary(title="T"), segment_count=len(texts), image_count=0
        )

    def test_sections_then_finished(self) -> None:
        adapter = ParserChunkingAdapter()
        out = list(adapter.chunk_events(self._events("aaa bbb", "ccc ddd"), file_name="doc.txt"))
        assert [type(e).__name__ for e in out] == ["Section", "Section", "Finished"]
        assert out[0].value.section_index == 0
        assert out[1].value.section_index == 1
        assert out[-1].total_sections == 2
        assert out[-1].emitted_chunks == sum(
            len(e.value.result.chunks) for e in out[:-1]
        )
        assert out[-1].summary.title == "T"

    def test_file_name_is_supplied_by_caller(self) -> None:
        out = list(ParserChunkingAdapter().chunk_events(self._events("text"), file_name="doc.txt"))
        assert out[0].value.file_name == "doc.txt"

    def test_failed_is_passed_through_and_terminates(self) -> None:
        error = DocumentParseException("boom")

        def events():
            yield Streaming(segment=_segment("ok"))
            yield ParseFailed(error=error)
            yield Streaming(segment=_segment("never reached"))

        out = list(ParserChunkingAdapter().chunk_events(events()))
        assert [type(e).__name__ for e in out] == ["Section", "Failed"]
        assert out[-1].error is error

    def test_images_are_skipped_but_sections_keep_indexing(self) -> None:
        def events():
            yield Streaming(segment=_segment("before"))
            yield ImageStreaming(image=ImageSegment(data=b"\x89PNG"))
            yield Streaming(segment=_segment("after"))
            yield ParseFinished(summary=DocumentSummary(), segment_count=2, image_count=1)

        out = list(ParserChunkingAdapter().chunk_events(events()))
        assert [type(e).__name__ for e in out] == ["Section", "Section", "Finished"]
        assert [e.value.section_index for e in out[:-1]] == [0, 1]

    def test_truncated_stream_still_gets_exactly_one_terminal(self) -> None:
        out = list(
            ParserChunkingAdapter().chunk_events([Streaming(segment=_segment("only"))])
        )
        assert isinstance(out[-1], Finished)
        assert out[-1].total_sections == 1
        assert sum(isinstance(e, (Finished, Failed)) for e in out) == 1

    def test_empty_stream_gets_a_terminal(self) -> None:
        out = list(ParserChunkingAdapter().chunk_events([]))
        assert len(out) == 1
        assert isinstance(out[0], Finished)
        assert out[0].total_sections == 0
        assert out[0].emitted_chunks == 0

    def test_rule_is_forwarded_to_every_section(self) -> None:
        rule = ChunkingRule("r", "1", Strategy.FIXED, 8, 0)
        out = list(
            ParserChunkingAdapter().chunk_events(
                self._events("aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb"), rule
            )
        )
        for event in out[:-1]:
            assert all(len(c.text) <= 8 for c in event.value.result.chunks)


class TestEndToEndWithRouter:
    def test_markdown_bytes_to_traceable_chunks(self) -> None:
        source = BytesSource(
            "# 标题\n\n第一段内容。\n\n第二段内容。".encode("utf-8"), name="doc.md"
        )
        events = ParserRouter().parse(source)
        out = list(ParserChunkingAdapter().chunk_events(events))
        assert isinstance(out[-1], Finished)
        sections = [e.value for e in out if isinstance(e, Section)]
        assert sections, "必须真的产出 section"
        for section in sections:
            for chunk, span in zip(section.result.chunks, section.source_spans):
                assert span.text == chunk.text
                assert span.section.text[span.char_start : span.char_end] == chunk.text

    def test_text_file_containing_markup_still_chunks(self) -> None:
        """与 A5 修复联动：含 markup 的 .txt 必须走文本快路径而非报错。"""
        source = BytesSource(b"<html>some text</html>", name="notes.txt")
        out = list(ParserChunkingAdapter().chunk_events(ParserRouter().parse(source)))
        assert isinstance(out[-1], Finished)
        assert out[-1].emitted_chunks >= 1