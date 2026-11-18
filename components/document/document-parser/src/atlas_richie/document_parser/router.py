"""Parser routing by detected format.

The Java router hard-wires Tika and Fesod parsers. Here the router is a registry:
the zero-dependency text/Markdown fast path is built in, and PDF/Office/HTML
parsers are registered by adapter packages (optional extras), so the core never
depends on a heavy parsing library.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

from .detection import SNIFF_BUFFER_SIZE, detect_format
from .model import (
    BytesSource,
    FileSource,
    Format,
    FormatNotSupportedException,
    ParseEvent,
    ParserContext,
    ParserSource,
)
from .text import TextFastPathParser


class DocumentParser(Protocol):
    def parse(self, source: ParserSource, context: ParserContext | None = None) -> Iterator[ParseEvent]:
        ...


class ParserRouter:
    def __init__(self, parsers: dict[Format, DocumentParser] | None = None) -> None:
        self._parsers: dict[Format, DocumentParser] = {
            Format.TXT: TextFastPathParser(),
            Format.MD: TextFastPathParser(),
        }
        if parsers:
            self._parsers.update(parsers)

    def register(self, fmt: Format, parser: DocumentParser) -> None:
        self._parsers[fmt] = parser

    def registered_formats(self) -> tuple[Format, ...]:
        return tuple(sorted(self._parsers, key=lambda fmt: fmt.value))

    def route(self, fmt: Format | None) -> DocumentParser:
        if fmt is None:
            raise FormatNotSupportedException("null", "Format is null")
        parser = self._parsers.get(fmt)
        if parser is None:
            if fmt is Format.UNKNOWN:
                raise FormatNotSupportedException(
                    "unknown",
                    "Document format could not be detected. Provide a file with a "
                    "recognized extension or content type.",
                )
            raise FormatNotSupportedException(
                fmt.value,
                "no parser registered for this format; install the matching adapter extra",
            )
        return parser

    def parse(self, source: ParserSource, context: ParserContext | None = None) -> Iterator[ParseEvent]:
        """Detect the format from content (extension as fallback) and route."""
        head, name_hint = _sniff_source(source)
        fmt = detect_format(head, name_hint)
        return self.route(fmt).parse(source, context)

    def parse_file(self, path: str | Path, context: ParserContext | None = None) -> Iterator[ParseEvent]:
        return self.parse(FileSource(Path(path)), context)


def _sniff_source(source: ParserSource) -> tuple[bytes, str]:
    if isinstance(source, BytesSource):
        return source.data[:SNIFF_BUFFER_SIZE], source.name_hint
    if isinstance(source, FileSource):
        with open(source.path, "rb") as handle:
            return handle.read(SNIFF_BUFFER_SIZE), source.name_hint
    if hasattr(source, "stream"):
        stream = source.stream
        position = stream.tell() if stream.seekable() else None
        head = stream.read(SNIFF_BUFFER_SIZE)
        if position is not None:
            stream.seek(position)
        return head, source.name_hint
    raise FormatNotSupportedException(
        "url", "a URL source must be downloaded into a stream or bytes before parsing"
    )


__all__ = ["DocumentParser", "ParserRouter"]
