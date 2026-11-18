"""向量检索的值对象。

对应 Java `cn.richie696.component.vector.model`。Java 侧用 Lombok 可变
bean，这里改为 frozen dataclass：检索结果在 provider 与 diversifier 之间
传递时不应被就地改写，需要变更时用 `dataclasses.replace`。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Mapping

from .filters import VectorFilter


class Modality(StrEnum):
    TEXT = "TEXT"
    IMAGE = "IMAGE"


@dataclass(frozen=True, slots=True)
class TextContent:
    text: str
    mime_type: str = "text/plain"

    def __post_init__(self) -> None:
        if not self.text or not self.text.strip():
            raise ValueError("TextContent.text must not be blank")
        if not self.mime_type or not self.mime_type.strip():
            object.__setattr__(self, "mime_type", "text/plain")

    @property
    def modality(self) -> Modality:
        return Modality.TEXT


@dataclass(frozen=True, slots=True)
class ImageContent:
    data: bytes
    mime_type: str

    def __post_init__(self) -> None:
        if not self.data:
            raise ValueError("ImageContent.data must not be empty")
        if not self.mime_type or not self.mime_type.startswith("image/"):
            raise ValueError(
                f"ImageContent.mime_type must be image/*, got {self.mime_type!r}"
            )

    @property
    def modality(self) -> Modality:
        return Modality.IMAGE


VectorContent = TextContent | ImageContent


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class VectorRecord:
    """待写入向量库的一条记录。"""

    META_ITEM_ID = "__itemId"

    id: str
    index_name: str
    content: VectorContent
    vector: tuple[float, ...] | None = None
    document_id: str | None = None
    chunk_no: int | None = None
    version: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] | None = None
    source: str | None = None
    namespace: str | None = None
    status: str = "ACTIVE"
    score: float | None = None
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    @classmethod
    def text(
        cls,
        index_name: str,
        text: str,
        *,
        id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        vector: tuple[float, ...] | None = None,
    ) -> VectorRecord:
        return cls(
            id=id or str(uuid.uuid4()),
            index_name=index_name,
            content=TextContent(text),
            vector=vector,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def image(
        cls,
        index_name: str,
        data: bytes,
        mime_type: str,
        *,
        id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        vector: tuple[float, ...] | None = None,
    ) -> VectorRecord:
        return cls(
            id=id or str(uuid.uuid4()),
            index_name=index_name,
            content=ImageContent(data, mime_type),
            vector=vector,
            metadata=dict(metadata or {}),
        )

    def with_vector(self, vector: tuple[float, ...]) -> VectorRecord:
        return replace(self, vector=tuple(vector))


@dataclass(frozen=True, slots=True)
class VectorSearchResult:
    """一条检索命中。`vector` 仅在 provider 声明 CANDIDATE_VECTOR 时填充。"""

    id: str | None = None
    content: str | None = None
    score: float | None = None
    vector: tuple[float, ...] | None = None
    type: str | None = None
    tags: tuple[str, ...] | None = None
    source: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    document_score: float | None = None
    status: str | None = None
    metadata: Any = None
    namespace: str | None = None

    @classmethod
    def of(
        cls,
        id: str,
        content: str | None,
        score: float | None,
        vector: tuple[float, ...] | None = None,
    ) -> VectorSearchResult:
        return cls(id=id, content=content, score=score, vector=vector)


@dataclass(frozen=True, slots=True)
class SearchOptions:
    rerank: bool = True
    rerank_model: str | None = None
    min_score: float | None = None
    filter: VectorFilter | None = None
    namespace: str | None = None
    limit: int | None = None
    type: str | None = None
    provider_search_parameters: Mapping[str, int] = field(default_factory=dict)
    timeout: timedelta | None = None
    include_candidate_vectors: bool = False


@dataclass(frozen=True, slots=True)
class HybridSearchOptions:
    vector_weight: float = 0.7
    keyword_weight: float = 0.3
    keyword_query: str | None = None
    search_options: SearchOptions | None = None


__all__ = [
    "Modality",
    "TextContent",
    "ImageContent",
    "VectorContent",
    "VectorRecord",
    "VectorSearchResult",
    "SearchOptions",
    "HybridSearchOptions",
]