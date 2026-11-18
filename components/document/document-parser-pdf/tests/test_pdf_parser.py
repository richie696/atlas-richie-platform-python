"""PDF 适配器：文本/图片事件、纯图检测、超时、监听器与路由接入。"""

from __future__ import annotations

import io
from datetime import timedelta
from pathlib import Path

import pytest

from atlas_richie.document_parser import (
    BytesSource,
    DocumentParseException,
    Failed,
    FileSource,
    Finished,
    Format,
    FormatNotSupportedException,
    ImageOnlyPdfException,
    ImageStreaming,
    ParserContext,
    ParserRouter,
    StreamSource,
    Streaming,
    UrlSource,
)
from atlas_richie.document_parser_pdf import (
    MAX_EMBEDDED_IMAGE_BYTES,
    ImageOnlyDetection,
    PdfParser,
)

from pdf_fixture import build_pdf

pytestmark = pytest.mark.unit


def _source(pages, **kwargs) -> BytesSource:
    return BytesSource(build_pdf(pages, **kwargs), name="doc.pdf")


def _events(parser, source, context=None):
    return list(parser.parse(source, context))


def _texts(events) -> list[str]:
    return [e.segment.text for e in events if isinstance(e, Streaming)]


def _finished(events) -> Finished:
    return next(e for e in events if isinstance(e, Finished))


class TestTextExtraction:
    def test_per_page_segments(self) -> None:
        events = _events(PdfParser(), _source([["Hello PDF", "Second line"], ["Page two"]]))
        assert _texts(events) == ["Hello PDF\nSecond line", "Page two"]

    def test_section_path_and_page_metadata(self) -> None:
        events = _events(PdfParser(), _source([["a"], ["b"]]))
        segments = [e.segment for e in events if isinstance(e, Streaming)]
        assert segments[0].section_path == "/doc.pdf/Page[1]"
        assert segments[1].section_path == "/doc.pdf/Page[2]"
        assert segments[0].metadata["page"] == 1
        assert segments[0].metadata["format"] == "application/pdf"

    def test_summary_carries_title_and_page_count(self) -> None:
        events = _events(PdfParser(), _source([["a"], ["b"]], title="Doc Title"))
        finished = _finished(events)
        assert finished.summary.title == "Doc Title"
        assert finished.summary.metadata["pages"] == 2
        assert finished.segment_count == 2
        assert finished.image_count == 0

    def test_empty_pages_produce_no_segments(self) -> None:
        events = _events(PdfParser(), _source([[], []]))
        assert _texts(events) == []
        assert _finished(events).segment_count == 0

    def test_max_segment_length_splits_long_page(self) -> None:
        events = _events(
            PdfParser(), _source([["abcdefghij" * 5]]),
            ParserContext(max_segment_length=10),
        )
        texts = _texts(events)
        assert len(texts) > 1
        assert all(len(t) <= 10 for t in texts)

    def test_file_source(self, tmp_path: Path) -> None:
        path = tmp_path / "f.pdf"
        path.write_bytes(build_pdf([["from file"]]))
        events = _events(PdfParser(), FileSource(path))
        assert _texts(events) == ["from file"]

    def test_stream_source(self) -> None:
        stream = io.BytesIO(build_pdf([["from stream"]]))
        events = _events(PdfParser(), StreamSource(stream, name="s.pdf"))
        assert _texts(events) == ["from stream"]
        assert not stream.closed, "调用方持有的流不应被适配器关闭"

    def test_url_source_is_rejected_with_pointer_to_fetcher(self) -> None:
        events = _events(PdfParser(), UrlSource("https://example.com/a.pdf"))
        assert isinstance(events[-1], Failed)
        assert isinstance(events[-1].error, FormatNotSupportedException)
        assert "document-fetcher" in str(events[-1].error)

    def test_corrupt_pdf_becomes_failed_event(self) -> None:
        events = _events(PdfParser(), BytesSource(b"%PDF-1.4 not a real pdf", name="bad.pdf"))
        assert isinstance(events[-1], Failed)
        assert isinstance(events[-1].error, DocumentParseException)

    def test_timeout_becomes_failed_event(self) -> None:
        events = _events(
            PdfParser(), _source([["a"], ["b"]]),
            ParserContext(timeout=timedelta(microseconds=1)),
        )
        assert isinstance(events[-1], Failed)
        assert "timeout" in str(events[-1].error)


class TestImages:
    def test_images_not_emitted_by_default(self) -> None:
        events = _events(PdfParser(), _source([["text"]], images_per_page=3))
        assert not any(isinstance(e, ImageStreaming) for e in events)
        assert _finished(events).image_count == 0

    def test_emit_images_yields_image_events(self) -> None:
        events = _events(
            PdfParser(), _source([["text"]], images_per_page=3),
            ParserContext(emit_images=True),
        )
        images = [e for e in events if isinstance(e, ImageStreaming)]
        assert len(images) == 3
        assert images[0].image.data
        assert images[0].image.mime_type == "image/png"
        assert images[0].image.section_path == "/doc.pdf/Page[1]"
        assert images[0].image.metadata["page"] == 1
        assert _finished(events).image_count == 3

    def test_oversized_images_are_skipped(self) -> None:
        parser = PdfParser(max_embedded_image_bytes=1)
        events = _events(
            parser, _source([["text"]], images_per_page=3),
            ParserContext(emit_images=True),
        )
        assert not any(isinstance(e, ImageStreaming) for e in events)
        assert _texts(events) == ["text"], "图片被跳过不影响文本"

    def test_invalid_max_image_bytes_rejected(self) -> None:
        with pytest.raises(ValueError):
            PdfParser(max_embedded_image_bytes=0)

    def test_default_cap_matches_java(self) -> None:
        assert MAX_EMBEDDED_IMAGE_BYTES == 20 * 1024 * 1024


class TestImageOnlyDetection:
    def test_disabled_by_default_emits_images_instead_of_failing(self) -> None:
        """Java 默认 enabled=false：业务方收 ImageStreaming 自行走 OCR/VLM。"""
        events = _events(
            PdfParser(), _source([[]], images_per_page=6),
            ParserContext(emit_images=True),
        )
        assert isinstance(events[-1], Finished)
        assert events[-1].image_count == 6

    def test_strict_mode_fails_fast_with_diagnostics(self) -> None:
        parser = PdfParser(image_only_detection=ImageOnlyDetection(enabled=True))
        events = _events(parser, _source([[]], images_per_page=6), ParserContext(emit_images=True))
        assert isinstance(events[-1], Failed)
        error = events[-1].error
        assert isinstance(error, ImageOnlyPdfException)
        assert error.image_count == 6
        assert error.text_chars == 0
        assert error.page_count == 1
        assert error.name_hint == "doc.pdf"

    def test_strict_mode_needs_both_thresholds(self) -> None:
        detection = ImageOnlyDetection(enabled=True, min_text_chars=200, min_image_count=5)
        assert detection.triggers(100, 5) is True
        assert detection.triggers(100, 4) is False, "图片数不足不应触发"
        assert detection.triggers(250, 6) is False, "文本足够不应触发"

    def test_almost_empty_triggers_regardless_of_images(self) -> None:
        detection = ImageOnlyDetection(enabled=True)
        assert detection.triggers(49, 0) is True
        assert detection.triggers(50, 0) is False

    def test_text_rich_pdf_passes_strict_mode(self) -> None:
        parser = PdfParser(image_only_detection=ImageOnlyDetection(enabled=True))
        events = _events(parser, _source([["word " * 60]]))
        assert isinstance(events[-1], Finished)

    def test_disabled_detection_never_triggers(self) -> None:
        assert ImageOnlyDetection().triggers(0, 100) is False

    def test_negative_thresholds_rejected(self) -> None:
        with pytest.raises(ValueError):
            ImageOnlyDetection(min_text_chars=-1)


class TestListener:
    class _Recorder:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def on_streaming(self, segment, source_name) -> None:
            self.calls.append("streaming")

        def on_image(self, image, source_name) -> None:
            self.calls.append("image")

        def on_finished(self, summary, source_name) -> None:
            self.calls.append("finished")

        def on_error(self, error, source_name) -> None:
            self.calls.append("error")

    def test_listener_receives_every_event(self) -> None:
        recorder = self._Recorder()
        events = _events(
            PdfParser(listener=recorder), _source([["a"]], images_per_page=2),
            ParserContext(emit_images=True),
        )
        assert recorder.calls == ["streaming", "image", "image", "finished"]
        assert len(events) == 4

    def test_listener_sees_errors(self) -> None:
        recorder = self._Recorder()
        _events(PdfParser(listener=recorder), BytesSource(b"garbage", name="x.pdf"))
        assert recorder.calls == ["error"]

    def test_broken_listener_does_not_break_parsing(self) -> None:
        class _Broken:
            def on_streaming(self, *a) -> None:
                raise RuntimeError("listener down")

            def on_image(self, *a) -> None:
                raise RuntimeError("listener down")

            def on_finished(self, *a) -> None:
                raise RuntimeError("listener down")

            def on_error(self, *a) -> None:
                raise RuntimeError("listener down")

        events = _events(PdfParser(listener=_Broken()), _source([["a"], ["b"]]))
        assert _texts(events) == ["a", "b"]
        assert isinstance(events[-1], Finished)


class TestRouterIntegration:
    def test_pdf_routes_to_adapter(self) -> None:
        router = ParserRouter({Format.PDF: PdfParser()})
        assert Format.PDF in router.registered_formats()
        events = list(router.parse(_source([["routed"]])) )
        assert _texts(events) == ["routed"]

    def test_detection_by_magic_bytes(self) -> None:
        router = ParserRouter({Format.PDF: PdfParser()})
        source = BytesSource(build_pdf([["magic"]]), name="lies.txt")
        assert _texts(list(router.parse(source))) == ["magic"]

    def test_unregistered_pdf_still_reports_missing_adapter(self) -> None:
        with pytest.raises(FormatNotSupportedException, match="no parser registered"):
            ParserRouter().route(Format.PDF)


class TestChunkingChain:
    def test_pdf_to_traceable_chunks(self) -> None:
        """PDF → chunk → 溯源区间，验证与下游桥接真的串得起来。"""
        from atlas_richie.chunking_parser_adapter import (
            Finished as ChunkFinished,
            ParserChunkingAdapter,
            Section,
        )

        router = ParserRouter({Format.PDF: PdfParser()})
        events = router.parse(_source([["First page text."], ["Second page text."]]))
        out = list(ParserChunkingAdapter().chunk_events(events, file_name="doc.pdf"))
        assert isinstance(out[-1], ChunkFinished)
        sections = [e.value for e in out if isinstance(e, Section)]
        assert len(sections) == 2
        for section in sections:
            for chunk, span in zip(section.result.chunks, section.source_spans):
                assert span.text == chunk.text
                assert span.section.metadata["page"] in (1, 2)