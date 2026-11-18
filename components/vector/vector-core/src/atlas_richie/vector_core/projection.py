"""向量投影版本模型与生命周期契约（零第三方依赖）。

对应 Java `cn.richie696.component.vector.projection` 的公开契约部分：
`VectorProjectionState` / `VectorProjectionReference` / `VectorProjectionSpecification` /
`VectorProjectionVersion`，以及 `knowledge.ActiveProjectionVersionResolver` 与
`VectorProjectionLifecycleService` / `VectorProjectionCleanupService` 两个接口。

为什么需要这层：商用 RAG 要求"向量库可重建投影"——同一份文档在同一向量库内
按版本严格隔离，激活后才可被检索，旧版本到点后按 manifest 精确回收。检索侧
不认识版本，只认识"当前活跃版本集合"，因此需要一个可选 SPI 把
(tenantId, knowledgeBaseId) 解析成可见的 version id 集合。

关键不变量（与 Java 保持一致）：
1. 同一 `VectorProjectionReference` 同一时刻至多一个 ACTIVE 版本；
2. FAILED / CLEANED 是终态，不允许再被激活或回退到前置状态；
3. 状态机只前进不倒退，转移由持久化层在事务内用 CAS 校验；
4. resolver 返回空集合 = "无可用版本"，调用方必须短路返回空结果，
   而不是绕过过滤——否则"解析失败"与"无版本"会被混为同一行为。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Mapping, Protocol, Sequence, runtime_checkable

PROJECTION_VERSION_FIELD = "projectionVersionId"
"""向量库中承载投影版本 id 的 metadata 字段名。

检索侧据此下推 `projectionVersionId IN (...)`；Java 侧同名常量分散在
`DefaultKnowledgeBaseVectorService` 与 writer 的 metadata 投影里，此处收口，
避免两处拼写漂移。
"""

MAX_FAILURE_REASON_LENGTH = 1000
"""失败原因落库前的最大长度；超长截断，与 Java `trimReason` 一致。"""

UNKNOWN_FAILURE_REASON = "unknown"
"""失败原因缺省值：空值/纯空白统一记为 `unknown`，而不是留空。"""


class VectorProjectionState(StrEnum):
    """向量投影版本的生命周期状态。"""

    PREPARING = "PREPARING"
    WRITING = "WRITING"
    READY = "READY"
    ACTIVE = "ACTIVE"
    RETIRING = "RETIRING"
    FAILED = "FAILED"
    CLEANED = "CLEANED"

    @property
    def is_terminal(self) -> bool:
        """是否为不可逆终态（FAILED / CLEANED）。"""
        return self in _TERMINAL_STATES

    @property
    def is_visible(self) -> bool:
        """是否为检索可见状态（仅 ACTIVE）。"""
        return self is VectorProjectionState.ACTIVE

    def can_transition_to(self, target: VectorProjectionState) -> bool:
        """判断状态机是否允许从当前状态转移到目标状态。"""
        return target in _ALLOWED_TRANSITIONS.get(self, frozenset())

    @classmethod
    def from_id(cls, value: str) -> VectorProjectionState:
        """从数据库里的字符串状态解析枚举；未知状态显式失败，不静默兜底。"""
        if not isinstance(value, str) or not value.strip():
            raise ValueError("projection state must not be blank")
        try:
            return cls(value.strip())
        except ValueError:
            raise ValueError(f"unknown vector projection state: {value}") from None


_ALLOWED_TRANSITIONS: Mapping[VectorProjectionState, frozenset[VectorProjectionState]] = {
    VectorProjectionState.PREPARING: frozenset(
        {VectorProjectionState.WRITING, VectorProjectionState.FAILED}
    ),
    VectorProjectionState.WRITING: frozenset(
        {VectorProjectionState.READY, VectorProjectionState.FAILED}
    ),
    VectorProjectionState.READY: frozenset(
        {VectorProjectionState.ACTIVE, VectorProjectionState.FAILED}
    ),
    VectorProjectionState.ACTIVE: frozenset({VectorProjectionState.RETIRING}),
    # Java 的 markFailed 只拒绝 ACTIVE / CLEANED，RETIRING 仍可被标记失败，
    # 这里与代码而非状态图保持一致。
    VectorProjectionState.RETIRING: frozenset(
        {VectorProjectionState.CLEANED, VectorProjectionState.FAILED}
    ),
    VectorProjectionState.FAILED: frozenset(),
    VectorProjectionState.CLEANED: frozenset(),
}

_TERMINAL_STATES = frozenset(
    {VectorProjectionState.FAILED, VectorProjectionState.CLEANED}
)


def normalize_failure_reason(reason: str | None) -> str:
    """把失败原因规范化为可持久化字符串。

    空值/纯空白记为 `unknown`，超长截断至 1000 字符——与 Java `trimReason` 同语义。
    """
    if reason is None or not reason.strip():
        return UNKNOWN_FAILURE_REASON
    if len(reason) <= MAX_FAILURE_REASON_LENGTH:
        return reason
    return reason[:MAX_FAILURE_REASON_LENGTH]


@dataclass(frozen=True, slots=True)
class VectorProjectionReference:
    """业务文档在 (租户, 知识库) 范围内的稳定引用三元组。"""

    tenant_id: int
    knowledge_base_id: str
    document_ref: str

    def __post_init__(self) -> None:
        if self.tenant_id is None:
            raise ValueError("tenant_id must not be None")
        if not isinstance(self.knowledge_base_id, str) or not self.knowledge_base_id.strip():
            raise ValueError("knowledge_base_id must not be blank")
        if not isinstance(self.document_ref, str) or not self.document_ref.strip():
            raise ValueError("document_ref must not be blank")


@dataclass(frozen=True, slots=True)
class VectorProjectionSpecification:
    """一次文档向量化重建的不可变规格三元组。

    三元素完全相同的重建才落在同一向量语义空间，可复用既有 manifest；
    任一改变（换 embedding 模型、换索引名、换源版本）都必须新建版本。
    """

    source_version: str
    index_name: str
    embedding_space_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.source_version, str) or not self.source_version.strip():
            raise ValueError("source_version must not be blank")
        if not isinstance(self.index_name, str) or not self.index_name.strip():
            raise ValueError("index_name must not be blank")
        if not isinstance(self.embedding_space_id, str) or not self.embedding_space_id.strip():
            raise ValueError("embedding_space_id must not be blank")


@dataclass(frozen=True, slots=True)
class VectorProjectionVersion:
    """一次投影重建的公开快照，不暴露持久化实体。"""

    projection_id: str
    version_id: str
    reference: VectorProjectionReference
    specification: VectorProjectionSpecification
    state: VectorProjectionState
    written_records: int = 0
    failed_records: int = 0
    cleanup_after: datetime | None = None
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.projection_id or not self.projection_id.strip():
            raise ValueError("projection_id must not be blank")
        if not self.version_id or not self.version_id.strip():
            raise ValueError("version_id must not be blank")
        if self.reference is None:
            raise ValueError("reference must not be None")
        if self.specification is None:
            raise ValueError("specification must not be None")
        if self.state is None:
            raise ValueError("state must not be None")
        if self.written_records < 0 or self.failed_records < 0:
            raise ValueError("record counters must not be negative")

    @property
    def is_active(self) -> bool:
        """该版本是否为当前对外可见版本。"""
        return self.state.is_visible


@runtime_checkable
class ActiveProjectionVersionResolver(Protocol):
    """解析某租户 + 知识库下当前对外可见的 projection version id 集合。

    可选 SPI：检索门面未注入时不做版本过滤，行为退化为单版本语义。

    实现约束：
    - 返回不可变集合，避免调用方在并发请求中看到被中途修改的视图；
    - 处于检索热路径，应在合理时间内完成；
    - 空集合表示"无可用版本"，调用方会短路返回空结果，
      而不是绕过过滤——这让"解析失败"与"无版本"保持可区分。
    """

    def active_version_ids(
        self, tenant_id: int, knowledge_base_id: str
    ) -> frozenset[str]: ...


@runtime_checkable
class VectorProjectionLifecycleService(Protocol):
    """投影版本状态机的写入 / 激活 / 失败转移入口。"""

    def begin_rebuild(
        self,
        reference: VectorProjectionReference,
        specification: VectorProjectionSpecification,
    ) -> VectorProjectionVersion: ...

    def activate(
        self, version_id: str, cleanup_delay: timedelta | None = None
    ) -> None: ...

    def mark_failed(self, version_id: str, reason: str | None = None) -> None: ...

    def find_version(self, version_id: str) -> VectorProjectionVersion | None: ...


@runtime_checkable
class VectorProjectionCleanupService(Protocol):
    """延迟清理任务的调度入口；由外部调度器周期触发。"""

    def cleanup_due_projections(self, max_versions: int) -> int: ...


@runtime_checkable
class VectorRecordDeleteOperations(Protocol):
    """按 vector id 精确删除向量库记录。

    清理阶段只依赖本协议，因此对不支持 metadata 过滤的 provider 同样成立。
    """

    def delete_by_ids(self, index_name: str, ids: Sequence[str]) -> int: ...


__all__ = [
    "PROJECTION_VERSION_FIELD",
    "MAX_FAILURE_REASON_LENGTH",
    "UNKNOWN_FAILURE_REASON",
    "VectorProjectionState",
    "VectorProjectionReference",
    "VectorProjectionSpecification",
    "VectorProjectionVersion",
    "ActiveProjectionVersionResolver",
    "VectorProjectionLifecycleService",
    "VectorProjectionCleanupService",
    "VectorRecordDeleteOperations",
    "normalize_failure_reason",
]
