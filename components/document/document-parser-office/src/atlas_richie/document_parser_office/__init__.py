"""OOXML 解析适配器：DOCX（python-docx）与 XLSX（openpyxl）。

只覆盖 OOXML。旧二进制格式（DOC/XLS/PPT）与 PPTX/ODF 显式抛
`FormatNotSupportedException`，而不是静默返回空文本 —— Java 靠 Tika+POI
覆盖这些格式，Python 无等价单一依赖，宁可明确拒绝也不给假成功。

XLSX 用 `read_only=True` + `data_only=True` 流式读取，避免整表进内存，
并取公式的缓存计算值而非公式字符串。
"""

from __future__ import annotations

import io
import time
from typing import BinaryIO, Iterator

from docx import Document
from openpyxl import load_workbook

from atlas_richie.document_parser import (
    BytesSource,
    DocumentParseException,
    DocumentSegment,
    DocumentSummary,
    Failed,
    FileSource,
    Finished,
    FormatNotSupportedException,
    ListenerBus,
    ParseEvent,
    ParseListener,
    ParserContext,
    ParserSource,
    StreamSource,
    Streaming,
    UrlSource,
)


def _open(source: ParserSource) -> tuple[BinaryIO, bool]:
    if isinstance(source, BytesSource):
        return io.BytesIO(source.data), True
    if isinstance(source, FileSource):
        return open(source.path, "rb"), True
    if isinstance(source, StreamSource):
        return source.stream, False
    if isinstance(source, UrlSource):
        raise FormatNotSupportedException(
            "url", "download the URL into bytes or a stream before parsing (see document-fetcher)"
        )
    raise FormatNotSupportedException("unknown", f"unsupported source {type(source).__name__}")


def _split(text: str, limit: int | None) -> Iterator[str]:
    if limit is None or len(text) <= limit:
        yield text
        return
    for start in range(0, len(text), limit):
        piece = text[start : start + limit].strip()
        if piece:
            yield piece


class _OfficeParser:
    """Shared event/error/timeout plumbing for the OOXML adapters."""

    format_name = "application/octet-stream"

    def __init__(self, *, listener: ParseListener | None = None) -> None:
        self._bus = ListenerBus([listener] if listener is not None else [])

    def parse(
        self, source: ParserSource, context: ParserContext | None = None
    ) -> Iterator[ParseEvent]:
        context = context if context is not None else ParserContext.defaults()
        try:
            for event in self._parse(source, context):
                self._bus.dispatch(event)
                yield event
        except DocumentParseException as error:
            failed = Failed(error)
            self._bus.dispatch(failed)
            yield failed
        except Exception as error:  # noqa: BLE001 — surfaced as Failed, as in the text fast path
            failed = Failed(
                DocumentParseException(
                    f"{type(self).__name__} parse failed: {source.name_hint}: {error}"
                )
            )
            self._bus.dispatch(failed)
            yield failed

    def _parse(
        self, source: ParserSource, context: ParserContext
    ) -> Iterator[ParseEvent]:
        raise NotImplementedError

    @staticmethod
    def _deadline(context: ParserContext) -> float | None:
        return (
            time.monotonic() + context.timeout.total_seconds()
            if context.timeout is not None
            else None
        )

    @staticmethod
    def _check_deadline(deadline: float | None, where: str, name_hint: str) -> None:
        if deadline is not None and time.monotonic() > deadline:
            raise DocumentParseException(
                f"parse exceeded timeout at {where}: {name_hint}"
            )


class DocxParser(_OfficeParser):
    """DOCX: paragraphs and table rows as segments."""

    format_name = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

    def _parse(
        self, source: ParserSource, context: ParserContext
    ) -> Iterator[ParseEvent]:
        stream, owns = _open(source)
        name_hint = source.name_hint
        deadline = self._deadline(context)
        try:
            document = Document(stream)
            title = document.core_properties.title or None
            segments = 0
            for order, paragraph in enumerate(document.paragraphs, start=1):
                self._check_deadline(deadline, f"paragraph {order}", name_hint)
                text = paragraph.text.strip()
                if not text:
                    continue
                style = paragraph.style.name if paragraph.style is not None else None
                for piece in _split(text, context.max_segment_length):
                    yield Streaming(
                        DocumentSegment(
                            piece,
                            None,
                            f"/{name_hint}/Paragraph[{segments + 1}]",
                            {"order": order, "style": style, "format": self.format_name},
                        )
                    )
                    segments += 1
            for table_index, table in enumerate(document.tables, start=1):
                for row_index, row in enumerate(table.rows, start=1):
                    self._check_deadline(
                        deadline, f"table {table_index} row {row_index}", name_hint
                    )
                    cells = [cell.text.strip() for cell in row.cells]
                    text = " | ".join(c for c in cells if c)
                    if not text:
                        continue
                    for piece in _split(text, context.max_segment_length):
                        yield Streaming(
                            DocumentSegment(
                                piece,
                                None,
                                f"/{name_hint}/Table[{table_index}]/Row[{row_index}]",
                                {
                                    "table": table_index,
                                    "row": row_index,
                                    "format": self.format_name,
                                },
                            )
                        )
                        segments += 1
            yield Finished(
                DocumentSummary(title, None, {"format": self.format_name}), segments, 0
            )
        finally:
            if owns:
                stream.close()


class XlsxParser(_OfficeParser):
    """XLSX: one segment per non-empty row, per sheet."""

    format_name = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    def _parse(
        self, source: ParserSource, context: ParserContext
    ) -> Iterator[ParseEvent]:
        stream, owns = _open(source)
        name_hint = source.name_hint
        deadline = self._deadline(context)
        workbook = None
        try:
            workbook = load_workbook(stream, read_only=True, data_only=True)
            segments = 0
            for sheet in workbook.worksheets:
                for row_index, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                    self._check_deadline(
                        deadline, f"sheet {sheet.title} row {row_index}", name_hint
                    )
                    cells = ["" if v is None else str(v).strip() for v in row]
                    text = " | ".join(c for c in cells if c)
                    if not text:
                        continue
                    for piece in _split(text, context.max_segment_length):
                        yield Streaming(
                            DocumentSegment(
                                piece,
                                None,
                                f"/{name_hint}/Sheet[{sheet.title}]/Row[{row_index}]",
                                {
                                    "sheet": sheet.title,
                                    "row": row_index,
                                    "format": self.format_name,
                                },
                            )
                        )
                        segments += 1
            yield Finished(
                DocumentSummary(
                    None,
                    None,
                    {"format": self.format_name, "sheets": len(workbook.worksheets)},
                ),
                segments,
                0,
            )
        finally:
            if workbook is not None:
                workbook.close()
            if owns:
                stream.close()


__all__ = ["DocxParser", "XlsxParser"]