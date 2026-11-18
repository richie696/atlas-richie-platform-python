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

provider 适配器（如 `atlas-richie-vector-pgvector`）单独安装，核心层不引入任何驱动。