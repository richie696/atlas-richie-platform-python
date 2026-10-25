# T00.4 Java/Go Runtime 规则源适配器决策与验收设计

状态：Adapter 与真实 provider 定向验收通过；T00.4 父项仍开放（2026-10-17）  
范围：仓库内 Java/Go Sentinel demo 的规则源边界；不改 Console API、Rule Load Observation V1、Metrics V2、Nacos/Consul 已登记源数据或现有长驻 demo。

## 1. 事实与缺口

Java demo 在 `JavaSentinelDemo` 中直接构造 Nacos `ConfigService` 并完成读取/轮询；Go demo 在 `main` 中直接构造 Nacos `ConfigClient`，`pollConfig` 虽接受窄读取接口，但仍绑定 Nacos `ConfigParam`。当前真实验收证明了两个官方 Sentinel 引擎通过 Nacos 读取、应用、拒绝坏快照和恢复；Dashboard 设计同时把已登记 Nacos 与 Consul 列为 Runtime 规则源。因此当前代码尚不能按同一 Runtime 接入设计消费 Consul KV 规则。

## 2. 冻结的推荐方案

两种语言都在 Runtime demo 的规则读取边界定义小型 `RuleSnapshotSource` 能力：读取指定规则快照、报告稳定的读取失败分类、关闭自有 client。Nacos 和 Consul 各自实现适配器，官方 Sentinel 规则解码器、规则原子应用、last-known-good、观察/回执 Reporter 与 polling 调度留在原有 Runtime/application 边界。

配置以显式 `RULE_SOURCE_PROVIDER=nacos|consul` 选择，缺省仍为 `nacos` 以保持已有 demo 兼容。Nacos 保留 namespace/group/Data ID 与官方 SDK；Consul 通过官方 HTTP KV API 读取指定 key，支持 datacenter `dc` 与可选 ACL token (`X-Consul-Token`)。Consul endpoint 仅接受 HTTP(S)；禁止把 token 放进 URL、日志、错误文本或 demo `/rules` 输出。TLS 校验使用平台默认信任链，不提供跳过证书校验开关。

Consul 精确 key 读取使用 `/v1/kv/{key}?raw=true`，按 key path segment 编码并可选传 `dc`。仅 2xx 且正文不超过 65,536 字节的响应交给既有规则 decoder。404 表示当前快照缺失：首次读取失败并阻止 HTTP 服务就绪，运行期读取失败保留 last-known-good；空正文仍交由既有 strict decoder 拒绝，不把缺失、空文档或错误响应转换成 `[]`。401/403 归类为稳定的认证拒绝，其它状态、超时、传输错误和过大响应归为 source unavailable；对外日志不含 token、正文或完整异常。

Consul env：`CONSUL_URL`、`CONSUL_KEY`、可选 `CONSUL_DATACENTER`、可选 `CONSUL_TOKEN`。只在 `RULE_SOURCE_PROVIDER=consul` 时读取 Consul 参数；Nacos 配置名及默认不变。Reporter 的 binding/profile/identity 仍由显式 enrollment 配置提供；不从 provider 内容推断身份，也不改变 managed envelope、receipt 或 observation payload。

## 3. 设计模式评估

- **Adapter（采用；此前已获用户批准）**：Java/Go Nacos SDK 与 Consul HTTP/ACL/HTTP 状态码的具体语义不同；在 demo infrastructure/source adapter 中翻译为 Runtime 的窄 `read snapshot` 能力，避免 Sentinel rule loader、poll loop 和 Reporter 依赖厂商 SDK/HTTP DTO。contract checks 覆盖成功、缺失、拒绝、超时/5xx、大小上限、关闭和 LKG 不变。
- **Strategy（不另造对象层）**：provider 确实可替换，但由 composition root 一次选择 source adapter 已足够；不在业务处理循环逐请求分派，也不增加新的 strategy registry、优先级或 fallback。缺失/错误的 provider id 必须启动失败，不静默降级到 Nacos。
- **Factory Method / Abstract Factory（不采用）**：只有一个能力对象需要按一个 provider 构造，composition root 的显式 switch 足够；没有兼容对象族需要一起生产。
- **Facade / Template Method（不采用）**：规则 decoder、应用、poll loop、Reporter 已有清晰所有权；新增 Facade 会把这些既有职责再次聚合，Template Method 会为两个不同 SDK 强加继承生命周期。两种 adapter 复用同一窄契约测试，不复制规则状态机。
- **Observer/Mediator（不采用）**：当前是单个 Runtime 按周期读取一个选定 source，不是多方订阅事实或同步协调多个对象。

## 4. 验收矩阵

| 边界 | 定向验证 |
|---|---|
| Source contract | 两语言相同成功/缺失/拒绝/不可用分类；读取错误不更改 active snapshot；关闭后无后台读取 |
| Consul adapter | 路径编码、datacenter、ACL header、HTTP(S)、响应大小上限；错误中无 token/规则正文；Java 4 个 source tests 与 Go `httptest` 合同通过 |
| 真实 Consul provider | 本轮启动的唯一 owner-labeled、无持久卷 Consul 容器；唯一 key 检查占用后才写；首次无流量加载、真实 429、合法热更、非法更新 LKG、key 暂时删除/恢复、进程重启、finally/defer 仅删除本次 key 并关闭进程；Java 与 Go 两套接受用例通过，owner 容器和端口已确认清理 |
| 真实 Nacos provider | Java/Go Runtime 已切到共享 source Port 后，各自重新对用户本机 Nacos 3 执行随机唯一 Data ID 验收并通过；只删除本轮数据，详情见主清单 §15.1436 |
| Collector-to-Console readback | Collector 接受真实 loopback mTLS observation 后，在同一个 disposable SQLite authority 执行 durable outbox projection，再经生产 SQL observation reader 和 authenticated Console route 按精确 binding/instance 读取 applied snapshot 与 checksum；不据此声称当前保留安装态 authority 或 Runtime SDK/browser 已联测 |
| Managed receipt retry | Go sender 对 503→204 保持同一 payload bytes 的既有测试；Java sender 新增包内 transport seam，验证 503 后仍保留队列、204 后才移除，重试字节完全相同；真实 Collector mTLS/durable-ACK 仍独立验收 |
| Existing contracts | `mvn test`、`go test ./...`、`go vet ./...` 通过；两个 real-provider tests 默认是 opt-in；既有 Metrics V2/Rule Load Observation/managed receipt 行为单测通过 |

真实 Consul acceptance 只证明两个语言 Runtime 对当前已支持的 Consul KV source 的加载执行；不证明 pip Console 当前认证用户的同 authority native binding UI/API 对账。后者继续按 T00.4/T06.7/T07.1 责任边界单独验收。

## 5. 被否决方案

1. 仅在文档标注“Consul 未支持”：会使 UI 接入引导与 Runtime 可消费能力不一致，违反 Nacos+Consul 已冻结产品边界。
2. 把 Consul 转成 Nacos 协议或让 Dashboard 推送至进程：引入额外配置桥接/写入权限及双写一致性，不能验证 Runtime 原生从登记源读取。
3. 给每种 provider 复制整份 polling/LKG/Reporter 主循环：两个实现容易在错误恢复、初始就绪和 Reporter 触发顺序上漂移。
4. 只用 mock HTTP 测试称真实支持：不能证明实际 Consul KV 行为、ACL header、源内容和运行中的 Sentinel 规则执行；本项使用 disposable Consul acceptance。

