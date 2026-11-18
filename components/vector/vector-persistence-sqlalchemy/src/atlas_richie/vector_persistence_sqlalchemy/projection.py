"""关系库上的向量投影状态机、manifest 账本与清理 outbox。

对应 Java `cn.richie696.component.vector.projection.impl.DefaultVectorProjectionService`
与其 4 张表（`rag_vector_projection` / `_version` / `_record` / `_outbox`）。

本模块是 `atlas-richie-vector-core` 投影契约的 SQLAlchemy 实现：
- `begin_rebuild` / `activate` / `mark_failed` 推进状态机；
- `active_version_ids` 实现 `ActiveProjectionVersionResolver`，
  检索门面据此把 `projectionVersionId IN (...)` 下推到 provider；
- `record_succeeded` 维护 version → vectorId 的 manifest 账本，
  清理阶段只凭 manifest 精确删除，因此对不支持 metadata 过滤的 provider 同样成立；
- `cleanup_due_projections` 按批次删除向量并把版本推进到 CLEANED。

与 Java 的两处刻意差异（均已核对 Java 源码，不是疏漏）：
1. `written_records` 只在 manifest 首次落库时累加。Java 的 `recordSucceeded`
   无条件执行 `written_records = written_records + 1`，重复 vectorId 会让计数
   超过 manifest 行数；而 Java 实体自己的注释写明该计数"与 manifest 行数保持
   一致"。这里按实体注释的语义对齐，保证计数与账本一致。
2. 本模块不内置调度线程。Java 同样把 `cleanupDueProjections` 交给外部调度器
   （Quartz / XXL-Job）周期触发，插件只提供"可被调度的入口"。

依赖隔离：本包只依赖 `atlas-richie-vector-core` 与 SQLAlchemy——不引入
`atlas-richie-persistence-sqlalchemy`。后者是另一个组件的适配器，按依赖策略
"一个适配器只依赖一个组件 + 它所适配的外部技术"，适配器之间不横向依赖。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    delete,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Connection, Engine

from atlas_richie.vector_core.projection import (
    VectorProjectionReference,
    VectorProjectionSpecification,
    VectorProjectionState,
    VectorProjectionVersion,
    VectorRecordDeleteOperations,
    normalize_failure_reason,
)

from .properties import VectorProjectionProperties

_log = logging.getLogger(__name__)

CLEANUP_EVENT = "VECTOR_PROJECTION_CLEANUP"
"""outbox 事件类型：清理某个 RETIRING 版本对应的向量库向量。"""

OUTBOX_PENDING = "PENDING"
OUTBOX_PROCESSED = "PROCESSED"

DEFAULT_TABLE_PREFIX = "rag_vector_projection"


class VectorProjectionError(RuntimeError):
    """投影持久化层的通用错误。"""


class ProjectionVersionNotFoundError(VectorProjectionError, LookupError):
    """指定的 projection version 不存在。"""


class ProjectionStateError(VectorProjectionError):
    """当前状态不允许该状态机转移。"""


@dataclass(frozen=True, slots=True)
class VectorProjectionCleanupEvent:
    """清理 outbox 事件快照。"""

    id: str
    event_type: str
    version_id: str
    state: str
    attempts: int
    last_error: str | None
    execute_after: datetime | None
    processed_at: datetime | None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    """把数据库读出的时间统一成 UTC。

    SQLite 不保存时区，读回来是 naive；这里补上 UTC，避免跨后端比较时出现
    "naive 与 aware 不可比"的运行期错误。
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class VectorProjectionStore:
    """向量投影的持久化实现，同时是 `ActiveProjectionVersionResolver` 的提供者。

    使用同步 SQLAlchemy `Engine`：投影状态机是低频写、检索热路径只读一列指针，
    同步 API 与 Java 的 MyBatis 语义一致，也便于嵌入已有的同步事务边界。
    """

    def __init__(
        self,
        engine: Engine | str,
        *,
        create_table: bool = True,
        properties: VectorProjectionProperties | None = None,
        table_prefix: str = DEFAULT_TABLE_PREFIX,
        deleter: VectorRecordDeleteOperations | None = None,
    ) -> None:
        self._engine = create_engine(engine) if isinstance(engine, str) else engine
        self._properties = properties or VectorProjectionProperties()
        self._deleter: VectorRecordDeleteOperations | None = deleter
        metadata = MetaData()
        self._projection = Table(
            table_prefix,
            metadata,
            Column("id", String(64), primary_key=True),
            Column("tenant_id", BigInteger, nullable=False),
            Column("knowledge_base_id", String(128), nullable=False),
            Column("document_ref", String(256), nullable=False),
            Column("active_version_id", String(64)),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
        )
        self._version = Table(
            f"{table_prefix}_version",
            metadata,
            Column("id", String(64), primary_key=True),
            Column("projection_id", String(64), nullable=False),
            Column("source_version", String(128), nullable=False),
            Column("index_name", String(256), nullable=False),
            Column("embedding_space_id", String(256), nullable=False),
            Column("state", String(32), nullable=False),
            Column("written_records", Integer, nullable=False, default=0),
            Column("failed_records", Integer, nullable=False, default=0),
            Column("failure_reason", String(1000)),
            Column("cleanup_after", DateTime(timezone=True)),
            Column("activated_at", DateTime(timezone=True)),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
        )
        self._record = Table(
            f"{table_prefix}_record",
            metadata,
            Column("id", String(64), primary_key=True),
            Column("version_id", String(64), nullable=False),
            Column("vector_id", String(256), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
        )
        self._outbox = Table(
            f"{table_prefix}_outbox",
            metadata,
            Column("id", String(64), primary_key=True),
            Column("event_type", String(64), nullable=False),
            Column("version_id", String(64), nullable=False),
            Column("state", String(32), nullable=False),
            Column("attempts", Integer, nullable=False, default=0),
            Column("last_error", String(1000)),
            Column("execute_after", DateTime(timezone=True), nullable=False),
            Column("processed_at", DateTime(timezone=True)),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
        )
        if create_table:
            metadata.create_all(self._engine)

    @property
    def engine(self) -> Engine:
        return self._engine

    @property
    def properties(self) -> VectorProjectionProperties:
        return self._properties

    @property
    def projection_table(self) -> Table:
        return self._projection

    @property
    def version_table(self) -> Table:
        return self._version

    @property
    def record_table(self) -> Table:
        return self._record

    @property
    def outbox_table(self) -> Table:
        return self._outbox

    # ------------------------------------------------------------------
    # 生命周期：写入 / 激活 / 失败
    # ------------------------------------------------------------------

    def begin_rebuild(
        self,
        reference: VectorProjectionReference,
        specification: VectorProjectionSpecification,
    ) -> VectorProjectionVersion:
        """开启一次重建：复用或创建 projection 主表行，并新建一条 PREPARING 版本。"""
        if reference is None or specification is None:
            raise ValueError("reference and specification are required")
        now = _now()
        version_id = str(uuid.uuid4())
        with self._engine.begin() as connection:
            row = connection.execute(
                select(self._projection).where(
                    self._projection.c.tenant_id == reference.tenant_id,
                    self._projection.c.knowledge_base_id
                    == reference.knowledge_base_id,
                    self._projection.c.document_ref == reference.document_ref,
                )
            ).mappings().first()
            if row is None:
                projection_id = str(uuid.uuid4())
                connection.execute(
                    insert(self._projection).values(
                        id=projection_id,
                        tenant_id=reference.tenant_id,
                        knowledge_base_id=reference.knowledge_base_id,
                        document_ref=reference.document_ref,
                        active_version_id=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                projection_id = row["id"]
            connection.execute(
                insert(self._version).values(
                    id=version_id,
                    projection_id=projection_id,
                    source_version=specification.source_version,
                    index_name=specification.index_name,
                    embedding_space_id=specification.embedding_space_id,
                    state=VectorProjectionState.PREPARING.value,
                    written_records=0,
                    failed_records=0,
                    failure_reason=None,
                    cleanup_after=None,
                    activated_at=None,
                    created_at=now,
                    updated_at=now,
                )
            )
        return VectorProjectionVersion(
            projection_id=projection_id,
            version_id=version_id,
            reference=reference,
            specification=specification,
            state=VectorProjectionState.PREPARING,
            written_records=0,
            failed_records=0,
        )

    def activate(
        self, version_id: str, cleanup_delay: timedelta | None = None
    ) -> None:
        """把 READY 版本切为 ACTIVE，同 projection 的旧 ACTIVE 版本退场为 RETIRING。

        退场版本会在同一事务里入队一条清理事件——状态切换与清理意图必须一起提交，
        否则会出现"版本已 RETIRING 但没有清理任务"的悬挂状态。
        """
        delay = (
            cleanup_delay if cleanup_delay is not None else self._properties.cleanup_delay
        )
        now = _now()
        cleanup_after = now + delay
        with self._engine.begin() as connection:
            candidate = self._require_version(connection, version_id)
            state = VectorProjectionState.from_id(candidate["state"])
            if state is not VectorProjectionState.READY:
                raise ProjectionStateError(
                    f"only READY projection versions can be activated: {version_id}"
                )
            projection_id = candidate["projection_id"]
            previous = connection.execute(
                select(self._version).where(
                    self._version.c.projection_id == projection_id,
                    self._version.c.state == VectorProjectionState.ACTIVE.value,
                )
            ).mappings().all()
            for old in previous:
                connection.execute(
                    update(self._version)
                    .where(self._version.c.id == old["id"])
                    .values(
                        state=VectorProjectionState.RETIRING.value,
                        cleanup_after=cleanup_after,
                        updated_at=now,
                    )
                )
                self._enqueue_cleanup(connection, old["id"], cleanup_after, now)
            connection.execute(
                update(self._version)
                .where(self._version.c.id == version_id)
                .values(
                    state=VectorProjectionState.ACTIVE.value,
                    activated_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                update(self._projection)
                .where(self._projection.c.id == projection_id)
                .values(active_version_id=version_id, updated_at=now)
            )

    def mark_failed(self, version_id: str, reason: str | None = None) -> None:
        """把版本标记为 FAILED。ACTIVE / CLEANED 不允许回退。"""
        now = _now()
        with self._engine.begin() as connection:
            version = self._require_version(connection, version_id)
            state = VectorProjectionState.from_id(version["state"])
            if state in (VectorProjectionState.ACTIVE, VectorProjectionState.CLEANED):
                raise ProjectionStateError(
                    f"cannot fail projection version in state {state.value}"
                )
            connection.execute(
                update(self._version)
                .where(self._version.c.id == version_id)
                .values(
                    state=VectorProjectionState.FAILED.value,
                    failure_reason=normalize_failure_reason(reason),
                    updated_at=now,
                )
            )

    def mark_writing(self, version_id: str) -> None:
        """CAS：PREPARING → WRITING。重复调用是幂等的 no-op。"""
        now = _now()
        with self._engine.begin() as connection:
            updated = connection.execute(
                update(self._version)
                .where(
                    self._version.c.id == version_id,
                    self._version.c.state == VectorProjectionState.PREPARING.value,
                )
                .values(state=VectorProjectionState.WRITING.value, updated_at=now)
            ).rowcount
            if updated != 1:
                raise ProjectionStateError(
                    f"invalid projection version state transition for {version_id}"
                )

    def mark_ready_if_no_failure(self, version_id: str) -> None:
        """写入流收尾：存在失败记录则置 FAILED，否则置 READY。"""
        now = _now()
        with self._engine.begin() as connection:
            version = self._require_version(connection, version_id)
            state = VectorProjectionState.from_id(version["state"])
            if state is not VectorProjectionState.WRITING:
                return
            if (version["failed_records"] or 0) > 0:
                connection.execute(
                    update(self._version)
                    .where(self._version.c.id == version_id)
                    .values(
                        state=VectorProjectionState.FAILED.value,
                        failure_reason=normalize_failure_reason(version["failure_reason"]),
                        updated_at=now,
                    )
                )
                return
            connection.execute(
                update(self._version)
                .where(self._version.c.id == version_id)
                .values(state=VectorProjectionState.READY.value, updated_at=now)
            )

    def find_version(self, version_id: str) -> VectorProjectionVersion | None:
        """读取单个版本快照；不存在返回 None。"""
        with self._engine.connect() as connection:
            version = connection.execute(
                select(self._version).where(self._version.c.id == version_id)
            ).mappings().first()
            if version is None:
                return None
            projection = connection.execute(
                select(self._projection).where(
                    self._projection.c.id == version["projection_id"]
                )
            ).mappings().first()
            if projection is None:
                raise VectorProjectionError(
                    f"projection does not exist: {version['projection_id']}"
                )
        return self._snapshot(projection, version)

    # ------------------------------------------------------------------
    # 检索侧：ActiveProjectionVersionResolver
    # ------------------------------------------------------------------

    def active_version_ids(
        self, tenant_id: int, knowledge_base_id: str
    ) -> frozenset[str]:
        """解析某租户 + 知识库下当前对外可见的 projection version id 集合。

        读路径：只查 projection 主表的 `active_version_id` 指针列——它由激活事务
        原子切换，因此检索侧永远看到"已提交"的版本，不会读到中间态。
        """
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(self._projection.c.active_version_id).where(
                    self._projection.c.tenant_id == tenant_id,
                    self._projection.c.knowledge_base_id == knowledge_base_id,
                    self._projection.c.active_version_id.is_not(None),
                )
            ).all()
        return frozenset(row[0] for row in rows if row[0] is not None)

    # ------------------------------------------------------------------
    # 写入侧：manifest 账本
    # ------------------------------------------------------------------

    def record_succeeded(self, version_id: str, vector_id: str) -> None:
        """记录一条写入成功的 vectorId manifest。

        manifest 幂等：同一 (versionId, vectorId) 只落库一行。
        """
        if not vector_id or not vector_id.strip():
            raise ValueError("vector_id must not be blank")
        now = _now()
        with self._engine.begin() as connection:
            self._require_version(connection, version_id)
            existing = connection.execute(
                select(self._record.c.id).where(
                    self._record.c.version_id == version_id,
                    self._record.c.vector_id == vector_id,
                )
            ).first()
            if existing is None:
                connection.execute(
                    insert(self._record).values(
                        id=str(uuid.uuid4()),
                        version_id=version_id,
                        vector_id=vector_id,
                        created_at=now,
                    )
                )
                connection.execute(
                    update(self._version)
                    .where(self._version.c.id == version_id)
                    .values(
                        written_records=self._version.c.written_records + 1,
                        updated_at=now,
                    )
                )

    def record_failure(self, version_id: str, reason: str | None = None) -> None:
        """记录一条写入失败，累加失败计数并刷新失败原因。"""
        now = _now()
        with self._engine.begin() as connection:
            self._require_version(connection, version_id)
            connection.execute(
                update(self._version)
                .where(self._version.c.id == version_id)
                .values(
                    failed_records=self._version.c.failed_records + 1,
                    failure_reason=normalize_failure_reason(reason),
                    updated_at=now,
                )
            )

    def manifest_vector_ids(self, version_id: str) -> tuple[str, ...]:
        """读取某版本的 manifest vectorId 列表（按写入顺序）。"""
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(self._record.c.vector_id)
                .where(self._record.c.version_id == version_id)
                .order_by(self._record.c.created_at, self._record.c.id)
            ).all()
        return tuple(row[0] for row in rows)

    # ------------------------------------------------------------------
    # 清理侧：延迟清理与 outbox
    # ------------------------------------------------------------------

    def due_cleanup_versions(self, max_versions: int) -> tuple[VectorProjectionVersion, ...]:
        """列出到期待清理的 RETIRING 版本。"""
        if max_versions <= 0:
            return ()
        now = _now()
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(self._version)
                .where(
                    self._version.c.state == VectorProjectionState.RETIRING.value,
                    self._version.c.cleanup_after.is_not(None),
                    self._version.c.cleanup_after <= now,
                )
                .order_by(self._version.c.id)
                .limit(max_versions)
            ).mappings().all()
            versions = []
            for row in rows:
                projection = connection.execute(
                    select(self._projection).where(
                        self._projection.c.id == row["projection_id"]
                    )
                ).mappings().first()
                if projection is None:
                    raise VectorProjectionError(
                        f"projection does not exist: {row['projection_id']}"
                    )
                versions.append(self._snapshot(projection, row))
        return tuple(versions)

    def pending_cleanup_events(
        self, limit: int = 100
    ) -> tuple[VectorProjectionCleanupEvent, ...]:
        """列出尚未处理的清理事件（PENDING），不区分是否已到期。"""
        return self._cleanup_events(limit, due_only=False)

    def due_cleanup_events(
        self, limit: int = 100
    ) -> tuple[VectorProjectionCleanupEvent, ...]:
        """列出已到期待处理的清理事件（PENDING 且 execute_after 已到）。"""
        return self._cleanup_events(limit, due_only=True)

    def _cleanup_events(
        self, limit: int, *, due_only: bool
    ) -> tuple[VectorProjectionCleanupEvent, ...]:
        if limit <= 0:
            return ()
        conditions = [
            self._outbox.c.event_type == CLEANUP_EVENT,
            self._outbox.c.state == OUTBOX_PENDING,
        ]
        if due_only:
            conditions.append(self._outbox.c.execute_after <= _now())
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(self._outbox)
                .where(*conditions)
                .order_by(self._outbox.c.id)
                .limit(limit)
            ).mappings().all()
        return tuple(self._to_event(row) for row in rows)

    def cleanup_due_projections(self, max_versions: int) -> int:
        """清理到期版本，返回成功清理（已推进到 CLEANED）的版本数。

        单个版本失败不影响其它版本：失败会被记进 outbox 的 attempts / last_error，
        下次调度自动重试。
        """
        if max_versions <= 0:
            return 0
        if self._deleter is None:
            raise VectorProjectionError(
                "cleanup requires a vector record deleter; "
                "construct the store with deleter=... to enable cleanup"
            )
        cleaned = 0
        for version in self.due_cleanup_versions(max_versions):
            if self._cleanup_version(version):
                cleaned += 1
        return cleaned

    def _cleanup_version(self, version: VectorProjectionVersion) -> bool:
        """按 manifest 批量删除向量，删空后把版本推进到 CLEANED。"""
        version_id = version.version_id
        index_name = version.specification.index_name
        try:
            while True:
                with self._engine.connect() as connection:
                    batch = connection.execute(
                        select(self._record)
                        .where(self._record.c.version_id == version_id)
                        .limit(self._properties.delete_batch_size)
                    ).mappings().all()
                if not batch:
                    self._finish_cleanup(version_id)
                    return True
                self._deleter.delete_by_ids(
                    index_name, [row["vector_id"] for row in batch]
                )
                with self._engine.begin() as connection:
                    connection.execute(
                        delete(self._record).where(
                            self._record.c.id.in_([row["id"] for row in batch])
                        )
                    )
        except Exception as error:  # noqa: BLE001 — 单版本失败不影响其它版本
            self._record_cleanup_failure(version_id, str(error))
            _log.warning(
                "vector projection cleanup failed, version=%s", version_id
            )
            return False

    def _finish_cleanup(self, version_id: str) -> None:
        """状态切到 CLEANED 并把对应清理事件标记 PROCESSED——两者必须同步成功。"""
        now = _now()
        with self._engine.begin() as connection:
            connection.execute(
                update(self._version)
                .where(self._version.c.id == version_id)
                .values(state=VectorProjectionState.CLEANED.value, updated_at=now)
            )
            connection.execute(
                update(self._outbox)
                .where(
                    self._outbox.c.version_id == version_id,
                    self._outbox.c.event_type == CLEANUP_EVENT,
                )
                .values(
                    state=OUTBOX_PROCESSED,
                    processed_at=now,
                    last_error=None,
                    updated_at=now,
                )
            )

    def _record_cleanup_failure(self, version_id: str, error: str) -> None:
        """清理失败计数入库，供下次调度重试与人工排查。"""
        now = _now()
        with self._engine.begin() as connection:
            connection.execute(
                update(self._outbox)
                .where(
                    self._outbox.c.version_id == version_id,
                    self._outbox.c.event_type == CLEANUP_EVENT,
                    self._outbox.c.state == OUTBOX_PENDING,
                )
                .values(
                    attempts=self._outbox.c.attempts + 1,
                    last_error=normalize_failure_reason(error),
                    updated_at=now,
                )
            )

    def _enqueue_cleanup(
        self, connection: Connection, version_id: str, execute_after: datetime, now: datetime
    ) -> None:
        """在调用方事务里入队一条清理事件。"""
        connection.execute(
            insert(self._outbox).values(
                id=str(uuid.uuid4()),
                event_type=CLEANUP_EVENT,
                version_id=version_id,
                state=OUTBOX_PENDING,
                attempts=0,
                last_error=None,
                execute_after=execute_after,
                processed_at=None,
                created_at=now,
                updated_at=now,
            )
        )

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _require_version(self, connection: Connection, version_id: str):
        row = connection.execute(
            select(self._version).where(self._version.c.id == version_id)
        ).mappings().first()
        if row is None:
            raise ProjectionVersionNotFoundError(
                f"projection version does not exist: {version_id}"
            )
        return row

    def _snapshot(self, projection, version) -> VectorProjectionVersion:
        return VectorProjectionVersion(
            projection_id=projection["id"],
            version_id=version["id"],
            reference=VectorProjectionReference(
                tenant_id=projection["tenant_id"],
                knowledge_base_id=projection["knowledge_base_id"],
                document_ref=projection["document_ref"],
            ),
            specification=VectorProjectionSpecification(
                source_version=version["source_version"],
                index_name=version["index_name"],
                embedding_space_id=version["embedding_space_id"],
            ),
            state=VectorProjectionState.from_id(version["state"]),
            written_records=version["written_records"] or 0,
            failed_records=version["failed_records"] or 0,
            cleanup_after=_as_utc(version["cleanup_after"]),
            failure_reason=version["failure_reason"],
        )

    def _to_event(self, row) -> VectorProjectionCleanupEvent:
        return VectorProjectionCleanupEvent(
            id=row["id"],
            event_type=row["event_type"],
            version_id=row["version_id"],
            state=row["state"],
            attempts=row["attempts"] or 0,
            last_error=row["last_error"],
            execute_after=_as_utc(row["execute_after"]),
            processed_at=_as_utc(row["processed_at"]),
        )

    def close(self) -> None:
        self._engine.dispose()


__all__ = [
    "VectorProjectionStore",
    "VectorProjectionCleanupEvent",
    "VectorProjectionError",
    "ProjectionVersionNotFoundError",
    "ProjectionStateError",
    "CLEANUP_EVENT",
    "OUTBOX_PENDING",
    "OUTBOX_PROCESSED",
    "DEFAULT_TABLE_PREFIX",
]
