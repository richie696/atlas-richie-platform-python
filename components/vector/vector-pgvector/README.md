# atlas-richie-vector-pgvector

PostgreSQL + [pgvector](https://github.com/pgvector/pgvector) 适配器，实现
`atlas-richie-vector-core` 的 `VectorStoreEngine` 协议。

只依赖 `vector-core` + `psycopg[binary]`，不引入 SQLAlchemy / Spring AI 等价物。

## 特性

- **ACL 预过滤下推**：过滤树编译为**全参数化**的 JSONB 谓词（字段名也是绑定
  参数，不做字符串拼接），在召回阶段就排除无权文档，而不是检索后裁剪。
- **三种距离度量**：`cosine` / `l2`(euclidean) / `ip`(dot)，各自声明独立的
  `VectorScoreSemantics`，`minScore` 语义由核心解析器据此校验。
- **索引生命周期**：HNSW / IVFFlat / 无索引，`ensure_schema()` 幂等建表建索引，
  附带 `metadata` 的 GIN 索引以加速 ACL 谓词。
- **查询调参**：`hnsw.ef_search` / `ivfflat.probes` 通过 `SET LOCAL` 在事务内生效。
- **客户端 MMR**：pgvector 无服务端 MMR，候选向量回传后由核心 diversifier 重排。

## 用法

```python
from atlas_richie.vector_pgvector import PgVectorProperties, PgVectorStore
from atlas_richie.vector_core import VectorQueryRequest, VectorQueryResolver

store = PgVectorStore(PgVectorProperties(
    dsn="postgresql://postgres:***@127.0.0.1:15432/postgres",
    table="kb_vectors", dimension=3, metric="cosine",
))
store.ensure_schema()
resolver = VectorQueryResolver(store_defaults=store.query_defaults(),
                               score_semantics=store.score_semantics())
results = store.search([0.1, 0.2, 0.3], resolver.resolve(VectorQueryRequest.of("hello")))
```

集成测试需要真实 PostgreSQL + pgvector；不可达时自动 skip。