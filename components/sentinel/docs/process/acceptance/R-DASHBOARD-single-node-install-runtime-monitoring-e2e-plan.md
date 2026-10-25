# Sentinel 单节点源码运行、运行时接入与监控 E2E 验收方案

状态：**本轮执行基线（实现中间文档，不构成 PyPI 发布或生产支持承诺）**

> **2026-10-24 范围更新：**当前 E2E 标准是从源码工作区启动并验证程序自身。本文后续带日期的 pip/wheel 安装过程仅作历史证据；不构成当前 E2E 检查项、前置条件或完成标准。包构建/安装兼容性和 PyPI 发布另由独立发布流程验收。

## 1. 目标与范围

本轮验证程序自身的真实运维路径：从当前源码工作区启动 Console 与 React → 浏览器完成控制面初始化 → 登记 Nacos/Consul 规则源 → Java/Go Sentinel 官方 SDK 在无业务请求时加载规则 → 请求业务 Demo 观察确实限流 → Console 页面读取规则目录与实例加载状态 → 配置 Prometheus-compatible 查询源 → 展示 Linux HOST 指标及已有 PROCESS/业务曲线 → 重启/修改规则后复核状态。

单节点本机验收；使用当前工作区 Python/React 源码、Console HTTP API、持久 SQL、Nacos/Consul、Java/Go 进程、Prometheus HTTP API 和隔离浏览器。Mock/fixture、编译通过、健康端点、单独 provider SDK 调用均不能替代以上运行链路。E2E 不构建或安装 wheel，也不执行 PyPI 发布；这些归独立发布流程。

不包含 Rust SDK、Kubernetes 多节点/Ingress/RWX 验收（T00.3）、集群部署、PyPI 发布、对用户生产规则的写入。Java/Go demo 与临时规则使用明确的 `sentinel-e2e-<run-id>` 命名；仅使用本轮专属数据 ID，记录验证后是否保留及其影响。

## 2. 已核实的基线

- 独立运维控制台包为 `atlas-richie-sentinel-console`，其 CLI 为 `sentinel-console`；`atlas-richie-sentinel-dashboard` 是另一个 per-process 诊断 wheel，不可混称。
- Console 提供首次初始化及后续登录/管理 API；本轮 E2E 从当前源码启动 Console 与 React，避免已安装包或旧 dashboard 污染源码验证结论。
- SQLite、PostgreSQL、MySQL 走已建立的数据库 Adapter/显式 composition。单节点持久化首装依部署选项；生产 SQL 身份、迁移、安全策略仍由已支持的 Adapter 承担。
- Console API 0.8.0 冻结；T03.4/T03.5 的 additive 0.9.0 已批准；Prometheus source/query 是单独监控域，不能混入 Nacos/Consul rule source union。
- 当前本机 Nacos 3.2.3 用户实例已运行；不得改动或覆盖既有配置。认证 Nacos 管理路径不向明文 HTTP 发送凭证；本轮若需 TLS bridge，只监听 loopback、无请求体/凭证日志，并且只转发本轮随机 Data ID。
- 本轮之前机器没有 Prometheus 9090 服务。不得把 Docker Desktop Linux VM 误报成 macOS HOST。

## 3. 推荐实施决策与未选方案

### 3.1 首次启动与本机授权

**已批准并按此实现：** 首次启动默认仅监听 `127.0.0.1`；当 Console 绑定地址、全部允许的浏览器 Origin 都是 loopback，且未配置可信反向代理 CIDR 时，Setup 页面自动通过独立的 loopback-only API 换取短时 bootstrap grant，不显示、不要求输入一次性授权码。服务端仍校验实际连接对端为 loopback、精确 Origin、CSRF proof、数据库未初始化及 setup window 开放；这张 grant 只授权初始化流程，不登录或创建管理员会话。若显式绑定非 loopback、允许非 loopback Origin 或配置可信代理，则无授权码本地路径关闭，远程初始化必须提供部署侧 operator code。operator code 不是产品授权或 PyPI 共享码。完成初始化后 setup window 关闭，后续再次访问不能重开初始化。

Web 初始化仍由操作人员填写所选 SQL 连接、首个管理员密码和一个必需的 Nacos/Consul 规则源；连接凭据只在写入时提交，页面不回显。Prometheus 作为可跳过的连接与采集向导，独立保存于 SQL；它不是初始化数据库/身份的前置条件。初始化后提供“继续配置监控”入口，规则源和监控源都可在系统管理中持续维护。

**不采用的方案：** 所有部署都强制输入 operator code 会让单机 pip 首装依赖额外的秘密分发步骤；所有来源都免 code 则会让远程首次初始化暴露；由 PyPI 发放固定 code 会变成可共享、可泄露的静态秘密。当前实现保留远程 operator-code exchange，同时为严格 loopback 拓扑增加独立的免 code 路径。部署仍需配置 bootstrap authority state path 与 fingerprint key 来保护短时 grant/失败限制状态；这些是本机服务安全状态，不是用户需要从 PyPI 获取的授权码。

**决策理由：** 授权码只保护远程首次初始化的管理权限，不是软件授权。loopback 来源、Origin 与反向代理配置三重约束把免 code 能力限定在机器本地；短时、HttpOnly、Secure、SameSite strict grant 仍受服务端状态验证，不能代替管理员密码。远程拓扑保留显式部署秘密门禁，避免把易用性默认扩展成网络开放。

**本轮定向验证（2026-10-17）：** 首次授权后端与部署配置测试 56 项通过；前端 no-code authorize-local HTTP 测试 1 项通过，初始化状态/授权逻辑测试 7 项通过，React TypeScript typecheck 通过。覆盖 loopback grant、远端 peer 拒绝、初始化窗口关闭拒绝、精确 Origin/CSRF、无 operator code 时 loopback 部署配置可组合，以及同一配置改为 `0.0.0.0` 时 fail closed。此证据是代码和 HTTP 边界验证，不替代全新状态目录下从当前源码启动并由隔离浏览器执行的首次初始化 E2E；目前也仍需部署端配置 authority state path/fingerprint key 等本机状态密钥。

**内置浏览器只读复核（2026-10-17）：** 对本机 fresh-wheel 实例 `127.0.0.1:53203/#/setup` 读取可访问性树，首次流程已直接进入规则来源配置步骤，未出现授权码输入页；符合 loopback 部署不要求用户取得 operator code 的决定。该页面当前 Nacos 连接检查失败，因此只证明本机授权步骤被省略且向导可继续，不证明配置中心连通、初始化提交、管理员登录或完整首装 E2E；这些仍属于 T07.1 最终门禁。未修改该页面当前表单/配置。

### 3.2 规则源与 Java/Go 应用接入

**推荐：** Nacos/Consul 是规则权威源；Console 登记 binding 后主动读 provider，因此无需业务流量即可展示规则。Java 与 Go 分别使用官方 Sentinel 引擎/SDK 和官方 Nacos datasource 扩展（若 SDK 对 Nacos 3.2.3 有协议兼容限制，则以实测结果决定是否使用官方 Nacos 客户端配合官方规则 manager 的薄边界 Adapter，并清楚限定支持矩阵）。Demo 提供 `/api/hello` 固定响应与独立有界延迟端点；健康/版本接口不被误认为 Sentinel 流控证据。规则 Data ID 含本轮唯一 run-id，修改真实 threshold 后重复调用，证明合法限流和热更新。

规则获取、运行时状态上报、Prometheus 抓取分别展示为三个地址/能力；不能把 Sentinel Dashboard URL 当作 Nacos 地址，也不能宣称仅填写 Dashboard 地址即可获得 Nacos 加载、实例回执、主机指标全部功能。原生 JSON 加载状态走 T03.5 Rule Load Observation；managed publication receipt 仍只用于证明特定发布，不伪造原生规则 publication ID。

**不推荐：** 使用 Alibaba Gateway demo（没有实际业务 handler，且不是本项目可独立验收的业务服务）；仅验证 Nacos `get_config()` 成功；在 Demo 里写死内存规则；使用私有控制面钩子替代官方 Sentinel SDK；通过注入 HTTP 请求才触发规则“加载”结论。

#### T00.4 Java/Go Runtime Adapter 边界与选择理由

**实现边界：** 每个语言 demo 保持真实业务 HTTP handler，分别复用官方 Sentinel Java Core / Sentinel Go SDK 的 entry、规则 manager 与 Nacos 官方客户端。Demo 内按职责分开 `RuleSourceAdapter`（读取、版本、失联分类）、`SentinelRuleAdapter`（严格校验并原子调用官方 manager）和 `ReportingTransportAdapter`（mTLS、协商、Metrics V2 与 Rule Load Observation 序列化/ACK）；业务 handler 只使用官方 SDK entry。Adapter 不创建第二套限流算法，不让 SDK 类型越过应用自己的边界。规则成功应用事实在 SDK apply 成功后产生；发送故障只能影响上报，不能撤销已生效规则或阻塞业务请求。

**Profile 决定：** 首期分别使用 binding profile `sentinel-java-v1` 与 `sentinel-go-v1`，共享 fingerprint 语义名为 `sentinel-flow-runtime-v1`。只接受唯一 UTF-8 resource、每秒 QPS threshold、direct/current-resource 匹配与立即 reject；Java `grade=1` 的 `count` 与 Go `statIntervalInMs=1000` 的 `threshold` 才映射为同一语义。只允许受控字段，未知字段、已知但未建模字段、duplicate resource、非 plain-decimal/excess precision、超出阈值/枚举范围、其他窗口/控制模式、cluster/warm-up/queueing 以及 profile 与 binding 不符均 fail closed，并保留 last-known-good。canonical member 与整组 checksum 规范见 `docs/protocol/SENTINEL-FLOW-RUNTIME-PROFILE-V1.md`；来源原始字节摘要、provider revision 与 canonical checksum 明确分开。逐规则 membership 只有在 Java、Go、Python 三方都读取同一 shared positive/negative vector，且 Console runtime-membership allowlist 单独接受 profile 时才设为 complete。规则目录解析是另一项显式能力：当前 Java/Go 只投影该文档定义的 Flow V1 子集；其余规则族仍为 unsupported，不从 runtime membership allowlist 推导。

**身份及传输：** demo 专属 mTLS client certificate 由本机 acceptance harness 生成，证书 SHA-256/principal 通过安装包提供的 `sentinel-console metrics-reporter enroll` 命令登记到同一个 SQL authority，绑定 environment/app/worker instance/process。真实 HTTP/2 TLS 连接执行 Collector 协商，随后以同一 enrollment 上报当前规则快照、心跳和 Metrics V2；Collector ACK 必须经 durable SQL 接受。演示证书/绑定仅用于本地 synthetic identities，不把 client 自报 ID 当认证，也不使用固定密钥。测试结束只撤销本轮 principal；保留的 demo 进程需保留它们时，记录证书/绑定有效期与本机审查用途。

**模式评估：** 已批准的 Adapter 模式隔离官方 SDK/provider 与 Sentinel 的稳定产品边界；直接的同步调用负责读取、校验和 `loadRules`，只有 apply 后异步发送的事实进入有界 reporting worker。当前每个 runtime 只有一个规则 apply consumer，不增加 Observer/Mediator/Strategy registry/Template Method；没有第二算法、多个独立订阅者或稳定流程变体来支撑这些结构。Go/Java fixture validator 只能证明 wire contract，不替代运行 SDK 实际应用的 acceptance。

**不采用的方案：** 不把仅能 `200/429` 的业务 demo 当成完整 T00.4；不因某个版本 SDK 看起来支持 Nacos 就假设 Nacos 3 listener 可用，当前以真实 polling 接入并分别验证更新/LKG；不让 demo 在业务请求到来时才读取规则；不将 HTTP QPS、blocked ratio 或 RT 从规则状态推测；不使用测试端点、进程日志或未经 enrollment 的 body 字段冒充 Collector durable observation。

**canonicalization 方案取舍：** 不直接 hash Nacos 原文（JSON field order/spacing 不同会把等价规则误判为不等）；不把任一语言 DTO 作为跨语言 wire schema（Java `count` 与 Go `threshold/statIntervalInMs` 并非同构）；不尝试推导任意统计窗的浮点 rate（会引入舍入差异）。首期只把 Go 窗固定 1000ms、阈值限定六位小数以内的 plain decimal，再用 UTF-8 length-prefixed resource + normalized decimal threshold 计算 member fingerprint。通过官方 SDK 实际 apply 后异步发送 mTLS Observation；不在 HTTP handler 同步发网，也不把 Collector 当前 projection 回执扩展成另一种业务发布协议。

#### 2026-10-17 T00.4 现场补充：Java/Go durable rule observation 与 LKG 恢复

- Java、Go 使用本轮独立 reporter enrollment、各自唯一 environment/app/instance/process 身份和 Nacos Data ID；mTLS 协商后实际发送 `snapshot_applied`，Collector 返回持久化后才 `204`。本机 SQLite 验证两份 inbox/outbox，outbox 均为 `delivered`，current projection 记录正确的 binding、profile、process epoch 与 canonical digest。Metrics V2 同一证书身份也分别有真实已确认快照；它提供 Observation 所需的 process epoch。
- 两个 SDK profile 的等价规则规范化后得到相同 checksum `8d4bf14903161eb179b906816d5cb2152627e28133edefa7ae0e7d573d6c252c`，但 Nacos 原始 JSON digest 不同。真实 Nacos 更新 threshold 2→1 后，两服务均由 `200,200,429` 变为 `200,429,429`；故意提交 Java 未建模字段和 Go 非 1000ms 窗后，两者仍保留 threshold 1、业务请求继续限流，并各自持久化 `snapshot_failed/decode_rejected`。恢复为与 active snapshot 字节完全相同的有效配置后，真实 Observation 又产生 `snapshot_applied` 并清除失败状态。
- **实现修复：**现场发现 provider 恢复到当前已生效的同一配置时，checksum 快路径此前直接跳过，造成规则仍正确但运行时状态长期显示旧失败。Java/Go poller 现在只在先前确有刷新失败、随后成功读到当前 accepted 内容时产生恢复观察，不重复 load SDK、不为每个相同轮询生成事件；新增两语言回归测试锁定这组条件。
- **定向验证：**Java `mvn -q test` 与 Go `go test ./...`、`go vet ./...`；共享 Foundation/Java/Go fixture、Console profile/ingest/API tests 通过。实测两语言流控、更新、非法候选 LKG、恢复观察和 Collector durable outbox 均已证实。本段不是 Dashboard 内置浏览器验收，也不证明 React 规则页面/指标图表 readback。
- **保留供后续 E2E：**单节点 Console/Collector、Java demo `127.0.0.1:18092`、Go demo `127.0.0.1:18093` 与本轮命名的两个 Nacos 配置继续运行，配置恢复为合法 threshold=1。绑定和 reporter enrollment 是本机 acceptance SQL 数据；不是用户已有应用身份或生产规则。此状态保留到最终验收，不删除或清理用户现有服务。

### 3.3 Prometheus 与指标展示

**推荐：** 监控源经 Console 内部最小 `MonitoringSource/Probe` Port 和基础设施 `PrometheusHttpAdapter`，React 只访问版本化 Console API 0.11.0（检查）、0.12.0（安全读取）、0.13.0（管理命令）。首期 Linux `node-exporter-v1` 仅提供 HOST CPU busy、内存使用 bytes/ratio、1-minute load；Prometheus 只存时序，Console SQL 只存源配置、受保护的认证信息、revision、身份映射和探测回执。Prometheus 来源、Runtime Collector、Nacos/Consul 规则源彼此分离。

授权与凭证采用无认证、Basic/Bearer direct、部署侧 reference；浏览器可直接一次性录入密码但 API readback/日志/审计绝不回显。TLS 校验不关闭。source health 与 sample/profile/identity coverage 分开报告。Linux/Kubernetes 引导给出参数化模板，不从 Console 网页远程部署 exporter。图表对缺失/过期/不支持范围显示 unavailable/empty，不补零；node-exporter 容器只标 Linux VM，不冒充本机 macOS。

**不推荐：** 仅测试 Prometheus `/-/healthy` 或 `up==1` 就宣称可出图；从浏览器提交任意 PromQL；让用户把 Secret 放 URL/localStorage；把主机、容器、进程 scope 混合；将 load average 格式化为百分比；将 QPS 推断成 TPS。首期不引入 Grafana/TSDB，也不直接向数据库写规则或时序。

**2026-10-17 真实单节点查询补充：**本机 Prometheus `127.0.0.1:9090` 与 Node Exporter 已被监控 source 配置指向唯一 `HOST` identity `docker-desktop-linux-vm`（明确是 Docker Desktop Linux VM，不是 macOS）。不是只查 `/-/healthy`：使用正在运行的 Console deployment target policy、SQLite 加密监控源 registry 与生产 `ReadHostMetrics` + `PrometheusHostMetricsAdapter`，对实际配置的 source 发出固定 `node-exporter-v1` range queries。返回 quality `available`、1 个稳定 host、4 种 HOST metric（CPU busy ratio、memory used bytes/ratio、1-minute load），每种 20 个真实点；missing/stale 均不伪造为零。该命令直接调用应用读用例而非登录 HTTP API，因此仍不是 Dashboard 查询图表验收。

**API 0.11.0 实施基线（按委托采用推荐默认值）：**

- 监控源是独立 `MonitoringSource` 聚合根和内部 `MonitoringSource/Probe` Port；不复用规则 `RuleSource`、Metrics V2 Reporter 或 Nacos/Consul 注册表。Prometheus 查询全部由后端 profile 常量生成，浏览器不能传 PromQL。
- 首期 provider/profile 固定为 `prometheus-compatible` 与 `node-exporter-v1`，只声明 `HOST` scope。基础地址默认 HTTPS；HTTP 仅在管理员显式启用部署级 `allow_private_http_monitoring` 并配置私网 CIDR/端口 allowlist，且目的地址全部解析到其中时允许；该模式禁止 Basic/Bearer 凭据，只支持无认证，并在界面标出链路未加密。loopback HTTP 另限显式本机验收 profile。拒绝 URL user-info、query、fragment、重定向、非允许端口、loopback/link-local/metadata/multicast/未指定地址及私网/公网混合解析；DNS 解析结果需在单次请求中固定，不能在校验后重新解析逃逸。不得关闭 TLS 校验。唯一认证模式为无认证、Basic、Bearer、部署凭证引用；更新时用 `keep` 保留现有凭据。直接凭据与引用值只写不读，经过现有 key-ring/Secret protection 边界。
- `identityLabels` 是有序、唯一的稳定标签名列表；`selectorLabels` 仅支持有界的精确 key/value，不支持 regex、自由 PromQL 或浏览器构造表达式。host identity 是 `(monitoringSourceId, environmentId, hostId)`。缺失/冲突标签作为不可用事实返回，不猜测 `instance` 或合并重复 job 样本。
- Probe receipt 有效期固定 10 分钟，绑定当前 actor/session、非秘密候选指纹、source revision 与 profile；只存有限结果，不存 URL/凭据/标签值/原始响应。候选探测只读，不改变 Prometheus 或正式 source revision。允许保存未经探测的 source，但 readback 必须标记 `unverified`。
- list 允许 `admin`/`view` 读取有限安全摘要；详情、probe、create/update/enable/disable/delete 仅 `admin`。所有变更要求精确 Origin、CSRF、Idempotency-Key；修改/删除带 `expectedRevision`。未知写结果只能用原 request key 查询。删除若被活动监控查询引用则拒绝，不做隐式级联。
- SQL 复用既有数据库 application Port 与 SQLite/PostgreSQL/MySQL adapters，不在路由或 Prometheus adapter 内嵌方言 SQL，也不增加平行通用数据库框架。SQL 仅存 metadata、受保护凭据/引用、身份映射、revision、短期 probe receipt、命令回执和审计；time series 始终保留在 Prometheus。

**协议演进补充（本轮实现决定）：**Console API 0.11.0 冻结 candidate check + session-bound receipt；0.12.0 增加监控源安全目录与 admin 详情读取；0.13.0 增加来源管理命令与同会话回执读取。各版本分别保留不可变 OpenAPI 快照，旧版本 wire 不变。目录可由 admin/view 读取安全摘要；配置详情仅 admin，返回 endpoint origin 而不是任意路径/秘密。

**选择理由与未选方案：**保持版本快照不可变，避免让已经生成/验收的 0.11 客户端对相同 API version 收到不同 operation set；也避免为了“少一个版本号”把只读查看和副作用 mutation 混为一个含糊的请求入口。没有把 endpoint 路径暴露给浏览器，因为 Prometheus 部署路径可能含敏感信息且页面目前只需识别查询服务。后续若需路径编辑/诊断，优先提供明确、经过脱敏的 display policy，而不是直接回显整条 URL。

**选择理由与未选方案：**独立聚合根避免规则与监控的权限、生命周期和刷新语义互相污染；固定 profile 与精确标签 selector 限制 SSRF/查询成本且让单位可审计；短时 receipt 防止“检查 A、保存 B”的 TOCTOU；统一 SQL application Port 保持三种数据库一致而不绑定具体方言。Kubernetes 内部 Prometheus 常由集群私有 Service 暴露，因此既不强迫用户搭建额外 TLS 代理，也不默认开放任意明文访问：明文只对管理员显式启用且落在部署私网 CIDR/端口 allowlist 的无认证目标放行。未选任意 PromQL（范围/成本不可控）、仅健康检查即验收（不能证明 HOST profile）、复用 Collector URL（写入与查询职责不同）、永久保存探测明文（敏感数据驻留扩大）或将 Prometheus 当控制面配置仓库。

### 3.4 API/状态版本

- Console API 0.8.0 原样保持。
- 规则绑定状态与运行时规则观察仅使用已批准 additive 0.9.0 contracts；loopback-only 本机首次授权使用已批准 additive 0.10.0。
- 监控源检查使用 additive Console API 0.11.0，安全目录读取使用 0.12.0，来源管理命令使用 0.13.0；三个历史快照均不可变。严格 DTO、角色/CSRF/Origin、幂等/revision/secret policy、SQL mapping、OpenAPI 和 React wire types 一起实现并检查。它们不改变 Agent Reporting V1、Runtime Receipt V1、Metrics V2 或 PROCESS 查询语义。
- API version 进入实现/安装测试不等于批准发布；发布仍要单独签字。

### 3.5 T06.7 历史进程观察与当前态分离（推荐实现决策）

**问题：** 0.9.0 `GET /api/v2/rules/load-observations` 只从活动 Reporter enrollment 与当前 epoch 投影读取，不能展示 SQL durable inbox 中的旧 epoch。将历史事件混入现有 current endpoint 会改变旧合同对“当前在线观察”的含义，并可能让旧快照影响当前规则使用计数。

**选择：** 新增 Console API **0.16.0** 的独立认证只读 endpoint `GET /api/v2/rules/load-observation-history`。查询必须指定精确 `environmentId`、`appId`、`bindingId`，可选 `instanceId`，分页参数遵循当前严格 query policy。仅返回 durable inbox 中属于当前 epoch 之外或已撤销 Reporter 的观察事件；按 Collector `receivedAt` 倒序，再按稳定 `observationId` 排序。每条记录标 `superseded`、`revoked` 或 `no_current_epoch`；返回 safe projection（event kind、epoch、active checksum/member metadata、attempt classification、runtime observedAt、Collector receivedAt），绝不返回 principal、凭证或原始 body。历史列表与实时当前列表及 publication/receipt 历史使用独立标题和 resource owner。已撤销记录只用于审计历史，不进入 current expected/loaded 分母。

`coverage=complete,total=0` 只表示指定 binding 在当前保留的 durable inbox 中没有符合条件的历史事件；不表示没有实例、没有规则或从未加载。读取失败保持独立 error state。当前无明文历史 retention window，接口只承诺查询当前数据库仍保留的事件，不在 UI 暗示永久保留。读取权限与当前 rule observation 相同：admin/view session；服务端只读，不引入浏览器直连数据库、provider scan 或现场写入。

**选择理由：** 独立 endpoint 保持 0.9 current DTO 不变；读取既有 immutable inbox 可审计旧 process epoch，不要求新增 runtime wire、migration 或第二份事件存储；精确 binding + optional instance + bounded pagination 限制查询成本；明确历史状态防止把旧 applied 伪装成当前实例。publication receipts 仍独立证明 managed 发布，不把 native 配置伪造为 publication。

**不选方案：** 不扩展 0.9 query 加 `includeHistory`（一个 DTO 混两种状态会让 current denominator/排序和旧客户端语义变模糊）；不从 current projection 猜旧 epoch（投影只存每 principal/binding 当前行）；不只显示 latest active receipt（会丢失重启前身份）；不为每个 UI 打开周期自动拉历史（放大分页/SQL读取并无用户收益）；不新增单独 history table/outbox（durable inbox 已是来源）；不以 publication receipt 代替原生观察历史。

**定向验收矩阵：** (1) current epoch facts 不出现在 history，current endpoint/计数不变；(2) epoch 轮换后旧事件带 `superseded`，撤销后带 `revoked`，活跃 enrollment 缺 current epoch 的旧事件带 `no_current_epoch`；(3) sequence/receivedAt 逆序、重复/乱序重放后顺序稳定且无重复；(4) binding 不存在/越界/重复 query key fail closed；(5) 无历史返回 complete empty；(6) admin/view 可读、匿名拒绝；(7) 当前规则目录刷新、Nacos 重复内容读取或版本回滚不清空/重解释 durable history；(8) mounted UI 分开展示 current/history/publication，分页和空态语义正确。通过定向测试后仍只关闭 T06.7 对应子项；完整浏览器 E2E 留 T07.1。

### 3.6 managed 规则只读目录不依赖发布 allowlist（实现决策，2026-10-17）

**现象与证据：**原 Console `53205` 在进程启动时没有 `SENTINEL_CONSOLE_MANAGED_RULE_BINDING_IDS`。源码确认旧 `RegisteredRuleSetSnapshotReader` 用该启动配置门控 managed-envelope 解码；binding 是运行时登记的，静态名单无法自动包含后续 binding，因此这是一个确定的读取缺陷。但现有旧进程的 `content_invalid` 不能仅凭此事实断言全部由该缺陷导致。现场另对已登记的合成 Java Data ID `sentinel-codex-t004-java-cd9bcfa59d-flow-rules.json` 做了只读验证：认证 Nacos SDK 能读到有效 managed envelope；更新后的 `RegisteredRuleSetSnapshotReader` 通过已有 loopback TLS bridge、严格 TLS peer/hostname verification、精确 target policy 完成真实 Nacos Admin API 读取并解析为 1 条规则、带 managed version 和 provider revision。该运行使用固定测试 binding/target/resolver seam，证明真实 provider→reader 解码路径，不证明原 Console 活进程或其 SQL authority 已加载新代码。

**采用方案：**只读目录对 JSON object-shaped provider value 尝试 strict Managed Publication V1 解码，再校验精确 `binding_id`、`rule_kind`、`profile_id` 与 payload checksum；任一失败整份候选 fail closed，继续保留 last-known-good。JSON array 仍按 binding 的 native profile adapter 解析。`SENTINEL_CONSOLE_MANAGED_RULE_BINDING_IDS` 保留为发布 worker 的写入授权门禁，不再控制只读 reader 的解码能力。

**选择理由与未选方案：**读路径拥有精确 SQL binding/source/target/profile，且只对登记目标做单次只读读取，因此 envelope 自身严格校验足以判别其语义，不需要以部署时静态名单重复表达运行时元数据；这使控制台运行后新增绑定可立即读取，也避免要求重启或人工维护名单。未采用“关闭 allowlist 并宽松接受 object”，因为仍必须满足版本化 envelope 的完整校验及精确绑定匹配；未采用把所有 managed IDs 存入第二份配置中心/SQL清单，因为 binding profile/target 已是权威，不应再有第二事实源；未移除 publisher allowlist，写入授权仍需部署显式授予。未新增 GoF 模式：复用当前 provider Adapter、profile adapter 与 Managed Publication V1 decoder，只改变 Reader 内部的格式判别职责。

**验证要求：**无 allowlist 的 reader 能读取合法当前 binding envelope；错 binding/kind/profile/checksum、畸形对象拒绝；native Java/Go/Python arrays 原合同不变；Nacos/Consul 实际来源刷新正确读回；写入 worker 仍拒绝未 allowlist binding。定向现场已覆盖本轮命名的合成 Nacos target；后续还需在加载新代码的正式/隔离 Console 进程中验证真实 SQL binding/target resolution、API 投影及页面 readback，不修改其他规则。

## 4. 任务闭环顺序与门禁

| 顺序 | 闭环 | 通过证据 |
|---|---|---|
| 1 | 已实现的 T03.4/T03.5 服务端、0.9.0 查询和 SQL reader | Nacos 真实快照/外部更新/非法值 LKG；0/unknown/partial/stale 语义；SQLite/PG/MySQL targeted parity；角色与 strict API。 |
| 2 | Java Sentinel demo | 官方 SDK；无流量读取 Nacos 规则；阈值请求真实被拒；合法热更新立即改变阈值；非法配置保持最后可用规则；独立受控固定与延迟端点。 |
| 3 | Go Sentinel demo | 同 Java 语义及共享规则观察 schema 正负 fixture；不把 Go SDK 的 Prometheus exporter 事实冒充 Console durable 数据。 |
| 4 | T05.3 Prometheus source | API 0.11/0.12/0.13 auth/session/revision/secret/SSRF/error/idempotent readback；SQLite/PG/MySQL；真实 Prometheus/profile/label probe；无权限者不得写。 |
| 5 | T05.4 HOST profile | 真实 node-exporter 样本通过 adapter/API/React；半开查询窗口和 point bound；missing/stale/recovery；process metrics 回归不变。 |
| 6 | UI+源码运行一体化 E2E 验收 | 优先使用 Microsoft Edge + 仓库 CDP runner；仅当 Edge/CDP 无法启动或不能完成页面交互时，切换 Firefox + Playwright。Console 与 React 均从当前源码工作区运行；对初始化、来源/绑定/规则目录、Java/Go demo 限流及状态、Prometheus 图表、失败/空态/admin-view 工作流做端到端验证，并联查 HTTP/API、SQL、配置源、demo process、Prometheus query。Mock 浏览器全量与 live 源码运行旅程分别记录，不互相替代。此项验证程序自身，不构建/安装 wheel，也不发布到 PyPI。 |
| 7 | 留存审查环境 | 保留 Console、Demo、Prometheus/Exporter 进程与浏览器页面；保留有边界的本轮测试 source/binding 与规则快照以维持图示事实。最终交接提供停止命令和每项测试数据 ID。绝不停止或删除用户现有容器。 |

T00.5 Rust、T00.3 多节点 Kubernetes、wheel 安装与 PyPI 发布不属于本轮单节点 Java+Go+Prometheus E2E 验收；除非本轮验收设计证明它们是程序自身测试的必要条件，不扩大任务范围，也不把它们计为完成。安装包构建、安装兼容性和 PyPI 发布按独立发布清单验证。

### 4.1 本轮运行记录（2026-10-17，仍未最终验收）

> 本节保留当时的 wheel/PyPI 安装态运行记录作为历史事实，不再作为当前 E2E 验收前置条件或通过标准。当前 T07.1/T07.2 的 E2E 从源码运行验证程序；wheel 构建、安装兼容性与 PyPI 发布另按独立发布工作流执行。

- pip 安装版 Console 当前运行在 `127.0.0.1:53202`，内置浏览器 tab 3 保持在实时监控页。真实 node-exporter → Prometheus `up{job="sentinel-e2e-node-exporter"}=1`；Console 已保存 loopback Prometheus source，页面显示 `docker-desktop-linux-vm` 的 HOST CPU、内存 bytes、内存比例与 1-minute load 各 18/18 个点。查询窗口仍显示“部分样本缺失”，不将短期回填说成完整 1h 覆盖，也不把 Docker Desktop Linux VM 称为 macOS 主机。
- 同一个 pip-installed Console 的内置浏览器规则页确认：Nacos binding `t054-flow-e2e-20261017` 当前完整读取 1 条 `GET /api/hello` flow rule，阈值 3；实例使用情况明确显示“未观测”，因为 Java/Go demo 还没有以已 enrollment 的 Runtime Rule Load Observation 身份上报，不能把 `/rules` 健康端点或发出的 HTTP 请求冒充 Collector durable receipt。
- Java Demo 与 Go Demo 进程分别监听 `18081`、`18082`；当前 Nacos Data ID 已加载。`GET /health` 和 `/rules` 均成功，阈值为 3 时两服务各自 5 次连续业务请求都得到 `200, 200, 200, 429, 429`。前序记录中的合法更新与非法配置 last-known-good 验证仍需在本轮重新归档命令/当前数据版本，不能仅由该基线结果替代。
- HTTP QPS、TPS、p95、拦截率与 PROCESS CPU/内存仍显示 no-sample：Java/Go demo 当前不接 Metrics V2 Reporter，本轮 Prometheus 接入只覆盖 HOST profile。若“监控大盘所需数据全部正常展示”要求这些应用级时序也有真实样本，需先接通受 enrollment/mTLS 保护的 Metrics V2 reporter 流程，再把本项关闭；不能用示例值填图。
- 另以新建虚拟环境安装刚构建的 wheel，并在全新临时状态目录启动第二个 Console（`127.0.0.1:53203`）。该进程环境中没有 `SENTINEL_CONSOLE_BOOTSTRAP_OPERATOR_CODE`；匿名 bootstrap 返回 `setupAvailable=true, operatorAuthorized=false`，loopback-only authorize-local 成功后回读为 `operatorAuthorized=true`。内置浏览器新 tab 4 直接显示 Setup 的数据库向导，没有授权码输入步骤。该 fresh-install Console 和页面现保留以供审查，但尚未提交数据库或规则源初始化，所以不算完整首装闭环。
- 一次性 Nacos TLS bridge、Prometheus、node-exporter、原 pip-installed Console、Java/Go Demo、fresh-install Console 与内置浏览器页面均按用户要求保留运行（此为 2026-10-17 历史记录）。该记录曾把 fresh-wheel 初始化列为 T07.1 前置；按 2026-10-24 的范围决定，pip/wheel 安装不再属于 T07.1/T07.2 验收。当前仍需完成的程序功能验收以主任务清单及 B0.5 当前源码验收矩阵为准。

### 4.7 Java/Go 规则更新与 durable 实例回执复验（2026-10-17，T00.4/T07.1 仍开放）

- **真实 Nacos 更新与恢复：**只操作已登记的 Java/Go 合成 Data ID（`public / DEFAULT_GROUP`）。两个官方 Sentinel SDK 的规则阈值均现场执行 `1→2→1`：阈值 2 时固定业务端点得到 `200,200,429`；恢复阈值 1 后得到 `200,429,429`。`/rules` source/canonical digest 与更新、恢复内容相符。Go 初次编辑失败后发现未正确改变编辑器内容；该次不作为产品结论，重新确认编辑器 JSON 并完成同样的真实 provider→SDK→流控复验。
- **durable receipt 与页面：**Collector SQLite durable inbox/current projection 接收到 Java、Go 更新和恢复 `snapshot_applied`；登录后的 React Rules 页面两种应用均显示 `1` 条规则、`1/1` 实例确认加载、实例新鲜且成员清单完整，当前阈值为 `1`，与运行时和恢复后的持久回执一致。
- **验收界限：**本节只关闭“Java/Go 合法规则热更新 + 基线恢复 + 实例规则回执联查”这一切片，不据此勾选 T00.4；还要对实际运行时指标采集/API/React 图表完成联查，并执行本计划第 4 节的源码运行初始化、重启/不可重入、指标空/过期/恢复等全旅程。安装包与 PyPI 验收属于独立发布工作流，不是 T07.1 的门槛；完整浏览器 E2E 仍仅在 T07.1 关闭时执行。

### 4.2 T00.4 Java Adapter 定向切片（2026-10-17，主任务仍开放）

- **实现：**Java demo 的官方 `FlowRuleManager` 调用收进 `SentinelFlowRuleAdapter`。provider 快照先做有界 UTF-8、JSON duplicate key、Jackson unknown-field、规则类型/枚举/阈值与 cluster-mode 校验，再调用 SDK manager；空数组被视为显式清空。无效候选不更新 demo 的 active content/hash，继续使用已应用规则。`/rules` 只报告实际 manager apply 后的 count 与 provider 原始 bytes SHA-256，并明确不把它冒充 canonical rules digest 或 Collector receipt。
- **测试：**`mvn -q test`，**4/4 passed**：有效规则真实进入官方 manager；未知字段不覆盖 LKG；duplicate JSON key 和 cluster rule 被拒绝；空数组清空规则。`mvn -q package` 成功。
- **实时 SDK/provider 验收：**在已运行的 Nacos 3.2.3 上，仅创建合成随机 Data ID `sentinel-t004-java-8cc15c5a-d888-40c4-827a-bdec8fbbd9a0-flow-rules.json`。新 Java 进程 `127.0.0.1:18084` 零业务请求启动即从该 Data ID 加载 1 条官方 FlowRule；随后真实 Nacos 更新 threshold 3→2，等待 polling 后端点实测从 `200,200,200,429,429` 变为 `200,200,429,429,429`；再发布带 unknown field 的非法候选，`/rules` 中 active hash 保持 `6cd76375ace3c28a43eaa64428239bcfd5f1a3237533e3fcc45d380dff658013`，端点仍按 threshold 2 返回 `200,200,429`。这些 HTTP 请求只是验证 apply 后的官方 runtime behavior；启动前规则读取独立证明未依赖业务请求。
- **保留状态：**新 Java 进程、该隔离 Data ID（目前在 provider 中保留最后的非法候选以便 LKG 行为复查）、原 Java/Go 服务、Console、Prometheus/exporter 和 Codex IAB 均未停止。实验中的重复临时进程 `18083` 已关闭；不触碰既有规则源 Data ID。
- **未关闭边界：**本切片没有接入有效 `sentinel-java-v1` shared canonical profile、mTLS reporter enrollment/send、Rule Load Observation durable ACK、Metrics V2、Console 规则实例显示或 PROCESS/QPS/RT 图表；Go 也尚未复验同等 Adapter 行为。因此 **T00.4 不勾选**，T06.7/T07.1 继续开放。不得把该切片写成完整 Java 应用接入闭环。

### 4.3 Java Metrics V2 Reporter 定向切片（2026-10-17，T00.4 仍开放）

- **实现：**Java demo 增加独立 `MetricsV2SnapshotBuilder` 与 `MetricsV2Reporter`。Builder 在 demo HTTP 边界维护累计 HTTP 完成数、Sentinel admitted/blocked、成功业务交易数及 Metrics V2 冻结 12 边界 RT 直方图；不把 JVM heap 冒充 RSS，当前 Java 进程的 memory/RSS 明确报告 unavailable。采样与网络传输不在请求线程执行。Reporter 使用 PKCS#12 client identity + 独立 CA trust bundle 建立 mTLS；单 flight 保存精确 body bytes、epoch、sequence、SHA-256，只有 HTTP 200 且 strict receipt 六字段/identity/sequence/body digest/UTC 微秒时间全部匹配才清除；网络错误或 ACK 不匹配继续重发完全相同快照。日志只输出稳定失败分类，不输出 body、证书、URL 或异常文本。入口仅在提供 `METRICS_COLLECTOR_URL` 时启用。
- **验证：**Java `mvn -q test` 当前 **6/6 passed**（4 个真实官方 FlowRule adapter tests + 2 个 Metrics V2 snapshot semantics tests）。启动隔离 Reporter identity 并经 `sentinel-console metrics-reporter enroll` 注册到当前 pip-installed Console SQL authority；mTLS `serve-metrics` 监听 `127.0.0.1:8443`。真实 Java 实例 `127.0.0.1:18085` 零业务请求启动并从原 Nacos Data ID 成功加载 1 条规则。5 个真实 `/api/hello` 请求返回 `200,200,200,429,429`；Collector 数据库记录该 principal 的连续序号快照（观察时序号已达 58），最新快照含 HTTP completed=5、Sentinel admitted=3、blocked=2、RT histogram sample_count=5、PROCESS CPU quality=available。直接从 SQL 只读读取的最新 body 再通过 `atlas_richie.contracts.reporting.v2.decode_metrics_snapshot` 严格解码成功；未持有有效客户端证书的边界之前返回 TLS handshake 失败行为已在 Collector acceptance tests 覆盖，本轮合成空 body 的已认证请求得到 400 `invalid_protocol_version`，未获成功 ACK。
- **保留审查环境：**新增 Java Reporter demo `18085`、本轮独立 mTLS Collector `8443`、测试 CA/client identity 与日志目录位于 `/private/tmp/sentinel-java-metrics-a5Ci1W`；原 Java `18081/18084`、Go `18082`、主 Console `53202`、fresh-wheel Console `53203`、Prometheus/exporter 与现有浏览器不停止。Reporter identity 是专用合成 enrollment；不修改既有 Nacos Data ID，不包含明文 Nacos/DB 密码在本证据中。
- **未关闭边界：**本切片证明 Java Metrics V2 Reporter→mTLS Collector→durable SQLite receipt，但尚未验证 Console 实时图表/API 对该 reporter 的 process QPS/RT 展示；TPS/blocked-ratio 需按冻结 dashboard 指标定义验收。Java Rule Load Observation V1 的 shared `sentinel-java-v1` canonical profile、authenticated negotiation、durable observation ACK 与 binding-instance 页面关联未实现；Go 侧规则热更新/LKG、Metrics V2 与 Rule Load Observation 均未复验。故 **T00.4 不勾选**；T06.7/T07.1 仍开放。Reporter/Collector 使用 SQLite 仅符合本机单节点本轮路径，不代表 PostgreSQL/MySQL Metrics 方言验收。

### 4.4 Go Metrics V2 Reporter 定向切片（2026-10-17，T00.4 仍开放）

- **实现：**Go demo 新增独立本地 `metricsCapture` 与后台 `metricsReporter`：HTTP request handler 只在短 mutex 内更新 bounded cumulative counters/冻结 histogram；请求 write 失败不记入 HTTP 完成数/RT，Sentinel admission/rejection 仍按实际 entry 记录。后台 reporter 使用 Go 标准 TLS 1.2+ PEM client identity 与配置 CA，不跟随重定向；single-flight 精确保留 bytes，严格解析 receipt、拒绝 unknown fields/trailing JSON，并核对 protocol、reporter、epoch、sequence、body digest 和 UTC 六位微秒时间后才清除。缺少可信 Go process gauges 时报告 unavailable，不读取容器/host 数值冒充 PROCESS。只设置 Collector URL 时启用，配置不完整则 fail-fast。
- **验证：**`go test ./...` 通过，新增 3 项 Metrics V2 本地采样用例；实际 Go demo `127.0.0.1:18086` 零业务请求启动并从 Nacos 读取 1 条规则，5 次 HTTP 请求返回 `200,200,200,429,429`。以独立证书 fingerprint enrollment 后，经同一 mTLS Collector `127.0.0.1:8443` 收到 durable receipts；SQLite 只读查询确认最新 Go snapshot HTTP completed=5、admitted=3、blocked=2、RT histogram sample_count=5，且同一 frozen Python `decode_metrics_snapshot` 接受。Go reporter snapshot 序号持续递增，DB 最新读取时 sequence=17。
- **未关闭边界：**Go 侧真实规则 snapshot strict profile/apply/LKG 与 `/rules` 正确显示、Java/Go Rule Load Observation V1 shared profile/negotiation/durable ACK/Console 页面关联、Dashboard 对 process Metrics 的已登录 query/chart readback 尚未验证。T00.4/T06.7/T07.1 继续开放；两语言共同项仍不允许勾选 T00.4。

### 4.5 Go 官方 Sentinel FlowRule Adapter 定向切片（2026-10-17，T00.4 仍开放）

- **实现：**Go `rule_adapter.go` 只建模当前 Go demo 声明支持的直接流控 FlowRule 字段，reject 未知/重复字段、未知控制枚举、关联资源、非直接 token strategy、cluster/adaptive 等未支持语义；只在整个候选数组校验成功后调用官方 `flow.LoadRules`。有效空数组是显式清空。`/rules` 由成功 apply 后的 atomic snapshot 生成 rule count 和 exact provider bytes SHA-256；失败候选不覆盖这些活跃事实，poller 继续保留 LKG。此处 checksum 明确不是 profile canonical digest/Collector receipt。
- **验证：**`go test ./...` **6 passed**、`go vet ./...` passed；unit tests 真实检查 SDK manager rule、未知/重复/unsupported 候选保留前一条规则及 metadata、`[]` 清空。最新 Go 实例 `127.0.0.1:18087` 在无请求启动时从 Nacos 加载 1 条官方 FlowRule，`/rules` 返回 loaded/count/raw digest；5 次调用为 `200,200,200,429,429`。Metrics Reporter 仍由独立 Go 实例 `18086` 提供实时 durable sample。
- **未关闭边界：**仍缺 `sentinel-go-v1` 与 Java 对齐的 canonical/member fingerprint profile、真实 Nacos 合法更新/非法候选现场热更新/LKG、Rule Load Observation 协商和 mTLS durable ACK、Console binding/instance readback 与 Dashboard query/chart 联查。Go 真实配置只验证初始加载/拒绝效果，不宣称这些未完成项通过；T00.4 不勾选。

### 4.6 两种官方 SDK 规则解码边界收紧（2026-10-17，T00.4 仍开放）

- Java decoder 现在对 FlowRule 使用显式字段 allowlist；除 duplicate/unknown 外，即使某个属性是 Alibaba FlowRule 的已知字段，但当前 profile 未建模（例如 warm-up cold factor）也拒绝整个候选，保留 SDK active rules 与上次 metadata。
- Go decoder uses closed typed DTO + duplicate-key scan + `DisallowUnknownFields`；当前 Go profile 限定 Direct token calculation、当前资源关联策略、Reject control behavior、finite positive threshold 和 1–60,000 ms statistic interval；adaptive/warmup/associated-resource/unknown cluster semantics fail closed。合法 `[]` 才清空。每条规则/profile canonical fingerprint 尚未实现，所以当前只能报告 provider raw bytes digest；没有把它显示为 canonical digest。
- **验证：**Java `mvn -q package` 当前 **8 tests passed**（FlowRule Adapter 5 项、Metrics V2 Builder 3 项）；Go `go test ./...` **6 passed**、`go vet ./...` passed。真实 Go `18087` 用本轮 latest strict build 初次从 Nacos 拉取规则、`/rules` 反映真实 count/raw digest，五次调用仍 `200,200,200,429,429`。Java latest strict-source edit已完成 focused test/build，但正在审查的运行实例 `18085` 是先前以同一有效 Data ID 启动的 Reporter 进程；完整 Nacos update/LKG需在分开的 synthetic IDs 下重跑。
- **未关闭边界：**两 SDK 仍没有已冻结/共享验证的 canonicalization 与 member fingerprints、Rule Load Observation protocol negotiation/Collector durable ACK/Console读回；Go真实 Nacos热更新/LKG和 Java最新严格profile真实热更新/LKG仍需跑。T00.4 不关闭。

## 6. T05.3 监控源管理命令决策（API 0.13.0）

**边界与模式评估：**监控源注册表拥有 endpoint/profile/selector/auth-mode/revision/enabled 元数据和加密凭证；SQL 持久化 Adapter 拥有跨 SQLite/PostgreSQL/MySQL 的事务实现；HTTP adapter 只做严格 wire 解析、管理员/Origin/CSRF 检查与稳定回执映射；React feature 只消费版本化 HTTP contract。已评估 GoF 模式：复用既有 **Adapter** 隔离 SQLAlchemy 与 SQL 方言；采用 **Command** 封装需要幂等、审计及结果回读的 create/update/enable/disable/delete；不新增 Facade/Mediator/Observer/Strategy，因为当前调用路径只有一个同步的管理命令执行者，不存在多个独立订阅者或可选 provider 执行算法。

**已落地合同：**不可变 API 0.12.0 之上新增 additive 0.13.0：严格 `POST /api/v2/monitoring/sources/commands` 接收有界 `requestKey` 与有限 `kind`；create/update 携带来源候选、凭证更新模式以及 check receipt 或显式 `skipCheck`，update 另带 `expectedRevision`；启停使用最小 `{kind: "set-enabled", requestKey, sourceId, expectedRevision, enabled}`；delete 带 `sourceId/expectedRevision`。原操作回执由 `GET /api/v2/monitoring/sources/operations/{requestKey}` 读取，结果仅归发起的 account + session。check receipt 是 10 分钟 session-owned 回执，核对候选 fingerprint/source revision；明确跳过检查时操作回执为 `verified=false`。启停不重发 endpoint/credentials；source 变更、成功 check receipt 消费/失效、幂等 operation receipt 与 audit 原子提交。

**事务、秘密和失败策略：**来源行的新增/更新/删除、revision 变化、探测回执失效、actor-owned 幂等 operation receipt 与安全 audit 必须在同一个 SQL transaction 中原子提交；同一 request key + 同一非秘密 canonical fingerprint 返回原始回执，不重复副作用；相同 key 的不同输入返回 conflict；网络结果未知只允许读取原回执，禁止更换 key 自动重放。凭证只允许 request 内存态 + AES-GCM envelope；operation/audit/read DTO 只存或返回安全元数据、失败分类和是否配置标志，不包含明文、ciphertext 或部署引用原值。凭证 `keep/replace/clear` 是显式模式，避免空字段被误解。

**已完成的定向验证：**HTTP positive/negative（未登录、view 写、Origin/CSRF 缺失、非法 DTO、request-key 冲突、重复命令与跨 session 回读）；持久化（同 key 原结果、revision CAS、来源/check receipt/audit/operation receipt 原子行为、更新后旧 probe 失效、密钥不泄漏）；共享来源迁移及管理读写用例分别在 SQLite、一次性 PostgreSQL、一次性 MySQL 执行。该证据证明 Console source registry 管理子闭环，不证明真实 Prometheus/exporter 可连、时序图可绘制或 browser installation E2E；这些仍属于 T05.3/T05.4/T07.1。

**未选方案：**不在已冻结 0.12.0 修改 GET operation set；不将来源行和回执分两次提交（会留下无法安全重放的未知写结果）；不让浏览器直连 Prometheus 或把凭证放在 localStorage；不在当前只有一个 SQLAlchemy persistence path 时另建并行数据库 SPI/通用命令中台；不使用 source UUID 或 source name 作为幂等键，避免同一账号多标签页/跨 session 误读回执；不把 enable/disable 建成重发整份来源配置的独立操作，以免不必要地重交秘密或覆盖并发编辑。

## 5. 测试矩阵与安全清理

| 风险 | 核心断言 | 层级 |
|---|---|---|
| 源码运行误导入已安装旧版本 | 启动时确认 Python 模块来自当前源码工作区，React API 代理指向本轮 Console，浏览器未启用 MSW/live fallback | process + HTTP + browser |
| 首装/重启和重复初始化 | locator 持久、管理员能登录、setup 关闭、密码/凭据不出现在文件权限外或日志 | SQL + HTTP + IAB |
| Nacos 规则被误当成 Runtime 已加载 | 首次读取、0 targets、expected/unknown/partial、实际 reporter event 分开断言 | Nacos + SQL + API + IAB |
| Java/Go demo 未真正执行 SDK | 每个 demo HTTP 请求通过真实 Sentinel entry，触发原 SDK 规则的 blocked result；变更后通过/拒绝边界变化 | provider + SDK + HTTP |
| Prometheus 健康但无有效 host profile | query API、metric families、唯一映射 host、真实点数分开断言 | Prometheus adapter + SQL + IAB |
| 时序/重复 host/空值语义错误 | `[from,to)`、最大点、重复身份、缺样本、stale、恢复严格断言，缺值不为 0 | adapter + integration |
| 凭证外泄/SSRF | 无凭证 GET/operation/audit；credential replace/keep/direct；本地目标必须显式测试允许；无重定向旁路、有限超时/响应量 | API + SQL + logs |
| E2E 临时状态 | 数据库临时路径/容器明确 owner label；Nacos 仅精确随机 Data ID；服务需保留时将其标成审查状态，不执行 cleanup | integration + handoff |

每个任务关闭时在唯一进度清单增加一条含时间、commit/worktree、命令、通过数和证据范围的记录；实际 E2E 全部通过之前不得将 T07.1 标记完成。本轮如果遇到官方 SDK 与 Nacos 3 真实不兼容，不将其降格为 xfail；必须解决 adapter 支持边界并再次验证。任何未完成的产品依赖如证书/endpoint policy 无法在本地安全验证，明确留项和原因，不伪造完成结论。

### 7. 本轮 fresh-wheel 首装复验（2026-10-17，T07.1 未关闭）

- **免码路径：**使用隔离 virtualenv 中安装的 Console wheel，服务仅绑定 `127.0.0.1:53203`，进程未设置 operator code。首次从 `http://127.0.0.1:53203/#/setup` 打开时出现授权码表单；核对发现安装配置允许的 Browser Origin 是 `http://localhost:53203`，两种 hostname 不相同，因此本机授权按精确 Origin 安全规则拒绝。改用配置内的 `http://localhost:53203/#/setup` 后，页面自动完成本机授权并直接进入数据库配置，授权码输入步骤消失；对 `/api/v1/system/bootstrap/authorize-local` 的 loopback 请求在精确 `Origin`、CSRF proof 和空请求体下返回 `200 {"authorized":true}`。根因是测试 URL 与允许的 Origin 不一致，不是普通 pip 安装必须提供授权码。
- **当前现场位置：**修正 Origin 后，选择 SQLite 并执行 UI 的只读数据库连接检查，页面显示“连接可达；这不代表已初始化或配置已保存”；再进入“创建内置管理员”步骤。当前停在管理员密码与确认密码字段之前，没有输入/提交凭证，也没有运行初始化命令。此前在错误 Origin 下的授权码页不能作为正确 setup UX 的验收结论。
- **先前 SQLite 只读探测：**单独的定向验证曾使用隔离路径 `/private/tmp/sentinel-no-code-wheel-dkyyt26q/console.db`；缺失文件首次检查失败，在隔离目录中预建空 SQLite 文件后检查通过。只读检查不自动建库；这不代表当前 fresh-wheel 页面已完成该操作。
- **测试：**`uv run --extra test pytest -q tests/test_first_run_deployment_configuration.py tests/test_bootstrap_authorization_file_authority.py tests/test_bootstrap_database_connector.py tests/test_first_run_composition.py`：**59 passed**。这是安装前置配置/授权/数据库 adapter/composition 的定向回归，不替代 setup 提交、账号登录、setup 关闭、Nacos 规则来源登记与应用加载等 live E2E。
- **安全边界：**未输入或提交管理员密码；本轮现场仅签发短期本机 setup grant。未修改用户已有 Console/数据库，也未在报告或文档保存任何密码。
