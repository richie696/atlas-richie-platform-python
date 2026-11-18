"""document-parser → chunking 桥接（零第三方依赖）。"""

from __future__ import annotations

from .adapter import ParserChunkingAdapter
from .model import (
    ChunkedSection,
    ChunkingEvent,
    Failed,
    Finished,
    Section,
    SourceSpan,
)

__all__ = [
    "ParserChunkingAdapter",
    "SourceSpan",
    "ChunkedSection",
    "ChunkingEvent",
    "Section",
    "Finished",
    "Failed",
]