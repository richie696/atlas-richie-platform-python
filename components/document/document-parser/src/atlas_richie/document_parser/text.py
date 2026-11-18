"""Streaming text/Markdown parser — the zero-dependency fast path.

Ported from `TextFastPathParser` (Java): read line by line, emit a segment as soon
as a paragraph boundary (a blank line) is reached rather than buffering the whole
document, and force a split when `max_segment_length` is exceeded.

Section paths and metadata match the Java shape: `/{name}/Paragraph[{order+1}]`
with `order` and `format` in metadata, and a `Finished` event carrying
`format=text/plain`, `encoding=UTF-8`.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

from .model import (
    BytesSource,
    DocumentParseException,
    DocumentSegment,
    DocumentSummary,
    Failed,
    FileSource,
    Finished,
    ParseEvent,
    ParserContext,
    ParserSource,
    Streaming,
    StreamSource,
    UrlSource,
)


def supports(name_hint: str | None) -> bool:
    if not name_hint:
        return False
    lower = name_hint.lower()
    return lower.endswith((".txt", ".md", ".markdown"))


def _open(source: ParserSource) -> BinaryIO:
    if isinstance(source, FileSource):
        try:
            return open(source.path, "rb")
        except OSError as error:
            raise DocumentParseException(f"File not found: {source.path}") from error
    if isinstance(source, StreamSource):
        return source.stream
    if isinstance(source, BytesSource):
        return io.BytesIO(source.data)
    raise DocumentParseException(
        "TextFastPathParser does not accept a URL source directly; "
        "download it into a stream first"
    )


class TextFastPathParser:
    """Parses plain text and Markdown into paragraph segments."""

    def parse(self, source: ParserSource, context: ParserContext | None = None) -> Iterator[ParseEvent]:
        context = context if context is not None else ParserContext.defaults()
        try:
            yield from self._parse(source, context)
        except DocumentParseException as error:
            yield Failed(error)
        except Exception as error:  # noqa: BLE001 — surfaced as a Failed event, as in Java
            yield Failed(
                DocumentParseException(f"TextFastPath parse failed: {source.name_hint}")
            )

    def _parse(self, source: ParserSource, context: ParserContext) -> Iterator[ParseEvent]:
        name_hint = source.name_hint
        stream = _open(source)
        owns_stream = isinstance(source, (FileSource, BytesSource))
        try:
            paragraph: list[str] = []
            order = 0
            for raw_line in io.TextIOWrapper(stream, encoding="utf-8", newline=""):
                line = raw_line.rstrip("\r\n")
                if not line.strip():
                    if paragraph:
                        text = "\n".join(paragraph).strip()
                        paragraph = []
                        for event in self._emit(text, name_hint, order, context):
                            order += 1
                            yield event
                    continue
                paragraph.append(line)
                joined = "\n".join(paragraph)
                while context.max_segment_length is not None and len(joined) >= context.max_segment_length:
                    end = context.max_segment_length
                    head, joined = joined[:end], joined[end:]
                    for event in self._emit(head.strip(), name_hint, order, context):
                        order += 1
                        yield event
                paragraph = joined.split("\n") if joined else []
            if paragraph:
                text = "\n".join(paragraph).strip()
                for event in self._emit(text, name_hint, order, context):
                    order += 1
                    yield event
            yield Finished(
                DocumentSummary(None, None, {"format": "text/plain", "encoding": "UTF-8"}),
                order,
                0,
            )
        finally:
            if owns_stream:
                stream.close()

    @staticmethod
    def _emit(text: str, source_name: str, order: int, context: ParserContext) -> Iterator[ParseEvent]:
        normalized = text.strip() if text else ""
        if not normalized:
            return
        yield Streaming(
            DocumentSegment(
                normalized,
                None,
                f"/{source_name}/Paragraph[{order + 1}]",
                {"order": order, "format": "text/plain"},
            )
        )


__all__ = ["TextFastPathParser", "supports"]
