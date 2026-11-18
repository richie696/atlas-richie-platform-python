# atlas-richie-vector-core

向量检索的**纯算法与契约层**，零第三方依赖。

对应 Java `cn.richie696.component.vector` 中不绑定 Spring AI `VectorStore` 的部分：

| 模块 | 内容 |
|------|------|
| `filters` | 可下推的过滤表达式树（Eq / In / ContainsAny / Range / Exists / Not / And / Or） |
| `filter_compiler` | Spring AI metadata filter DSL 编译器（字段名强校验 + 字面量转义） |
| `acl` | `AccessScope` / `DocumentVisibility` 与知识库 ACL 预过滤构造 |
| `query` | Core < Provider < Store < Request 优先级解析、硬安全上限、参数来源归因 |
| `diversify` | 确定性客户端 MMR 重排，带维度/字节安全上限 |
| `topology` | 能力声明、分数语义描述符、跨 Store 分数可比性守卫 |
| `execution` | 并发许可 + 超时 + 取消的执行守卫 |
| `engine` | `VectorStoreEngine` 协议，供各 provider 适配器实现 |
| `projection` | 投影版本模型与状态机契约、`ActiveProjectionVersionResolver` SPI |
| `bulk` | 批量入库事件协议（EMBEDDING/PERSISTING 分段）与攒批编排器 |

provider 适配器（如 `atlas-richie-vector-pgvector`）单独安装，核心层不引入任何驱动。

## 投影版本收敛

检索门面 `KnowledgeBaseVectorService` 支持可选的 `projection_versions` resolver
（对位 Java `ActiveProjectionVersionResolver`）：解析出当前活跃的投影版本集合后，
把 `projectionVersionId IN (...)` 追加到 ACL filter 一起下推给 provider；
集合为空时直接返回空结果，不打 provider。

```python
service = KnowledgeBaseVectorService(
    engine=vector_store,
    embeddings=embedding_service,
    projection_versions=projection_store,   # 可选；不注入即单版本语义
)
```

持久化实现见 `atlas-richie-vector-persistence-sqlalchemy`（关系库四表 + 状态机 +
manifest 账本 + 延迟清理 outbox）。

## 批量入库事件流

`BulkIngestionPipeline` 把"嵌入 → 攒批 → 持久化"编排成一条可观察的事件流：
单条失败降级为 `BulkItemFailed` 事件而不中断整批，整批结束总会发出一条
`BulkCompleted`（含成功/失败/嵌入调用/落库调用计数）。

```python
from atlas_richie.vector_core import (
    BulkIngestionPipeline,
    ModalityAwareRecordEmbedder,
)

pipeline = BulkIngestionPipeline(
    ModalityAwareRecordEmbedder(embedding_service),
    writer,                       # 落库回调：write(index_name, embedded_records)
)
for event in pipeline.execute("kb-1-index", records):
    ...                          # 订阅进度与失败归因
```

与 Java 的差异：Java 用 Reactor 冷流 + 并发度/时间窗刷批旋钮；Python 侧
`VectorStoreEngine` 本身是同步的，因此这里用生成器表达同样的冷流语义，
只保留真正生效的 `write_batch_size`（默认 100，与 Java 一致）与 `fail_fast`。