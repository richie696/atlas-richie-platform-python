"""向量批量入库编排：嵌入 → 攒批 → 持久化（零第三方依赖）。

对应 Java `cn.richie696.component.vector.bulk`：`BulkIngestionPipeline` 与它的事件
协议 `BulkOperationEvent` / `BulkProcessingStage` / `BulkOperationSummary`。

为什么需要这层：RAG 入库是"上万条记录"的批量作业，业务侧要的不是一次
`upsert(records) -> int`，而是**可观察的进度与失败归因**——哪一条在嵌入阶段
挂了、哪一批落库失败、成功多少条、失败多少条。事件流就是这份协议：
业务埋点（投影写入器）、入库门面、运维看板订阅同一份流，无需知道具体 provider。

本模块只编排三段流程，不依赖任何 provider 实现：provider 通过两个函数式 SPI
（`RecordEmbedder` 嵌入、`EmbeddedRecordWriter` 落库）接入；也可走"库管嵌入"
分支（`StoreManagedRecordWriter`），此时事件流里不出现 EMBEDDING 阶段。

与 Java 的两处差异（已核对 Java 源码）：
1. **同步生成器而非反应式流**。Python 侧 `VectorStoreEngine` 协议本身是同步的，
   本模块用生成器表达"冷流"语义——`execute()` 返回的是惰性迭代器，迭代才真正开始，
   每次调用都是一次新执行。事件顺序因此是确定的（Java 的并发流会交错）。
2. **不提供并发度与时间窗刷批旋钮**。Java 的 `embeddingConcurrency` /
   `writeConcurrency` / `writeFlushIntervalMs` 依赖 Reactor 调度器；同步管线没有
   对应语义，与其接受后默默忽略，不如不提供——只保留真正生效的
   `write_batch_size`（默认 100，与 Java 一致）与 `fail_fast`。

失败语义：单条记录的嵌入或落库异常被就地捕获并转成 `BulkItemFailed` 事件，
不会中断整批；无论成败，批次末尾总会发出一条 `BulkCompleted`（带终态统计），
让消费者有稳定的批次级收尾锚点。事件不暴露异常对象，只透出稳定的 `error_code`
（异常类名）与截断到 512 字符的 `message`，因此可安全跨线程/跨进程持久化。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Iterable, Iterator, Protocol, Sequence, runtime_checkable

from .embeddings import ModalityAwareEmbeddingService
from .model import VectorRecord

MAX_ERROR_MESSAGE_LENGTH = 512
"""事件里错误消息的最大长度——超长截断，避免事件体积失控。"""

UNKNOWN_ITEM_ID = "unknown"
"""缺少追踪键时的占位 itemId。"""

DEFAULT_WRITE_BATCH_SIZE = 100
"""默认攒批大小，与 Java `VectorProperties.Bulk.writeBatchSize` 一致。"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


class BulkProcessingStage(StrEnum):
    """单条记录在批量操作中的可观测处理阶段。

    阶段只描述"在哪一步"，不描述"为什么"——失败原因由 `BulkItemFailed.error_code`
    单独承载，运维侧既能按阶段聚合失败率，也能按异常类聚合根因。
    """

    EMBEDDING = "EMBEDDING"
    PERSISTING = "PERSISTING"
    DELETING = "DELETING"


class BulkOperationType(StrEnum):
    """批量操作的类型。"""

    UPSERT = "UPSERT"
    DELETE = "DELETE"


@dataclass(frozen=True, slots=True)
class BulkOperationSummary:
    """批量操作结束时的不可变统计快照。

    计数器描述的是"API 调用次数"而非"记录数"：一次嵌入调用处理一条记录，
    但一次落库调用可能包含 `write_batch_size` 条记录——便于与 provider
    计费/SLA 直接对齐。
    """

    succeeded: int = 0
    failed: int = 0
    elapsed: timedelta = timedelta(0)
    embedding_requests: int = 0
    write_requests: int = 0

    @property
    def processed(self) -> int:
        """已处理记录数 = 成功数 + 失败数。"""
        return self.succeeded + self.failed


class BulkOperationEvent:
    """批量操作领域事件的基类。

    基类只做类型标记：各事件子类自带完整字段（`operation_id` 关联整批，
    `occurred_at` 记录发生时刻）。不让基类持有 dataclass 字段——dataclass
    继承会把基类字段排到子类字段之前，构造参数顺序就与阅读顺序不一致，
    这类"字段顺序陷阱"在事件协议里尤其危险。
    """

    __slots__ = ()


@dataclass(frozen=True, slots=True)
class BulkStarted(BulkOperationEvent):
    """整批开始。消费者以此为进度 UI 的起点。"""

    operation_id: str
    operation_type: BulkOperationType
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class BulkItemStarted(BulkOperationEvent):
    """单条记录进入某个处理阶段。

    同一 item 在 EMBEDDING 与 PERSISTING 各产生一条；消费者按
    `(operation_id, item_id, stage)` 三元组去重，避免重复计数。
    """

    operation_id: str
    item_id: str
    stage: BulkProcessingStage
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class BulkItemSucceeded(BulkOperationEvent):
    """单条记录成功落库。`vector_id` 是 provider 侧的向量记录 ID。"""

    operation_id: str
    item_id: str
    vector_id: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class BulkItemFailed(BulkOperationEvent):
    """单条记录在某个阶段失败。

    `error_code` 是异常类名（稳定、不含包路径），`message` 被截断，
    因此事件可以安全地跨进程转发。
    """

    operation_id: str
    item_id: str
    stage: BulkProcessingStage
    error_code: str
    message: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class BulkCompleted(BulkOperationEvent):
    """整批结束——无论中途是否失败，总会发出这一条。

    它是批次级清理（对账、释放资源、关闭进度 UI）的稳定锚点。
    """

    operation_id: str
    operation_type: BulkOperationType
    summary: BulkOperationSummary
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class BulkOptions:
    """批量入库的调度参数。"""

    write_batch_size: int = DEFAULT_WRITE_BATCH_SIZE
    fail_fast: bool = False

    def __post_init__(self) -> None:
        if self.write_batch_size <= 0:
            raise ValueError("write_batch_size must be positive")


@dataclass(frozen=True, slots=True)
class EmbeddedVectorRecord:
    """嵌入阶段与持久化阶段之间的不可变载体。

    `embedding` 是不可变元组，不存在 Java 侧为跨线程共享而做的数组克隆问题。
    """

    item_id: str
    record: VectorRecord
    embedding: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.item_id or not self.item_id.strip():
            raise ValueError("item_id must not be blank")
        if self.record is None:
            raise ValueError("record must not be None")
        if not self.embedding:
            raise ValueError("embedding must not be empty")


@runtime_checkable
class RecordEmbedder(Protocol):
    """按记录内容模态完成嵌入的回调。"""

    def embed(self, record: VectorRecord) -> tuple[float, ...]: ...


@runtime_checkable
class EmbeddedRecordWriter(Protocol):
    """把一个已嵌入批次写入目标索引。

    实现不应自行拆批或并发——拆批策略由流水线统一控制，保证事件协议一致。
    """

    def write(
        self, index_name: str, records: Sequence[EmbeddedVectorRecord]
    ) -> None: ...


@runtime_checkable
class StoreManagedRecordWriter(Protocol):
    """库管嵌入写入回调：嵌入由向量库在写入时完成。"""

    def write(self, index_name: str, records: Sequence[VectorRecord]) -> None: ...


class ModalityAwareRecordEmbedder:
    """把 `ModalityAwareEmbeddingService` 适配成按记录嵌入的 `RecordEmbedder`。

    记录的内容自带模态（文本/图片），因此这里只需要把模态与内容转交给服务，
    由服务按模态路由到对应模型——图片未配置模型时服务会显式失败，不会静默退回文本。
    """

    def __init__(self, service: ModalityAwareEmbeddingService) -> None:
        if service is None:
            raise ValueError("service must not be None")
        self._service = service

    def embed(self, record: VectorRecord) -> tuple[float, ...]:
        if record is None or record.content is None:
            raise ValueError("record and its content are required")
        return self._service.embed(record.content.modality, record.content)


class _Counters:
    __slots__ = ("succeeded", "failed", "embedding_requests", "write_requests")

    def __init__(self) -> None:
        self.succeeded = 0
        self.failed = 0
        self.embedding_requests = 0
        self.write_requests = 0

    def summary(self, started_at: datetime) -> BulkOperationSummary:
        return BulkOperationSummary(
            succeeded=self.succeeded,
            failed=self.failed,
            elapsed=_now() - started_at,
            embedding_requests=self.embedding_requests,
            write_requests=self.write_requests,
        )


class BulkIngestionPipeline:
    """向量批量入库编排器。

    两种构造形态：
    - 自管嵌入：`BulkIngestionPipeline(embedder, writer)`，事件流含 EMBEDDING 阶段；
    - 库管嵌入：`BulkIngestionPipeline(store_managed_writer=...)`，事件流只含
      PERSISTING 阶段，用于显式区分"我们嵌"和"库嵌"两条管线。
    """

    def __init__(
        self,
        embedder: RecordEmbedder | None = None,
        writer: EmbeddedRecordWriter | None = None,
        *,
        store_managed_writer: StoreManagedRecordWriter | None = None,
    ) -> None:
        if store_managed_writer is not None and (embedder is not None or writer is not None):
            raise ValueError(
                "store_managed_writer cannot be combined with embedder/writer"
            )
        if store_managed_writer is None and (embedder is None or writer is None):
            raise ValueError(
                "either embedder+writer or store_managed_writer is required"
            )
        self._embedder = embedder
        self._writer = writer
        self._store_managed_writer = store_managed_writer

    @property
    def store_managed(self) -> bool:
        """是否为库管嵌入管线。"""
        return self._store_managed_writer is not None

    def execute(
        self,
        index_name: str,
        records: Iterable[VectorRecord],
        options: BulkOptions | None = None,
    ) -> Iterator[BulkOperationEvent]:
        """启动一次批量入库事件流。

        返回的是惰性迭代器：调用本身不产生副作用，迭代才真正开始；每次调用
        `execute` 都是一次独立执行（对位 Java 的冷流语义）。
        """
        if not isinstance(index_name, str) or not index_name.strip():
            raise ValueError("index_name must not be blank")
        if records is None:
            raise ValueError("records must not be None")
        effective = options or BulkOptions()
        operation_id = str(uuid.uuid4())
        started_at = _now()
        counters = _Counters()
        yield BulkStarted(operation_id, BulkOperationType.UPSERT, started_at)
        try:
            if self.store_managed:
                yield from self._execute_store_managed(
                    operation_id, index_name, records, effective, counters
                )
            else:
                yield from self._execute_embedded(
                    operation_id, index_name, records, effective, counters
                )
        except Exception as error:  # noqa: BLE001 — 异常降级为事件，不中断整批
            yield _failed(
                operation_id, UNKNOWN_ITEM_ID, BulkProcessingStage.EMBEDDING, error, counters
            )
        yield BulkCompleted(
            operation_id, BulkOperationType.UPSERT, counters.summary(started_at), _now()
        )

    def _execute_embedded(
        self,
        operation_id: str,
        index_name: str,
        records: Iterable[VectorRecord],
        options: BulkOptions,
        counters: _Counters,
    ) -> Iterator[BulkOperationEvent]:
        assert self._embedder is not None and self._writer is not None
        batch: list[EmbeddedVectorRecord] = []
        try:
            for record in records:
                try:
                    item_id, prepared = _prepare(record, index_name)
                except Exception as error:  # noqa: BLE001 — 单条失败不影响整批
                    yield _failed(
                        operation_id,
                        UNKNOWN_ITEM_ID,
                        BulkProcessingStage.EMBEDDING,
                        error,
                        counters,
                    )
                    if options.fail_fast:
                        return
                    continue
                yield BulkItemStarted(
                    operation_id, item_id, BulkProcessingStage.EMBEDDING, _now()
                )
                try:
                    counters.embedding_requests += 1
                    embedding = tuple(self._embedder.embed(prepared))
                except Exception as error:  # noqa: BLE001 — 单条失败不影响整批
                    yield _failed(
                        operation_id,
                        item_id,
                        BulkProcessingStage.EMBEDDING,
                        error,
                        counters,
                    )
                    if options.fail_fast:
                        return
                    continue
                batch.append(EmbeddedVectorRecord(item_id, prepared, embedding))
                if len(batch) >= options.write_batch_size:
                    yield from self._persist(
                        operation_id, index_name, batch, options, counters
                    )
                    batch = []
        except Exception:
            # 记录源中途失败：已嵌入的批次不能被静默丢弃——先落库再把异常上抛，
            # 由 execute() 统一降级为失败事件。
            if batch:
                yield from self._persist(
                    operation_id, index_name, batch, options, counters
                )
            raise
        if batch:
            yield from self._persist(operation_id, index_name, batch, options, counters)

    def _execute_store_managed(
        self,
        operation_id: str,
        index_name: str,
        records: Iterable[VectorRecord],
        options: BulkOptions,
        counters: _Counters,
    ) -> Iterator[BulkOperationEvent]:
        assert self._store_managed_writer is not None
        batch: list[tuple[str, VectorRecord]] = []
        try:
            for record in records:
                try:
                    item_id, prepared = _prepare(record, index_name)
                except Exception as error:  # noqa: BLE001 — 单条失败不影响整批
                    yield _failed(
                        operation_id,
                        UNKNOWN_ITEM_ID,
                        BulkProcessingStage.PERSISTING,
                        error,
                        counters,
                    )
                    if options.fail_fast:
                        return
                    continue
                batch.append((item_id, prepared))
                if len(batch) >= options.write_batch_size:
                    yield from self._persist_store_managed(
                        operation_id, index_name, batch, options, counters
                    )
                    batch = []
        except Exception:
            if batch:
                yield from self._persist_store_managed(
                    operation_id, index_name, batch, options, counters
                )
            raise
        if batch:
            yield from self._persist_store_managed(
                operation_id, index_name, batch, options, counters
            )

    def _persist(
        self,
        operation_id: str,
        index_name: str,
        batch: list[EmbeddedVectorRecord],
        options: BulkOptions,
        counters: _Counters,
    ) -> Iterator[BulkOperationEvent]:
        assert self._writer is not None
        for item in batch:
            yield BulkItemStarted(
                operation_id, item.item_id, BulkProcessingStage.PERSISTING, _now()
            )
        try:
            counters.write_requests += 1
            self._writer.write(index_name, tuple(batch))
        except Exception as error:  # noqa: BLE001 — 整批失败按每条一条失败事件回放
            for item in batch:
                yield _failed(
                    operation_id,
                    item.item_id,
                    BulkProcessingStage.PERSISTING,
                    error,
                    counters,
                )
                if options.fail_fast:
                    return
            return
        for item in batch:
            counters.succeeded += 1
            yield BulkItemSucceeded(
                operation_id, item.item_id, item.record.id, _now()
            )

    def _persist_store_managed(
        self,
        operation_id: str,
        index_name: str,
        batch: list[tuple[str, VectorRecord]],
        options: BulkOptions,
        counters: _Counters,
    ) -> Iterator[BulkOperationEvent]:
        assert self._store_managed_writer is not None
        for item_id, _ in batch:
            yield BulkItemStarted(
                operation_id, item_id, BulkProcessingStage.PERSISTING, _now()
            )
        try:
            counters.write_requests += 1
            self._store_managed_writer.write(
                index_name, tuple(record for _, record in batch)
            )
        except Exception as error:  # noqa: BLE001 — 整批失败按每条一条失败事件回放
            for item_id, _ in batch:
                yield _failed(
                    operation_id,
                    item_id,
                    BulkProcessingStage.PERSISTING,
                    error,
                    counters,
                )
                if options.fail_fast:
                    return
            return
        for item_id, record in batch:
            counters.succeeded += 1
            yield BulkItemSucceeded(operation_id, item_id, record.id, _now())


def _prepare(record: VectorRecord, index_name: str) -> tuple[str, VectorRecord]:
    """校验并规整待写入记录，返回 (itemId, 规整后的记录)。"""
    if record is None or record.content is None:
        raise ValueError("record and its content are required")
    if not record.index_name or record.index_name != index_name:
        raise ValueError("record index_name must match the batch index_name")
    prepared = record
    if not record.id or not record.id.strip():
        prepared = replace(record, id=str(uuid.uuid4()))
    return _item_id(prepared), prepared


def _item_id(record: VectorRecord) -> str:
    """取记录的追踪键；缺失时记为 `unknown`。"""
    metadata = record.metadata if isinstance(record.metadata, dict) else {}
    value = metadata.get(VectorRecord.META_ITEM_ID)
    if isinstance(value, str) and value.strip():
        return value
    return UNKNOWN_ITEM_ID


def _failed(
    operation_id: str,
    item_id: str,
    stage: BulkProcessingStage,
    error: Exception,
    counters: _Counters,
) -> BulkItemFailed:
    counters.failed += 1
    return BulkItemFailed(
        operation_id,
        item_id,
        stage,
        type(error).__name__,
        _safe_message(error),
        _now(),
    )


def _safe_message(error: Exception) -> str:
    message = str(error)
    if not message.strip():
        return type(error).__name__
    if len(message) <= MAX_ERROR_MESSAGE_LENGTH:
        return message
    return message[:MAX_ERROR_MESSAGE_LENGTH]


__all__ = [
    "BulkProcessingStage",
    "BulkOperationType",
    "BulkOperationEvent",
    "BulkStarted",
    "BulkItemStarted",
    "BulkItemSucceeded",
    "BulkItemFailed",
    "BulkCompleted",
    "BulkOperationSummary",
    "BulkOptions",
    "EmbeddedVectorRecord",
    "RecordEmbedder",
    "EmbeddedRecordWriter",
    "StoreManagedRecordWriter",
    "ModalityAwareRecordEmbedder",
    "BulkIngestionPipeline",
    "MAX_ERROR_MESSAGE_LENGTH",
    "DEFAULT_WRITE_BATCH_SIZE",
    "UNKNOWN_ITEM_ID",
]
