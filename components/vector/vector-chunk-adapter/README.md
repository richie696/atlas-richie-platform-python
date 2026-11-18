# atlas-richie-vector-chunk-adapter

把 `chunking-core` 的 `Chunk` 映射为 `vector-core` 的**未嵌入** `VectorRecord`。

对位 Java `atlas-richie-vector-chunk-adapter`（122 行）。这是 RAG 摄入侧的桥：
parse → chunk → **vector record** → 嵌入 → 写入 provider。

只依赖 `chunking-core` + `vector-core`，两者零第三方依赖，故本包亦无外部驱动。

## 记录身份

id 为 `documentId:version:ordinal` 三段式：

- 同一文档同一版本重跑切分 → 相同 id → 写入是幂等 upsert；
- 版本变化 → 新 id，旧版本可按 `documentId` + `version` 清理，不与新版本混淆。

metadata 键名沿用 Java camelCase（`chunkOrdinal` / `charStart` / `charEnd`），
便于与 Java 侧写入的记录互读。

## 用法

```python
from atlas_richie.chunking_core import DefaultChunkingService
from atlas_richie.vector_chunk_adapter import ChunkVectorRecordMapper, VectorRecordContext

result = DefaultChunkingService().chunk("文档正文……")
context = VectorRecordContext(
    index_name="kb", document_id="doc-1", version=3, namespace="tenant-7",
    metadata={"knowledgeBaseId": "kb", "tenantId": 7},
)
records = [ChunkVectorRecordMapper().map(c, context) for c in result.chunks]
# records[i].vector is None —— 由调用方注入嵌入服务后再写入 provider
```

与 `chunking-parser-adapter` 串联即得完整摄入链：解析事件 → 带溯源区间的
chunk → 向量记录。