"""HTML 解析适配器（beautifulsoup4 + lxml）。

对位 Java `TikaDocumentParser` 的 HTML 部分：按块级元素流式产出文本段，
只取最内层块以避免父子重复，剔除脚本/样式，标题进入 summary。

图片只处理 `data:` URI 内联资源；远程 `src` 不发起网络请求 —— 抓取是
`document-fetcher` 的职责，解析器保持无网络副作用。
"""

from __future__ import annotations

import base64
import binascii
import io
import time
from typing import BinaryIO, Iterator

from bs4 import BeautifulSoup

from atlas_richie.document_parser import (
    BytesSource,
    DocumentParseException,
    DocumentSegment,
    DocumentSummary,
    Failed,
    FileSource,
    Finished,
    FormatNotSupportedException,
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

BLOCK_TAGS = frozenset(
    {"p", "div", "td", "th", "li", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "blockquote"}
)
_DROP_TAGS = ("script", "style", "noscript", "template")
MAX_EMBEDDED_IMAGE_BYTES = 20 * 1024 * 1024


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


def _decode_data_uri(src: str) -> tuple[bytes, str | None] | None:
    if not src.startswith("data:"):
        return None
    header, _, payload = src[5:].partition(",")
    if not payload:
        return None
    mime = header.split(";")[0] or None
    try:
        data = base64.b64decode(payload, validate=False) if ";base64" in header else payload.encode("utf-8")
    except (binascii.Error, ValueError):
        return None
    return data, mime


class HtmlParser:
    """`DocumentParser` for HTML/XML sources."""

    def __init__(
        self,
        *,
        max_embedded_image_bytes: int = MAX_EMBEDDED_IMAGE_BYTES,
        listener: ParseListener | None = None,
        features: str = "lxml",
    ) -> None:
        if max_embedded_image_bytes <= 0:
            raise ValueError("max_embedded_image_bytes must be positive")
        self._max_image_bytes = int(max_embedded_image_bytes)
        self._bus = ListenerBus([listener] if listener is not None else [])
        self._features = features

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
                DocumentParseException(f"HTML parse failed: {source.name_hint}: {error}")
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
            raw = stream.read()
            soup = BeautifulSoup(raw, self._features_for(raw))
            for tag in soup(list(_DROP_TAGS)):
                tag.decompose()
            title_tag = soup.find("title")
            title = title_tag.get_text(strip=True) if title_tag else None

            segments = 0
            images = 0
            for order, block in enumerate(self._leaf_blocks(soup), start=1):
                if deadline is not None and time.monotonic() > deadline:
                    raise DocumentParseException(
                        f"HTML parse exceeded timeout at block {order}: {name_hint}"
                    )
                text = block.get_text(" ", strip=True)
                if not text:
                    continue
                for piece in self._split(text, context.max_segment_length):
                    yield Streaming(
                        DocumentSegment(
                            piece,
                            None,
                            f"/{name_hint}/Block[{segments + 1}]",
                            {"tag": block.name, "order": order, "format": "text/html"},
                        )
                    )
                    segments += 1
            if context.emit_images:
                for image in self._inline_images(soup, name_hint):
                    images += 1
                    yield image
            yield Finished(
                DocumentSummary(title, None, {"format": "text/html"}), segments, images
            )
        finally:
            if owns:
                stream.close()

    def _features_for(self, raw: bytes) -> str:
        """XML 声明开头时用 XML parser，否则 bs4 会按 HTML 解析并告警。"""
        if self._features != "lxml":
            return self._features
        head = raw.lstrip(b"\xef\xbb\xbf \t\r\n")[:64].lower()
        return "xml" if head.startswith(b"<?xml") else "lxml"

    @staticmethod
    def _leaf_blocks(soup) -> Iterator:
        for element in soup.find_all(sorted(BLOCK_TAGS)):
            if element.find(sorted(BLOCK_TAGS)) is None:
                yield element

    def _inline_images(self, soup, name_hint: str) -> Iterator[ImageStreaming]:
        for order, img in enumerate(soup.find_all("img"), start=1):
            decoded = _decode_data_uri(img.get("src") or "")
            if decoded is None:
                continue
            data, mime = decoded
            if not data or len(data) > self._max_image_bytes:
                continue
            yield ImageStreaming(
                ImageSegment(
                    data,
                    mime or "image/png",
                    f"/{name_hint}/Image[{order}]",
                    {"order": order, "alt": img.get("alt")},
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


__all__ = ["HtmlParser", "BLOCK_TAGS", "MAX_EMBEDDED_IMAGE_BYTES"]