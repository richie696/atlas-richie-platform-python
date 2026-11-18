"""投影写入器：把 bulk 写入事件投影成版本状态切换与 manifest 落库。

对应 Java `cn.richie696.component.vector.projection.impl.DefaultVectorProjectionWriter`。

它是状态机在写入侧的"镜像 sink"：bulk 流水线只管把记录写进向量库并发出事件，
不知道投影的存在；本类把事件回调到状态机——
- `BulkItemSucceeded` → `record_succeeded`（写 vectorId manifest + 累加计数）；
- `BulkItemFailed`    → `record_failure`（累加失败计数 + 刷新失败原因）；
- 流正常结束           → `mark_ready_if_no_failure`（有失败则 FAILED，否则 READY）；
- 流异常终止           → `mark_failed`。

每条写入的记录还会被补齐 6 个固定 metadata 字段（tenant / knowledgeBase /
projection / version / sourceVersion / embeddingSpace）+ `status=ACTIVE`，
检索阶段因此无需回查关系库就能拿到版本归属；`projectionVersionId` 正是
检索门面下推 `IN (...)` 的那个字段。
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Iterable, Iterator

from atlas_richie.vector_core.bulk import (
    BulkIngestionPipeline,
    BulkItemFailed,
    BulkItemSucceeded,
    BulkOperationEvent,
)
from atlas_richie.vector_core.model import VectorRecord
from atlas_richie.vector_core.projection import VectorProjectionVersion

from .projection import VectorProjectionStore

_log = logging.getLogger(__name__)


class VectorProjectionWriter:
    """把记录流写入某个投影版本，并同步维护 vectorId manifest。

    调用顺序：`begin_rebuild` → `write`（消费完事件流）→ `activate`。
    """

    def __init__(
        self,
        lifecycle: VectorProjectionStore,
        bulk: BulkIngestionPipeline,
    ) -> None:
        if lifecycle is None:
            raise ValueError("lifecycle is required")
        if bulk is None:
            raise ValueError("bulk is required")
        self._lifecycle = lifecycle
        self._bulk = bulk

    def write(
        self, version_id: str, records: Iterable[VectorRecord]
    ) -> Iterator[BulkOperationEvent]:
        """写入记录并驱动版本状态机。

        返回惰性迭代器：状态推进与 manifest 落库都发生在**迭代过程中**，
        与 Java 的冷流语义一致——调用方必须消费到底才能走到 READY。
        """
        version = self._lifecycle.find_version(version_id)
        if version is None:
            raise ValueError(f"projection version does not exist: {version_id}")
        if version.state.is_terminal:
            raise ValueError(
                f"projection version is already in a terminal state: {version_id}"
            )
        self._lifecycle.mark_writing(version_id)
        try:
            for event in self._bulk.execute(
                version.specification.index_name, self._decorated(records, version)
            ):
                self._observe(version_id, event)
                yield event
        except Exception as error:  # noqa: BLE001 — 写入流异常要把版本置 FAILED
            self._lifecycle.mark_failed(version_id, str(error))
            _log.warning("projection write failed, version=%s", version_id)
            raise
        self._lifecycle.mark_ready_if_no_failure(version_id)

    def _decorated(
        self, records: Iterable[VectorRecord], version: VectorProjectionVersion
    ) -> Iterator[VectorRecord]:
        """惰性装饰记录。

        必须是生成器函数而不是生成器表达式：表达式会在**创建时**就调用
        `iter(records)`，记录源若在 `__iter__` 里抛错，异常会绕过 bulk
        管线的事件降级机制。这里把取记录推迟到管线内部，源异常才会被管线
        捕获成失败事件（对位 Java 的 `onErrorResume`）。
        """
        for record in records:
            yield self._decorate(record, version)

    def _observe(self, version_id: str, event: BulkOperationEvent) -> None:
        """把单条 bulk 事件回调到状态机。"""
        if isinstance(event, BulkItemSucceeded):
            self._lifecycle.record_succeeded(version_id, event.vector_id)
        elif isinstance(event, BulkItemFailed):
            self._lifecycle.record_failure(
                version_id, f"{event.error_code}: {event.message}"
            )

    def _decorate(
        self, record: VectorRecord, version: VectorProjectionVersion
    ) -> VectorRecord:
        """把版本信息投影到记录的 metadata 上。

        索引名不一致直接失败——把记录写进另一个索引会绕过"按版本隔离检索"的
        边界，事后极难发现。
        """
        if record is None:
            raise ValueError("record must not be None")
        index_name = version.specification.index_name
        prepared = record
        if not record.index_name or not record.index_name.strip():
            prepared = replace(prepared, index_name=index_name)
        if prepared.index_name != index_name:
            raise ValueError("record index_name does not match the projection version")
        metadata = dict(prepared.metadata) if isinstance(prepared.metadata, dict) else {}
        metadata.update(
            {
                "tenantId": version.reference.tenant_id,
                "knowledgeBaseId": version.reference.knowledge_base_id,
                "projectionId": version.projection_id,
                "projectionVersionId": version.version_id,
                "sourceVersion": version.specification.source_version,
                "embeddingSpaceId": version.specification.embedding_space_id,
                "status": "ACTIVE",
            }
        )
        return replace(
            prepared,
            document_id=version.reference.document_ref,
            metadata=metadata,
        )


__all__ = ["VectorProjectionWriter"]
