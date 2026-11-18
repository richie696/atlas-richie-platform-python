"""Parse events, segments, sources and context.

Ported from `cn.richie696.component.parser` (Java). Java uses a sealed interface
with records; Python uses a small class hierarchy with frozen dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, BinaryIO


class Format(StrEnum):
    PDF = "PDF"
    DOCX = "DOCX"
    DOC = "DOC"
    XLSX = "XLSX"
    XLS = "XLS"
    PPTX = "PPTX"
    PPT = "PPT"
    ODT = "ODT"
    ODS = "ODS"
    ODP = "ODP"
    RTF = "RTF"
    TXT = "TXT"
    MD = "MD"
    HTML = "HTML"
    XML = "XML"
    UNKNOWN = "UNKNOWN"


class DocumentParseException(RuntimeError):
    """Parsing failed for a source."""


class FormatNotSupportedException(DocumentParseException):
    def __init__(self, format_name: str, reason: str) -> None:
        super().__init__(f"unsupported format {format_name}: {reason}")
        self.format_name = format_name
        self.reason = reason


class ImageOnlyPdfException(DocumentParseException):
    """A PDF carries no extractable text, only images (needs OCR).

    Raised only in strict mode; by default images are emitted as ImageStreaming
    events so the caller can route them to OCR/VLM instead of failing.
    """

    def __init__(
        self,
        image_count: int,
        text_chars: int,
        page_count: int = -1,
        name_hint: str = "",
    ) -> None:
        super().__init__(
            f"image-only PDF: {image_count} images, {text_chars} text chars"
            + (f", {page_count} pages" if page_count >= 0 else "")
            + (f" ({name_hint})" if name_hint else "")
        )
        self.image_count = image_count
        self.text_chars = text_chars
        self.page_count = page_count
        self.name_hint = name_hint


@dataclass(frozen=True, slots=True)
class DocumentSegment:
    text: str
    title: str | None = None
    section_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.text is None:
            raise ValueError("segment text must not be null")


@dataclass(frozen=True, slots=True)
class ImageSegment:
    data: bytes
    mime_type: str | None = None
    section_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DocumentSummary:
    title: str | None = None
    author: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ParseEvent:
    """Base parse event. `source_name` identifies where the event came from."""

    source_name: str = ""


@dataclass(frozen=True, slots=True)
class Streaming(ParseEvent):
    segment: DocumentSegment

    @property
    def source_name(self) -> str:  # type: ignore[override]
        return self.segment.section_path or ""


@dataclass(frozen=True, slots=True)
class ImageStreaming(ParseEvent):
    image: ImageSegment

    @property
    def source_name(self) -> str:  # type: ignore[override]
        return self.image.section_path or ""


@dataclass(frozen=True, slots=True)
class Finished(ParseEvent):
    summary: DocumentSummary
    segment_count: int
    image_count: int

    @property
    def source_name(self) -> str:  # type: ignore[override]
        return self.summary.title or ""


@dataclass(frozen=True, slots=True)
class Failed(ParseEvent):
    error: DocumentParseException

    @property
    def source_name(self) -> str:  # type: ignore[override]
        return str(self.error)


@dataclass(frozen=True, slots=True)
class ParserContext:
    max_segment_length: int | None = None
    emit_images: bool = False
    timeout: timedelta | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.max_segment_length is not None and self.max_segment_length <= 0:
            raise ValueError("max_segment_length must be > 0")
        if self.timeout is not None and self.timeout <= timedelta(0):
            raise ValueError("timeout must be positive")

    @classmethod
    def defaults(cls) -> ParserContext:
        return cls()


@dataclass(frozen=True, slots=True)
class FileSource:
    path: Path

    @property
    def name_hint(self) -> str:
        return self.path.name


@dataclass(frozen=True, slots=True)
class StreamSource:
    stream: BinaryIO
    name: str = ""

    @property
    def name_hint(self) -> str:
        return self.name


@dataclass(frozen=True, slots=True)
class BytesSource:
    data: bytes
    name: str = ""

    @property
    def name_hint(self) -> str:
        return self.name


@dataclass(frozen=True, slots=True)
class UrlSource:
    url: str

    @property
    def name_hint(self) -> str:
        return self.url


ParserSource = FileSource | StreamSource | BytesSource | UrlSource


__all__ = [
    "BytesSource",
    "DocumentParseException",
    "DocumentSegment",
    "DocumentSummary",
    "Failed",
    "FileSource",
    "Finished",
    "Format",
    "FormatNotSupportedException",
    "ImageOnlyPdfException",
    "ImageSegment",
    "ImageStreaming",
    "ParseEvent",
    "ParserContext",
    "ParserSource",
    "Streaming",
    "StreamSource",
    "UrlSource",
]
