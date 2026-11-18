# atlas-richie-vector-persistence-sqlalchemy

向量投影（projection version）的**关系库持久化适配器**，实现
`atlas-richie-vector-core` 的投影契约，并作为 `ActiveProjectionVersionResolver`
的提供者接进检索门面。

对应 Java `atlas-richie-vector-projection-dao`。只依赖 `vector-core` + SQLAlchemy，
不引入其它组件的适配器——适配器之间不横向依赖。

## 📖 目录

- [🎯 组件概览](#-组件概览)
    - [核心特性](#核心特性)
- [🏗️ 架构设计](#️-架构设计)
    - [版本状态机](#版本状态机)
    - [四表关系](#四表关系)
    - [检索侧收敛链路](#检索侧收敛链路)
- [🚀 快速开始](#-快速开始)
    - [1. 声明依赖](#1-声明依赖)
    - [2. 初始化 store](#2-初始化-store)
    - [3. 写入与激活](#3-写入与激活)
    - [4. 接入检索门面](#4-接入检索门面)
    - [5. 驱动延迟清理](#5-驱动延迟清理)
- [📚 接口参考](#-接口参考)
    - [VectorProjectionStore](#vectorprojectionstore)
    - [VectorProjectionProperties](#vectorprojectionproperties)
- [🔧 能力与边界](#-能力与边界)
- [⚙️ 配置参考](#️-配置参考)
- [🔧 故障排查](#-故障排查)

## 🎯 组件概览

商用 RAG 需要"向量库可重建投影"：同一份文档在同一向量库内**按版本严格隔离**，
新版本激活后旧版本退场，到期后按 manifest 精确删除物理向量。检索侧则只认
"当前活跃版本"，由 resolver 解析出可见版本集合并下推给 provider。

### 核心特性

- ✅ **状态机落库**：PREPARING → WRITING → READY → ACTIVE → RETIRING → CLEANED，
  转移在事务内用 CAS 校验，不允许倒退、不允许终态回退
- ✅ **manifest 账本**：version → vectorId 一行一账，清理只凭账本精确删除，
  因此对不支持 metadata 过滤的 provider 同样成立
- ✅ **检索侧收敛**：`active_version_ids(tenantId, knowledgeBaseId)` 实现
  `ActiveProjectionVersionResolver`，检索门面据此下推
  `projectionVersionId IN (...)`
- ✅ **空集短路**：无可用版本时检索直接返回空结果，不打 provider——
  "解析失败"与"无版本"保持可区分，不会退化成全量召回
- ✅ **延迟清理 outbox**：旧版本退场时同事务入队清理事件，事务回滚则不产生
  "版本已退场但没有清理任务"的悬挂状态
- ✅ **投影写入器**（`VectorProjectionWriter`）：把 bulk 写入事件投影成版本状态切换与
  manifest 落库，并给每条记录补齐 tenant/kb/projection/version/sourceVersion/
  embeddingSpace 六个 metadata 字段——检索侧无需回查关系库
- ✅ **失败可重试**：清理失败记 attempts / last_error，下次调度自动重试，
  单版本失败不影响其它版本
- ✅ **无导入副作用**：导入包不建连接、不建表、不起后台线程

## 🏗️ 架构设计

### 版本状态机

```mermaid
stateDiagram-v2
    [*] --> PREPARING: begin_rebuild
    PREPARING --> WRITING: mark_writing (CAS)
    WRITING --> READY: mark_ready_if_no_failure
    WRITING --> FAILED: mark_ready_if_no_failure / record_failure
    PREPARING --> FAILED: mark_failed
    READY --> FAILED: mark_failed
    READY --> ACTIVE: activate
    ACTIVE --> RETIRING: activate (旧版本退场)
    RETIRING --> CLEANED: cleanup_due_projections
    RETIRING --> FAILED: mark_failed
    FAILED --> [*]
    CLEANED --> [*]
```

| 状态 | 含义 | 可检索 | 终态 |
|------|------|--------|------|
| `PREPARING` | 版本已创建，等待写入流开始 | ❌ | ❌ |
| `WRITING` | 正在写入向量库，计数持续累加 | ❌ | ❌ |
| `READY` | 写入完成，等待显式激活 | ❌ | ❌ |
| `ACTIVE` | 当前对外可见版本，同一 projection 至多一个 | ✅ | ❌ |
| `RETIRING` | 被新版本替换，处于可清理宽限期 | ❌ | ❌ |
| `FAILED` | 写入/激活失败，保留 `failure_reason` | ❌ | ✅ |
| `CLEANED` | 物理向量已按 manifest 删除完毕 | ❌ | ✅ |

### 四表关系

```mermaid
erDiagram
    rag_vector_projection ||--o{ rag_vector_projection_version : "projection_id"
    rag_vector_projection_version ||--o{ rag_vector_projection_record : "version_id (manifest)"
    rag_vector_projection_version ||--o{ rag_vector_projection_outbox : "version_id (cleanup event)"

    rag_vector_projection {
        string id PK
        bigint tenant_id
        string knowledge_base_id
        string document_ref
        string active_version_id "当前激活版本指针"
    }
    rag_vector_projection_version {
        string id PK
        string projection_id
        string source_version
        string index_name
        string embedding_space_id
        string state
        int written_records
        int failed_records
        string failure_reason
        timestamp cleanup_after
        timestamp activated_at
    }
    rag_vector_projection_record {
        string id PK
        string version_id
        string vector_id "向量库写入返回值"
    }
    rag_vector_projection_outbox {
        string id PK
        string event_type
        string version_id
        string state
        int attempts
        string last_error
        timestamp execute_after
        timestamp processed_at
    }
```

| 表 | 职责 | 写入时机 |
|----|------|----------|
| `rag_vector_projection` | (tenant, kb, document) → 当前激活版本指针 | 首次重建时创建；激活时换指针 |
| `rag_vector_projection_version` | 版本生命周期事实来源 | 状态推进、计数累加 |
| `rag_vector_projection_record` | version → vectorId manifest 账本 | 每条向量写入成功后（幂等） |
| `rag_vector_projection_outbox` | 延迟清理事件流 | 旧版本退场时同事务入队 |

### 检索侧收敛链路

```mermaid
sequenceDiagram
    participant App as 业务方
    participant KB as KnowledgeBaseVectorService
    participant PR as ActiveProjectionVersionResolver
    participant DB as 关系库
    participant VS as 向量库 provider

    App->>KB: search(knowledgeBaseId, request)
    KB->>KB: 构造 ACL filter（tenant/kb/status/visibility）
    KB->>PR: active_version_ids(tenantId, knowledgeBaseId)
    PR->>DB: 读 active_version_id 指针列
    DB-->>PR: {v1, v2}
    PR-->>KB: frozenset{v1, v2}
    alt 版本集合非空
        KB->>KB: AND projectionVersionId IN (v1, v2)
        KB->>VS: 下推 filter 召回
        VS-->>KB: 候选
    else 版本集合为空
        KB-->>App: 空结果（不打 provider）
    end
```

## 🚀 快速开始

### 1. 声明依赖

```toml
dependencies = [
  "atlas-richie-vector-persistence-sqlalchemy>=0.2.0,<0.3.0",
]
```

### 2. 初始化 store

```python
from sqlalchemy import create_engine

from atlas_richie.vector_persistence_sqlalchemy import (
    VectorProjectionProperties,
    VectorProjectionStore,
)

engine = create_engine("postgresql+psycopg://postgres:***@127.0.0.1:15432/postgres")
store = VectorProjectionStore(
    engine,
    create_table=True,          # 默认建表；生产建议用 migration 管理
    properties=VectorProjectionProperties(
        cleanup_delay=timedelta(hours=24),
        delete_batch_size=200,
    ),
)
```

> 导入不产生副作用：连接与建表都由调用方显式触发。

### 3. 写入与激活

```python
from atlas_richie.vector_core import (
    VectorProjectionReference,
    VectorProjectionSpecification,
)

version = store.begin_rebuild(
    VectorProjectionReference(
        tenant_id=1, knowledge_base_id="kb-1", document_ref="doc-42"
    ),
    VectorProjectionSpecification(
        source_version="etag-9", index_name="kb-1-index", embedding_space_id="bge-m3"
    ),
)

store.mark_writing(version.version_id)
for record in records:
    store.record_succeeded(version.version_id, record.id)   # 写 manifest 账本
store.mark_ready_if_no_failure(version.version_id)            # 有失败则转 FAILED
store.activate(version.version_id)                            # 旧版本自动退场
```

### 4. 接入检索门面

```python
from atlas_richie.vector_core import KnowledgeBaseVectorService

service = KnowledgeBaseVectorService(
    engine=vector_store,
    embeddings=embedding_service,
    projection_versions=store,   # store 天然满足 ActiveProjectionVersionResolver
)
```

检索门面会：

1. 拼好 ACL filter；
2. 调 resolver 拿活跃版本集合；
3. 集合非空 → AND `projectionVersionId IN (...)` 下推给 provider；
4. 集合为空 → 直接返回空结果，不打 provider。

### 5. 驱动延迟清理

清理**不会**在包内自动发生——与 Java 一致，调度由业务侧周期触发：

```python
class VectorDeleter:
    def delete_by_ids(self, index_name: str, ids) -> int:
        return vector_store.delete(ids)

store = VectorProjectionStore(engine, deleter=VectorDeleter())

# 由 Quartz / XXL-Job / 应用层定时任务周期调用
cleaned = store.cleanup_due_projections(max_versions=50)
```

未注入 `deleter` 时调用清理会**显式报错**，不会假装清理成功。

### 写入侧：投影写入器

`begin_rebuild` → `write` → `activate` 是完整的重建链路。写入器把 bulk 事件
回调到状态机：

| bulk 事件 | 状态机动作 |
|-----------|-----------|
| `BulkItemSucceeded` | `record_succeeded`（写 vectorId manifest + 累加计数） |
| `BulkItemFailed` | `record_failure`（累加失败计数 + 刷新失败原因） |
| 流正常结束 | `mark_ready_if_no_failure`（有失败则 FAILED，否则 READY） |
| 流异常终止 | `mark_failed`（保留失败原因，不再可激活） |

```python
from atlas_richie.vector_core import BulkIngestionPipeline, ModalityAwareRecordEmbedder

writer = VectorProjectionWriter(
    store,
    BulkIngestionPipeline(
        ModalityAwareRecordEmbedder(embedding_service),
        vector_store_writer,          # 落库回调
    ),
)

version = store.begin_rebuild(reference, specification)
for event in writer.write(version.version_id, records):
    ...                              # 消费进度与失败归因
store.activate(version.version_id)   # 必须在事件流消费完之后
```

## 📚 接口参考

### VectorProjectionStore

| 方法 | 说明 | 返回 |
|------|------|------|
| `begin_rebuild(reference, specification)` | 复用或创建 projection 行，新建 PREPARING 版本 | `VectorProjectionVersion` |
| `mark_writing(version_id)` | CAS：PREPARING → WRITING | `None` |
| `record_succeeded(version_id, vector_id)` | 写 manifest（幂等）并累加 `written_records` | `None` |
| `record_failure(version_id, reason)` | 累加 `failed_records` 并刷新失败原因 | `None` |
| `mark_ready_if_no_failure(version_id)` | 有失败→FAILED，否则→READY | `None` |
| `activate(version_id, cleanup_delay=None)` | READY→ACTIVE，旧版本退场并入队清理 | `None` |
| `mark_failed(version_id, reason=None)` | 标记失败（ACTIVE/CLEANED 拒绝） | `None` |
| `find_version(version_id)` | 读版本快照 | `VectorProjectionVersion \| None` |
| `active_version_ids(tenant_id, knowledge_base_id)` | 活跃版本集合（resolver 读路径） | `frozenset[str]` |
| `manifest_vector_ids(version_id)` | 读 manifest vectorId 列表 | `tuple[str, ...]` |
| `due_cleanup_versions(max_versions)` | 列到期待清理版本 | `tuple[VectorProjectionVersion, ...]` |
| `pending_cleanup_events(limit=100)` | 列到期清理事件 | `tuple[VectorProjectionCleanupEvent, ...]` |
| `cleanup_due_projections(max_versions)` | 执行清理，返回成功数 | `int` |
| `close()` | 释放连接池 | `None` |

### VectorProjectionWriter

| 方法 | 说明 |
|------|------|
| `write(version_id, records)` | 写入记录并驱动状态机；返回惰性事件迭代器，**必须消费到底**才会走到 READY |

### VectorProjectionProperties

| 参数 | 默认值 | 业务含义 |
|------|--------|----------|
| `cleanup_delay` | `24h` | 旧版本退场后的宽限期。太短会在读链路仍用旧版本时删掉它；太长会让向量库残留 |
| `delete_batch_size` | `200` | 单批下发给 provider 的 vectorId 数量，受 provider 单次请求上限约束 |

## 🔧 能力与边界

| 能力 | 状态 | 说明 |
|------|------|------|
| 版本状态机 | ✅ | 事务内 CAS 推进，终态不可回退 |
| manifest 账本 | ✅ | (versionId, vectorId) 幂等 |
| 延迟清理 | ✅ | 需外部调度器触发；无内置线程 |
| 检索侧 resolver | ✅ | 读指针列，检索热路径只读一次 |
| 多租户隔离 | ✅ | tenant_id + knowledge_base_id 联合定位 |
| 向量库写入 | ❌ | 本包不写向量库，只记账与清理 |
| 内置调度线程 | ❌ | 刻意不做，避免导入即起线程 |
| 跨库分布式锁 | ❌ | 单库部署下事务 + CAS 已足够 |

## ⚙️ 配置参考

| 场景 | 建议 |
|------|------|
| 常规 RAG（单库单实例） | `cleanup_delay=24h`、`delete_batch_size=200` |
| Redis 向量库 | `delete_batch_size ≤ 300` |
| Milvus / Qdrant | `delete_batch_size=500` |
| 同步阻塞式 provider | `delete_batch_size=50~100` |
| 灰度期需要快速回滚 | 调大 `cleanup_delay`，保证旧版本仍在库 |

## 🔧 故障排查

| 现象 | 排查动作 |
|------|----------|
| 检索结果为空且无 provider 调用 | resolver 返回空集合：检查 projection 表 `active_version_id` 是否为空 |
| 旧版本向量仍在库 | `cleanup_due_projections` 未被调度，或 `cleanup_after` 未到期 |
| 清理反复失败 | 查 `rag_vector_projection_outbox` 的 `attempts` / `last_error` |
| `only READY projection versions can be activated` | 版本未走完 WRITING→READY，或存在失败记录 |
| `cleanup requires a vector record deleter` | 构造 store 时未注入 `deleter` |
