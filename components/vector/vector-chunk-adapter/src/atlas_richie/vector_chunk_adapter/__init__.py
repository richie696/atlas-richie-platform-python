"""chunk → 未嵌入向量记录的桥接。

对位 Java `cn.richie696.component.vector.chunk.ChunkVectorRecordMapper`。

记录 id 采用 `documentId:version:ordinal` 三段式：同一文档同一版本重跑切分
得到相同 id，因此写入是幂等 upsert；版本变化则产生新 id，旧版本记录可按
documentId + version 清理，不会与新版本混淆。

metadata 键名沿用 Java 的 camelCase（chunkOrdinal / charStart / charEnd），
以便与 Java 侧写入的记录互相读取。

本包不做嵌入：产出的 `VectorRecord.vector` 为 None，由调用方注入嵌入服务后
再写入 provider。这样桥接层保持零第三方依赖。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from atlas_richie.chunking_core import Chunk
from atlas_richie.vector_core import TextContent, VectorRecord


@dataclass(frozen=True, slots=True)
class VectorRecordContext:
    index_name: str
    document_id: str
    version: int
    namespace: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


class ChunkVectorRecordMapper:
    def map(
        self,
        chunk: Chunk,
        context: VectorRecordContext,
        *,
        ordinal: int | None = None,
    ) -> VectorRecord:
        """Map one chunk. `ordinal` overrides the chunk-local ordinal.

        Chunking restarts ordinals at 0 for each section, so mapping several
        sections of one document with chunk-local ordinals would collide on
        `documentId:version:ordinal`. Use `map_sections` for a whole document,
        or pass a document-global `ordinal` here.
        """
        if chunk is None:
            raise ValueError("chunk must not be None")
        if context is None:
            raise ValueError("context must not be None")
        position = chunk.ordinal if ordinal is None else ordinal
        if position < 0:
            raise ValueError("ordinal must be >= 0")
        meta = dict(context.metadata or {})
        meta["chunkOrdinal"] = position
        meta["charStart"] = chunk.char_start
        meta["charEnd"] = chunk.char_end
        return VectorRecord(
            id=f"{context.document_id}:{context.version}:{position}",
            index_name=context.index_name,
            content=TextContent(chunk.text),
            document_id=context.document_id,
            chunk_no=position,
            version=context.version,
            namespace=context.namespace,
            metadata=meta,
        )


    def map_sections(
        self,
        sections: Iterable[Iterable[Chunk]],
        context: VectorRecordContext,
    ) -> list[VectorRecord]:
        """Map a whole document, assigning document-global ordinals.

        Java's mapper has no equivalent and would collide when a document
        yields multiple independent sections; this keeps the same id format
        while making the identity actually unique.
        """
        records: list[VectorRecord] = []
        ordinal = 0
        for section in sections:
            for chunk in section:
                records.append(self.map(chunk, context, ordinal=ordinal))
                ordinal += 1
        return records


__all__ = ["VectorRecordContext", "ChunkVectorRecordMapper"]