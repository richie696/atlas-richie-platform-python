# T00.5 Rust Runtime Adapter 决策与验收设计

状态：实施中；实现以本文件及主清单 T00.5 为准（2026-10-17）  
范围：仓库内 Rust demo、官方 Sentinel Rust 执行引擎、官方 Nacos Rust SDK、Consul source adapter、既有 Collector 协议；不改共享 Nacos/Consul 数据，不改变已冻结的跨语言协议。

## 1. 能力核验与支持边界

- Sentinel 官方 Rust 仓库发布 `sentinel-core 0.1.3`，提供规则 `load_rules`、显式资源 Entry、Consul/etcd/Kubernetes/Apollo datasource feature、Prometheus exporter feature；官方项目没有 Nacos datasource feature。定向 Entry 测试发现 exporter 对 `handled_total` 传入的 label cardinality 与注册描述不一致，真实 pass 路径 panic；因此此版本 Rust profile 禁用 exporter，不能声称其可供 Prometheus 使用。
- Nacos 官方 Rust SDK 为 `nacos-sdk 0.8.2`，默认提供 config/naming 与 HTTP auth feature，使用 gRPC client；本实现优先使用它访问 Nacos 3，不手写 Nacos gRPC 协议或退化到 Nacos 3 已移除的 HTTP v1 API。
- T00.5 首期只将经验证的 **Flow / direct / reject / QPS** 规则语义列入 `sentinel-rust-v1` profile。官方 Rust FlowRule 明确是 QPS 统计，不提供 Java/Go 的并发数阈值语义；未知规则类型、链路/关联等未证明语义、非法值 fail closed，不能因 SDK `load_rules` 对单条规则容错而报告整个快照成功。
- 原生 Nacos/Consul JSON 由 Rust adapter 显式解析为上述受支持的 Sentinel Rust Flow subset。managed source 使用既有 versioned envelope，解包后仍走同一个 strict candidate validator；不创建第二套规则语义。
- 官方 exporter 输出 Sentinel 核心过程指标，供 Prometheus scrape；Metrics V2 reporter 仅在可从 demo 的 HTTP 请求边界可靠构造并遵守当前冻结 producer contract 时启用。Rust 尚未实现的语义必须标 unsupported/unavailable，不从 Prometheus scrape 指标反推规则观察或 HTTP TPS。

## 2. 推荐结构与边界

在 `components/sentinel/demos/rust-sentinel/` 建立独立 Cargo 工程，目录按责任分层：

```text
src/
  main.rs                 # 配置校验与 composition root
  app.rs                  # 真实 HTTP demo endpoint 与 Sentinel resource entry
  source/                 # RuleSnapshotSource、Nacos SDK adapter、Consul adapter
  rules/                  # 版本化 envelope 解码、profile validator、规则映射
  reporting/              # Rule Load Observation / managed receipt / Metrics V2
tests/                    # source contract、profile contract、runtime acceptance
```

- 规则读取、候选验证与快照版本事实属于 runtime adapter；Sentinel SDK 只负责经验证的规则执行。
- Nacos adapter 用 `nacos-sdk` config client，通过有界 polling 拉取初始及更新配置；不依赖 SDK push/listener 可用性。Consul adapter 使用 HTTP KV 精确 key 并沿用 T00.4 的错误、secret 与大小上限语义。
- composition root 仅允许 `RULE_SOURCE_PROVIDER=nacos|consul` 显式选择。一个进程只有一个选定权威 source，不加 source priority、静默 fallback 或注册表。
- `RuleSnapshotSource` 是 Runtime 消费的最小同步能力；Reporter 为已发生的状态事实提供异步、有界投递。source adapter 不拥有规则发布历史，不写控制台数据库。
- Runtime 先 strict decode/validate 全快照，再应用规则；应用失败或坏快照保留 last-known-good，并产生稳定失败观察。首次无法加载有效快照时 HTTP demo 不就绪。

## 3. 设计模式评估（编码前门禁）

- **Adapter（采用）**：Sentinel Rust `FlowRule`、Nacos SDK gRPC config、Consul HTTP KV 和既有语言无关 source/reporting contracts 具有不同技术类型。只在 `source/`、`rules/`、`reporting/` 翻译，不让 SDK 类型进入 Console/API 或业务 endpoint。收益是同一 runtime loop 不因 provider 改写；同一候选语义不因 Rust 另造 wire。替代方案“endpoint 里直接调 SDK”会把连接、错误、校验与执行混在业务入口。
- **Strategy（只用稳定 Port，不另建策略/注册框架）**：source 的确可替换，但单一 source 在进程启动时选定；由 composition root 一次组装具体 adapter 足够。多 source 竞争/优先级不属于本产品配置。
- **Observer / Mediator（不采用）**：Rule Load、receipt 与 metric 是不同的有界 reporter 投递，不需要彼此同步编排；直接依赖各自的最小 Port，不构建全局事件总线。
- **Factory / Abstract Factory（不采用）**：只有一个 Source 对象待组装，显式启动分支即可；没有一组需保持兼容的实现族。
- **Facade / Template Method（不采用）**：Sentinel Engine API 与 polling 生命周期已有边界；不叠一个万能 manager 或继承式算法骨架。

## 4. 风险—验证矩阵

| 风险/边界 | 定向验收 |
|---|---|
| Sentinel Rust profile 语义漂移 | Cross-language golden fixtures；合法 subset 完整映射；未支持字段/规则/重复 identity 全候选拒绝；`load_rules` 前后当前快照一致性 |
| Nacos SDK 与 Nacos 3 | 锁定 Cargo dependency；真实已运行 Nacos 3；只用随机唯一 Data ID；首次无 HTTP 业务流量加载、更新、删除/恢复、SDK close；finally 只清本轮 key |
| Consul source 可替换性 | 与 Java/Go 同一 source contract；HTTP mock 覆盖精确 key、`dc`、ACL header、404、401/403、5xx、超时/上限与错误脱敏；owner-labeled disposable Consul 真实更新/恢复 |
| LKG 与故障 | 无效候选不应用、active digest 保持；source 中断保留 LKG；source 恢复重新应用；重启后先成功加载有效规则再宣称 ready |
| Managed / native 观察 | Native snapshot observations 按既有 V1 schema 发送；managed receipt 精确 tuple/target/version 身份不重构；profile 与 binding unsupported 时明确 unknown/rejected，不伪报 applied |
| Reporter transport 与指标 | mTLS Collector durable ACK/重试行为复用当前协议语义；有界队列；Metrics V2 从 demo HTTP boundary 上报完成响应 / admitted / blocked / business counters 与 RT histogram；进程 CPU/RSS/memory ratio 只有真实采集能力时才报告，否则 unavailable；不声称源观察等于每条规则命中 |
| 构建可复现性 | 锁定 `Cargo.lock`；Docker Rust toolchain 编译、测试、Clippy/fmt；记录本地没有 Rust toolchain，测试只用本轮唯一构建容器或后续可复用的安装方式 |

外部服务临时资源使用唯一 owner label、loopback 随机映射与测试自有唯一配置；不停止、不删除、不写用户已有服务或共享配置。完整跨页浏览器旅程由 T07.1 从当前工作区源码运行验收；pip/wheel 安装与 PyPI 发布不属于该 E2E，另走独立发布流程。

## 5. 不推荐的替代方案

1. 自行实现 Nacos gRPC：Nacos 已有官方 Rust SDK，会复制认证、双工流和协议兼容逻辑，且增加维护面。
2. 依赖 Nacos 3 HTTP v1：3.x 不再提供该旧 HTTP client API；这会让规则接入无法在用户目标服务版本验收。
3. 把 SDK 的 Consul datasource 直接当作生产 Source：它虽是官方能力，但无法自动满足本产品的统一 strict snapshot、managed envelope、LKG/Reporter 顺序与错误脱敏合同；仍须通过本项目适配边界接入与验收。
4. 用固定 HTTP 返回字符串或共享 fixture 证明真实 Rust Sentinel 已限流：这种测试没有经过 Sentinel Entry / Rule Manager，不能关闭 T00.5。
5. 宣称全规则类型、全指标和全回执支持：首期只发布经真实 SDK 与协议合同逐项证明的 capability；其他类型保留 unsupported/unknown。

## 6. 当前实现与定向验收（2026-10-17）

- 已实现真实 `sentinel-core 0.1.3` Flow Adapter、Nacos 官方 Rust SDK `0.8.2` polling source、Consul KV source、strict `sentinel-rust-v1` 候选验证、LKG、启动先加载、`/health`/`/rules`/`/demo`，以及有界 Rule Load Observation / managed receipt reporter。Demo 支持边界与 SDK exporter 已知问题见同目录 README；这不是全规则兼容或生产安装包。
- `cargo fmt --all -- --check` 通过；`cargo clippy --locked --all-targets -- -D warnings` 通过；`cargo test --locked` **9 passed**。涵盖官方 SDK QPS 决策、Java/Go golden 归一一致性、未知字段整体拒绝、managed envelope tuple/hash/sequence 校验、Consul 请求和错误分类、reporter 有界队列及事件字段脱敏。
- 对用户既有 Nacos 3 执行显式 opt-in 定向验收：**1 passed**。只写入并删除本测试随机 Data ID / Group；真实运行时先无业务流量加载，Flow 规则按阈值拒绝，合法热更新生效，非法候选保留 LKG，删除配置模拟 source outage 时 LKG 继续执行，恢复规则后应用新阈值，进程重启后再次先加载当前快照再开放 `/health`。
- 对本轮临时 Consul `hashicorp/consul:1.21.1` 同一矩阵：**1 passed**。容器使用 owner 标签和 loopback 端口，测试后精确停止并移除；只删除本测试生成的唯一 KV key。没有停止用户已有 Nacos、Console、Collector、Prometheus 或 Java/Go 服务。

### T00.5 关闭结论

- **真实组合链路已通过**：同一个 Rust Runtime 进程从本轮随机 Consul KV 读取 managed envelope，strict validate 后加载真实 Sentinel Engine；实际 `/demo` 请求得到 200 与 429。该进程的首个 Metrics V2 snapshot 先建立 Reporter 的 current epoch，随后同进程 Rule Load Observation 与 managed publication receipt 通过 mTLS Collector 发送；在隔离 SQL 中验证 epoch、binding/publication/version tuple 和请求计数一致。
- **持久投影/API 已通过**：真实 Collector 将 observation/receipt durable ingest 到 SQL inbox/outbox；运行两个 production projection workers 后，用认证 Console API 从同一隔离 authority 读回 `applied` observation 与 receipt，且 process epoch 与 Metrics V2 enrollment 一致。
- **验证记录**：`bash ../demos/tools/with_disposable_rust_consul_collector_acceptance.sh` 通过 **1 passed**；同文件回归 `uv run --extra test --extra collector --extra sqlite-local pytest -q tests/test_metrics_collector_tls_acceptance.py` 为 **5 passed, 1 skipped**；前端单位逻辑 `npm run test:logic:focused -- charts` 为 **7 passed**。临时 Consul 及 runtime 容器按随机 owner label 清理，只删除本轮唯一 Consul KV；共享 Nacos、Console、Collector、Prometheus、Java/Go 服务与数据库均未修改。
- **支持边界**：Rust Metrics V2 支持 demo HTTP completed、Sentinel admitted/blocked、业务 completed 和 RT histogram；`sentinel-core` 0.1.3 官方 Prometheus exporter 的已知 pass-path panic 不启用。Rust process CPU/RSS/memory ratio 明确为 unavailable，不伪造 HOST 指标或宣称主机监控已覆盖。此限制记录在 capability matrix 与 demo 文档，属于本阶段已知 unsupported 能力，不阻断已定义的 Rust runtime/source/rule-observation/receipt 功能闭环；HOST 监控仍由独立 Prometheus adapter 提供。
- **结论**：provider→Engine→同进程 reporters→Collector durable ingest→outbox projection→认证 Console API readback 已形成同一身份/epoch 的完整定向闭环，故 **T00.5 关闭**。这不是 T07.1 的完整多页浏览器旅程；T07.1 从当前工作区源码运行验收程序功能，不要求 pip-installed Console。
