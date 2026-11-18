"""DOCX/XLSX 适配器：用 python-docx/openpyxl 生成真实文件作为夹具。"""

from __future__ import annotations

import io
from datetime import timedelta

import pytest
from docx import Document
from openpyxl import Workbook

from atlas_richie.document_parser import (
    BytesSource,
    Failed,
    Finished,
    Format,
    FormatNotSupportedException,
    ParserContext,
    ParserRouter,
    StreamSource,
    Streaming,
    UrlSource,
)
from atlas_richie.document_parser_office import DocxParser, XlsxParser

pytestmark = pytest.mark.unit


def _docx(paragraphs, tables=(), title=None) -> bytes:
    doc = Document()
    if title:
        doc.core_properties.title = title
    for text in paragraphs:
        doc.add_paragraph(text)
    for rows in tables:
        table = doc.add_table(rows=len(rows), cols=len(rows[0]))
        for i, row in enumerate(rows):
            for j, value in enumerate(row):
                table.cell(i, j).text = value
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _xlsx(sheets: dict[str, list[list]]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _texts(events):
    return [e.segment.text for e in events if isinstance(e, Streaming)]


def _finished(events):
    return next(e for e in events if isinstance(e, Finished))


class TestDocx:
    def test_paragraphs_become_segments(self) -> None:
        events = list(DocxParser().parse(BytesSource(_docx(["one", "two"]), name="d.docx")))
        assert _texts(events) == ["one", "two"]

    def test_title_from_core_properties(self) -> None:
        events = list(DocxParser().parse(BytesSource(_docx(["x"], title="My Doc"))))
        assert _finished(events).summary.title == "My Doc"

    def test_blank_paragraphs_skipped(self) -> None:
        events = list(DocxParser().parse(BytesSource(_docx(["", "  ", "real"]))))
        assert _texts(events) == ["real"]

    def test_table_rows_become_segments(self) -> None:
        data = _docx(["intro"], tables=[[["a", "b"], ["c", "d"]]])
        events = list(DocxParser().parse(BytesSource(data, name="d.docx")))
        assert _texts(events) == ["intro", "a | b", "c | d"]

    def test_section_paths_and_metadata(self) -> None:
        data = _docx(["p"], tables=[[["x", "y"]]])
        events = list(DocxParser().parse(BytesSource(data, name="d.docx")))
        segments = [e.segment for e in events if isinstance(e, Streaming)]
        assert segments[0].section_path == "/d.docx/Paragraph[1]"
        assert segments[1].section_path == "/d.docx/Table[1]/Row[1]"
        assert segments[1].metadata["table"] == 1
        assert segments[1].metadata["row"] == 1

    def test_max_segment_length_splits(self) -> None:
        events = list(
            DocxParser().parse(
                BytesSource(_docx(["x" * 30])), ParserContext(max_segment_length=10)
            )
        )
        assert _texts(events) == ["x" * 10] * 3

    def test_finished_counts(self) -> None:
        events = list(DocxParser().parse(BytesSource(_docx(["a", "b"]))))
        assert _finished(events).segment_count == 2
        assert _finished(events).image_count == 0

    def test_stream_source_not_closed(self) -> None:
        stream = io.BytesIO(_docx(["s"]))
        list(DocxParser().parse(StreamSource(stream, name="s.docx")))
        assert not stream.closed

    def test_corrupt_docx_becomes_failed(self) -> None:
        events = list(DocxParser().parse(BytesSource(b"not a docx", name="bad.docx")))
        assert isinstance(events[-1], Failed)

    def test_url_source_rejected(self) -> None:
        events = list(DocxParser().parse(UrlSource("https://example.com/a.docx")))
        assert isinstance(events[-1].error, FormatNotSupportedException)

    def test_timeout_becomes_failed(self) -> None:
        events = list(
            DocxParser().parse(
                BytesSource(_docx(["a", "b"])), ParserContext(timeout=timedelta(microseconds=1))
            )
        )
        assert isinstance(events[-1], Failed)
        assert "timeout" in str(events[-1].error)


class TestXlsx:
    def test_rows_become_segments(self) -> None:
        data = _xlsx({"Sheet1": [["a", "b"], ["c", "d"]]})
        events = list(XlsxParser().parse(BytesSource(data, name="s.xlsx")))
        assert _texts(events) == ["a | b", "c | d"]

    def test_multiple_sheets(self) -> None:
        data = _xlsx({"One": [["x"]], "Two": [["y"]]})
        events = list(XlsxParser().parse(BytesSource(data, name="s.xlsx")))
        assert _texts(events) == ["x", "y"]
        assert _finished(events).summary.metadata["sheets"] == 2

    def test_sheet_and_row_in_section_path(self) -> None:
        data = _xlsx({"Data": [["v"]]})
        events = list(XlsxParser().parse(BytesSource(data, name="s.xlsx")))
        segment = next(e.segment for e in events if isinstance(e, Streaming))
        assert segment.section_path == "/s.xlsx/Sheet[Data]/Row[1]"
        assert segment.metadata["sheet"] == "Data"

    def test_empty_rows_skipped(self) -> None:
        data = _xlsx({"S": [[None, None], ["real", None], []]})
        events = list(XlsxParser().parse(BytesSource(data)))
        assert _texts(events) == ["real"]

    def test_numbers_are_stringified(self) -> None:
        data = _xlsx({"S": [[1, 2.5]]})
        events = list(XlsxParser().parse(BytesSource(data)))
        assert _texts(events) == ["1 | 2.5"]

    def test_formula_uses_cached_value(self) -> None:
        wb = Workbook()
        ws = wb.active
        ws["A1"] = 2
        ws["B1"] = "=A1*3"
        buffer = io.BytesIO()
        wb.save(buffer)
        events = list(XlsxParser().parse(BytesSource(buffer.getvalue())))
        texts = _texts(events)
        assert texts and "=A1*3" not in texts[0], "data_only 应取缓存值而非公式串"

    def test_max_segment_length_splits(self) -> None:
        data = _xlsx({"S": [["y" * 25]]})
        events = list(
            XlsxParser().parse(BytesSource(data), ParserContext(max_segment_length=10))
        )
        assert all(len(t) <= 10 for t in _texts(events))

    def test_corrupt_xlsx_becomes_failed(self) -> None:
        events = list(XlsxParser().parse(BytesSource(b"not xlsx", name="bad.xlsx")))
        assert isinstance(events[-1], Failed)

    def test_timeout_becomes_failed(self) -> None:
        data = _xlsx({"S": [["a"], ["b"]]})
        events = list(
            XlsxParser().parse(BytesSource(data), ParserContext(timeout=timedelta(microseconds=1)))
        )
        assert isinstance(events[-1], Failed)


class TestListenerAndRouter:
    def test_listener_receives_events(self) -> None:
        calls: list[str] = []

        class _Rec:
            def on_streaming(self, *a) -> None: calls.append("s")
            def on_image(self, *a) -> None: calls.append("i")
            def on_finished(self, *a) -> None: calls.append("f")
            def on_error(self, *a) -> None: calls.append("e")

        list(DocxParser(listener=_Rec()).parse(BytesSource(_docx(["a"]))))
        assert calls == ["s", "f"]

    def test_broken_listener_does_not_break_parsing(self) -> None:
        class _Broken:
            def on_streaming(self, *a) -> None: raise RuntimeError("down")
            def on_image(self, *a) -> None: raise RuntimeError("down")
            def on_finished(self, *a) -> None: raise RuntimeError("down")
            def on_error(self, *a) -> None: raise RuntimeError("down")

        events = list(DocxParser(listener=_Broken()).parse(BytesSource(_docx(["a"]))))
        assert _texts(events) == ["a"]

    def test_router_dispatches_by_magic_bytes(self) -> None:
        router = ParserRouter({Format.DOCX: DocxParser(), Format.XLSX: XlsxParser()})
        assert _texts(list(router.parse(BytesSource(_docx(["routed docx"]), name="a.docx")))) == ["routed docx"]
        assert _texts(list(router.parse(BytesSource(_xlsx({"S": [["routed xlsx"]]}), name="b.xlsx")))) == ["routed xlsx"]

    def test_legacy_formats_are_explicitly_unsupported(self) -> None:
        router = ParserRouter({Format.DOCX: DocxParser(), Format.XLSX: XlsxParser()})
        for fmt in (Format.DOC, Format.XLS, Format.PPT, Format.PPTX, Format.ODT):
            with pytest.raises(FormatNotSupportedException, match="no parser registered"):
                router.route(fmt)
