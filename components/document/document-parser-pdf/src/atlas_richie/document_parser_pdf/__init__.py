"""PDF 解析适配器（pypdf）。

对位 Java `TikaDocumentParser` 的 PDF 部分。逐页产出文本段，可选抽取内嵌
图片，并支持**opt-in** 的纯图 PDF fail-fast。

与 Java 一致的默认行为：纯图检测默认**关闭**，图片以 `ImageStreaming` 事件
发出，由业务方自行走 OCR/VLM；只有显式 `enabled=True` 才抛
`ImageOnlyPdfException`。判定阈值同 Java：
`(textChars < min_text_chars and imageCount >= min_image_count) or textChars < 50`。

异常按 core 约定包装成 `Failed` 事件（异常类型保留在 `Failed.error` 里），
而不是直接抛出，以便与文本快路径的事件流契约一致。

图片抽取需要 Pillow（通过 `pypdf[image]` 引入）：pypdf 的 `page.images`
会解码并重编码为 PNG，因此 MIME 由返回名字的扩展名推断。
"""

from __future__ import annotations

import io
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator

from pypdf import PdfReader

from atlas_richie.document_parser import (
    BytesSource,
    DocumentParseException,
    DocumentSegment,
    DocumentSummary,
    Failed,
    FileSource,
    Finished,
    FormatNotSupportedException,
    ImageOnlyPdfException,
    ImageSegment,
    ImageStreaming,
    ListenerBus,
    ParseEvent,
    ParseListener,
    ParserContext,
    ParserSource,
    StreamSource,
    Streaming,
    UrlSource,
)

MAX_EMBEDDED_IMAGE_BYTES = 20 * 1024 * 1024

_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".webp": "image/webp",
}


@dataclass(frozen=True, slots=True)
class ImageOnlyDetection:
    enabled: bool = False
    min_text_chars: int = 200
    min_image_count: int = 5
    almost_empty_chars: int = 50

    def __post_init__(self) -> None:
        if self.min_text_chars < 0 or self.min_image_count < 0 or self.almost_empty_chars < 0:
            raise ValueError("image-only detection thresholds must be >= 0")

    def triggers(self, text_chars: int, image_count: int) -> bool:
        if not self.enabled:
            return False
        return (
            text_chars < self.min_text_chars and image_count >= self.min_image_count
        ) or text_chars < self.almost_empty_chars


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


def _mime_of(name: str) -> str | None:
    return _IMAGE_MIME.get(Path(name).suffix.lower())


class PdfParser:
    """`DocumentParser` for PDF sources."""

    def __init__(
        self,
        *,
        image_only_detection: ImageOnlyDetection | None = None,
        max_embedded_image_bytes: int = MAX_EMBEDDED_IMAGE_BYTES,
        listener: ParseListener | None = None,
    ) -> None:
        if max_embedded_image_bytes <= 0:
            raise ValueError("max_embedded_image_bytes must be positive")
        self._detection = image_only_detection or ImageOnlyDetection()
        self._max_image_bytes = int(max_embedded_image_bytes)
        self._bus = ListenerBus([listener] if listener is not None else [])

    @property
    def image_only_detection(self) -> ImageOnlyDetection:
        return self._detection

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
                DocumentParseException(f"PDF parse failed: {source.name_hint}: {error}")
            )
            self._bus.dispatch(failed)
            yield failed

    def _parse(
        self, source: ParserSource, context: ParserContext
    ) -> Iterator[ParseEvent]:
        stream, owns = _open(source)
        name_hint = source.name_hint
        deadline = (
            time.monotonic() + context.timeout.total_seconds()
            if context.timeout is not None
            else None
        )
        try:
            reader = PdfReader(stream)
            title = None
            if reader.metadata is not None:
                title = reader.metadata.title
            segments = 0
            images = 0
            text_chars = 0
            for page_number, page in enumerate(reader.pages, start=1):
                if deadline is not None and time.monotonic() > deadline:
                    raise DocumentParseException(
                        f"PDF parse exceeded timeout at page {page_number}: {name_hint}"
                    )
                text = (page.extract_text() or "").strip()
                if text:
                    text_chars += len(text)
                    for piece in self._split(text, context.max_segment_length):
                        yield Streaming(
                            DocumentSegment(
                                piece,
                                None,
                                f"/{name_hint}/Page[{page_number}]",
                                {"page": page_number, "format": "application/pdf"},
                            )
                        )
                        segments += 1
                if context.emit_images:
                    for image in self._page_images(page, page_number, name_hint):
                        images += 1
                        yield image
            if self._detection.triggers(text_chars, images):
                raise ImageOnlyPdfException(
                    images, text_chars, len(reader.pages), name_hint
                )
            yield Finished(
                DocumentSummary(
                    title,
                    None,
                    {"format": "application/pdf", "pages": len(reader.pages)},
                ),
                segments,
                images,
            )
        finally:
            if owns:
                stream.close()

    def _page_images(
        self, page, page_number: int, name_hint: str
    ) -> Iterator[ImageStreaming]:
        try:
            found = page.images
        except Exception:  # noqa: BLE001 — 图片抽取失败不应让整份文档解析失败
            return
        for image in found:
            try:
                data = image.data
            except Exception:  # noqa: BLE001
                continue
            if not data or len(data) > self._max_image_bytes:
                continue
            yield ImageStreaming(
                ImageSegment(
                    data,
                    _mime_of(image.name),
                    f"/{name_hint}/Page[{page_number}]",
                    {"page": page_number, "name": image.name},
                )
            )

    @staticmethod
    def _split(text: str, limit: int | None) -> Iterator[str]:
        if limit is None or len(text) <= limit:
            yield text
            return
        for start in range(0, len(text), limit):
            piece = text[start : start + limit].strip()
            if piece:
                yield piece


__all__ = ["PdfParser", "ImageOnlyDetection", "MAX_EMBEDDED_IMAGE_BYTES"]