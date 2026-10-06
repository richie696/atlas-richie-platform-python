# Dashboard 原型改写方案（框架接入 + 数据契约 + 改造清单）

> 状态：方向已定（React 最终实现 + 独立控制台 Console API），改造按 §8 分阶段执行中。
> 日期：2026-10-05。
> 依据：`richie696-react-library@1.0.1` 源码 + `REACT_CODING_STANDARD` / `REACT_PROJECT_SKELETON` /
> `RICHIE_FOUNDATION_USAGE` / `modern-react-ui-design` / `react-coding-standard`，
> 以及 `docs/DASHBOARD_CONTROL_PLANE.md`、`sentinel-dashboard` 现有 JSON API。
>
> 本文只描述改写任务与契约草案，不构成发布签字。

---

## 1. 框架库功能清单

仓库 `richie696-react-library` 当前为 `1.0.1`，已拆为 5 个独立发布包。基础包不依赖
React / 路由器 / UI 库。

### 1.1 `@richie696/react-framework`（协议与基础能力，21 个模块）

| 模块 | 公开符号 | 用途 |
| --- | --- | --- |
| `foundation/types` | `HttpMethod`、`ApiResult<T>`、`Page<T>`、`RequestOptions`、`HttpClientConfig`、`I18nDictionary` | 请求契约、响应信封、分页元数据 |
| `foundation/url` | **`Url`**、`UrlOptions`、`UrlCatalog`、`defineUrl`、`defineUrlCatalog` | 不可变端点描述符：路径模板、方法、加密/防重标志 |
| `foundation/errors` | `AppError`、`AppErrorKind`（10 类）、`AppErrorDetails` | 统一错误归一化，保留 status/code/requestId/traceId/retryAfter |
| `foundation/headers` | `ManagedHeadersStore` | 白名单响应头缓存（带 TTL），敏感头永不自动保存 |
| `foundation/duplicate` | `DuplicateRequestGuard` | 时间窗内重复提交抑制 |
| `foundation/crypto` | `EccCryptoSession` | Web Crypto ECDH P-256 / AES-GCM 请求加密与重握手 |
| `foundation/identity` | `DeviceIdentity` | 稳定设备 ID |
| `foundation/storage` | `StorageAdapter`、`BrowserStorage`、`MemoryStorage` | 可注入存储，SSR 默认内存实现 |
| `foundation/concurrency` | 转发 concurrency 包 | — |
| `localization/i18n` | `Translator`、`TranslationValues` | 字典 + 回退 locale + 命名插值 |
| `reactive/state-store` | `StateStore`、`ReadonlyStore`、`Equality` | 不可变快照外部 store（BehaviorSubject + distinctUntilChanged） |
| `reactive/resource` | `ObservableResource`、`ResourceSnapshot`、`ResourceStatus`、`ResourceLoader` | 一次异步资源的 idle/loading/success/error/cancel 生命周期，带代次防过期覆盖 |
| `reactive/polling` | `PollingStore`、`PollingOptions`、`PollingLoader` | 周期刷新，`exhaustMap` 防重叠，有界重试，保留 last-known-good |
| `reactive/time-series` | `TimeSeriesStore`、`TimeSeriesPoint` | 有界不可变时间窗口（默认 300 点） |
| `reactive/events` | `EventBus<Events>`、`EventStream` | 类型化发布/订阅，handler 异常隔离，不暴露 RxJS 类型 |
| `transport/http` | `HttpClient`、`GatewayClient`、拦截器类型、`StreamOptions` | 请求编排：重试/取消/超时/401/防重/加密/SSE |
| `transport/sse` | `parseEventStream`、`ServerSentEventMessage` | SSE 多帧解析（AsyncGenerator） |

### 1.2 `@richie696/react-framework-react`（React 19 绑定）

`ReactFrameworkProvider`、`useReactFramework`、`FrameworkEventName`（`unauthorized` /
`ruleUpdated` / `connectionChanged`）、`FrameworkEvents`、`useHttpClient`、`useRequest`、
`useObservableResource`、`useExternalSnapshot`、`useEvent`、`useOnlineStatus`。

### 1.3 三个可选扩展包

- `@richie696/react-framework-concurrency`：`AsyncMutex`、`ReentrantLock`、`ReadWriteLock`、
  `StampedLock`、`Condition`、`SingleFlight`、`LockOwner`（仅同 runtime 协作式，不是跨 Worker 锁）。
- `@richie696/react-framework-security`：`sha256Hex`、`HmacSha256Signer`、
  `RsaPssSha256Signer` / `Verifier`（仅密码学原语，不定义 HTTP 签名协议）。
- `@richie696/react-framework-browser-fingerprint`：`BrowserHardwareFingerprintCollector`、
  `SignedHardwareFingerprintProvider`（SSR 不可用，需显式启用并自行承担告知同意）。

### 1.4 关键 HTTP 契约（决定 API 层设计）

- `request<T>()` 返回 `ApiResult<T>`（`success` / `data` / `code` / `message` / `requestId`），
  另有 `requestData<T>()` 只取 `data`。
- `Url` 声明方法、路径参数、重复提交保护与加密意图；**GET 的对象参数自动转 query，
  数组参数填充 `{placeholder}`**。
- GET/HEAD/OPTIONS 默认重试 `maxRetries` 次；POST/PUT/PATCH/DELETE **只有显式
  `idempotencyKey` 才允许重试**。408/425/429/5xx/网络/超时走有界指数退避 + `Retry-After`。
- 401 自动清理受管凭证并触发 `onUnauthorized`。
- `requestStream<T>()` 返回 SSE `AsyncGenerator`，支持 `kind=done` / `kind=error` 控制帧。

---

## 2. 版本落差与引入缺口

### 2.1 版本问题（必须先修）

`package.json` 锁 `@richie696/react-framework@0.1.0` + `-react@0.1.0`，而 **npmjs 公共源上
只有 `1.0.0` / `1.0.1`**。`0.1.0` 来自 `.npmrc` 里的私有源
`@richie696:registry=https://npm.cnb.cool/...`。

已核对：0.1.0 与 1.0.1 源码中 `Url`、`ObservableResource`、`PollingStore`、
`TimeSeriesStore` 的签名完全一致，升级是安全的。

**动作**：升级到 `1.0.1`、删除 `.npmrc` 中的 `@richie696` scope 私有源、删除 `cachetools`
式的无谓锁定。同时 `1.0.1` 的 `framework` 会传递引入 `concurrency` 与 `security` 两个包。

### 2.2 实际只用了 2 个符号

`main.tsx` 用了 `ReactFrameworkProvider`，`app/App.tsx` 用了 `useOnlineStatus`。
其余能力**全部未引入**。下表按 dashboard 的真实需求排序。

| 框架能力 | 现状 | 应替换的现有实现 | 优先级 |
| --- | --- | --- | --- |
| `Url` + `defineUrlCatalog` | 未用 | 无 URL 抽象，API 层不存在 | **P0** |
| `HttpClient` / `useHttpClient` | 未用 | 无请求层 | **P0** |
| `AppError` / `AppErrorKind` | 未用 | 无任何错误处理与状态区分 | **P0** |
| `ApiResult<T>` 信封 | 未用 | 无响应契约 | **P0** |
| `PollingStore` + `useExternalSnapshot` | 未用 | `RealtimePage` 用 `setInterval` + `frame` 计数假回放 | **P0** |
| `TimeSeriesStore` + `useExternalSnapshot` | 未用 | `FLEET_TREND` 冻结数组 + `makeTrendSeries` 造数据 | **P0** |
| `HttpClient.requestStream` / `parseEventStream` | 未用 | 无；后端 `/sse/metrics` 已存在 | **P0** |
| `Page<T>` 分页元数据 | 未用 | 应用/实例/事件全为假数组 | P1 |
| `Url.needDuplicateCheck` | 未用 | 规则发布无防重，违反 Sentinel 幂等要求 | **P0** |
| `ObservableResource` + `useObservableResource` | 未用 | 故障/系统页一次性加载无取消 | P1 |
| `Translator` + `I18nDictionary` | 未用 | `ruleI18n.ts` 648 行手写三语 | P1 |
| `StorageAdapter` / `BrowserStorage` | 未用 | locale / 时间范围无持久化 | P1 |
| `StateStore` + `useExternalSnapshot` | 未用 | `appId` / `range` / `locale` 在 `App.tsx` 逐层 props 传 | P1 |
| `EventBus<Events>` | 未用 | 无类型化事实通道 | P1 |
| `useRequest` | 未用 | 无一次性动作层（重载规则、重置熔断、建账号） | P1 |
| `SingleFlight`（concurrency） | 未用 | 多组件同资源重复加载 | P2 |
| `sha256Hex`（security） | 未用 | 规则版本 `checksum` 是假字符串 | P2 |
| `SignedHardwareFingerprintProvider` | 未用 | — | P2（需隐私决策，**默认不启用**） |

### 2.3 明确不该引入

- `concurrency` 的各类锁：浏览器单页没有跨 Worker 临界区需求。仅为「防重复加载」时
  `SingleFlight` 一个足够。
- `browser-fingerprint`：涉及设备指纹与用户同意，运维控制台没有明确合规需求。
  `HttpClient.sendHardwareFingerprint` 保持默认 `false`。
- `Url.needEncryption`：控制面走内网 + Bearer/Cookie 会话，浏览器端加密没有服务端契约。
  服务端契约明确前不启用。
- `HmacSha256Signer`：浏览器端共享密钥不是秘密，不能替代服务端授权。

---

## 3. 现有结构与目标结构对照

### 3.1 改造前现状（历史快照）

> 以下清单记录的是 **2026-10-05 改造开始前**的状态，用于对照本方案做了什么。
> 阶段 0 与阶段 2 已完成，当前实际结构见
> [React 原型职责对照](REACT_REFACTOR_MAP.md)。
> 仍未开始的部分（样式分层、Console API 层、会话、i18n 分层）见该文件「尚未开始的工作」。

```text
src/
├── main.tsx                  27 行   Provider 装配（Astryx 在此层）
├── App.tsx                    2 行   兼容导出
├── app/App.tsx              120 行   路由 + 全局状态 + 六页条件渲染（过载）
├── app/shell/AppShell.tsx    24 行
├── app/router/hashRoute.ts   24 行   11 条路由白名单
├── app/providers/AstryxProvider.tsx
├── demoData.ts              529 行   全应用假数据 + 造数函数（跨 feature 共享）
├── ruleI18n.ts              648 行   手写三语
├── styles.css             2107 行   全局选择器
├── features/{overview,applications,rules,realtime,faults,system,identity}/ui/*.tsx
├── shared/ui/*.tsx                  14 个 Astryx 适配器 + charts/TrendChart
├── shared/types/dashboard.ts
└── legacy/LegacyDashboard.tsx
```

缺失：`core/` 整个目录、`*.module.scss`（0 个）、任何 `api/` 目录、任何 store、i18n locale 目录。

### 3.2 目标结构（按 `REACT_PROJECT_SKELETON`）

```text
src/
├── main.tsx                          # 只做挂载 + 唯一全局样式导入
├── app/
│   ├── App.tsx                       # Provider + 路由 + shell 组合，无业务
│   ├── providers/
│   │   ├── FrameworkProviders.tsx    # ReactFrameworkProvider（options 稳定）
│   │   └── AstryxProvider.tsx
│   ├── router/
│   │   ├── routes.ts                 # 路由表：path ↔ lazy 页面 + 权限适配
│   │   ├── route.constants.ts        # 路由静态地址唯一来源（见 §5）
│   │   ├── hashRoute.ts              # 解析/序列化 + 白名单校验
│   │   └── navigation.ts             # navigate 命令（应用编排层）
│   └── shell/AppShell.tsx + .module.scss
├── core/
│   ├── api/
│   │   ├── httpClient.ts             # HttpClient 单例配置（baseUrl/超时/401）
│   │   └── errorMapping.ts           # AppError → 可翻译文案 + 恢复动作
│   ├── i18n/
│   │   ├── locales/{zh-CN,en-US,ja-JP}.ts
│   │   └── translator.ts             # 基于框架 Translator
│   ├── session/                      # 登录态、权限（metrics:view / rules:write）
│   ├── config/                       # 已验证的运行时配置
│   └── styles/
│       ├── index.scss                # 唯一全局入口
│       ├── _reset.scss
│       ├── themes/{_dark,_light}.scss
│       └── tokens/{_structure,_mixins}.scss
├── shared/
│   ├── ui/*.tsx + *.module.scss      # 保留 Astryx 适配层，改为 CSS Modules
│   ├── format/                       # Intl 数字/时间/百分比
│   └── types/
└── features/<name>/
    ├── api/
    │   ├── <name>.endpoints.ts       # Url + defineUrlCatalog
    │   ├── <name>.dto.ts             # 线上请求/应答形状
    │   ├── <name>.gateway.ts         # 发请求 + DTO→model 映射 + 错误归一化
    │   └── <name>.mapper.ts          # DTO ↔ model 纯转换
    ├── model/                        # 领域类型、枚举、纯校验
    ├── state/                        # store + use*.ts 订阅 Hook
    ├── ui/*Page.tsx + *.module.scss
    ├── i18n/
    └── fixtures/                     # 显式演示数据，生产不导入
```

---

## 4. 逐页数据结构

以下每页的字段清单来自现有页面实际渲染的单元格、图表和卡片，
`DASHBOARD_CONTROL_PLANE.md` §3.1 的口径要求（`scope` / `source` / 单位 / 窗口 / 新鲜度）
已作为必填并入。

### 4.1 总览 `overview`

| 数据结构 | 关键字段 |
| --- | --- |
| `FleetAttention` | `attentionCount`、`totalApps`、`focusedAppIds[]`、`summary` |
| `InfraStatus` | `component`（nacos/consul/reporting）、`state`、`latencyMs`、`scopeText`、`capability` |
| `RuleDeliveryCoverage` | `appliedInstances`、`totalInstances`、`coveragePercent`、`version` |
| `FleetTrendSeries` | `points: MetricPoint[]`、`window`、`annotations: Annotation[]`（发布时点） |
| `MetricPoint` | `at`、`httpQps`、`blockedRate`、`blockedCount`、`rtP95Ms`（无可聚合 histogram 时为 `null`）、`cpuUsageRatio`（0..1）、`source`、`scope` |
| `ApplicationSummary` | `id`、`name`、`health`、`healthReason`、`runningInstances`、`totalInstances`、`cpuAvgRatio`、`memoryAvgRatio`、`httpQps`、`rtP95Ms`、`blockedRatePercent`、`ruleVersion`、`sourceKind` |
| `ApplicationList` | `Page<ApplicationSummary>` |

**硬约束（来自 §3.1，必须落到类型里）**：TPS 字段在未接入业务事务埋点前为 `null` 而非 0；
`rtP95Ms` 在无 histogram 时为 `null`，不得由累计 `avg_rt_ns` 做差伪造。

### 4.2 应用与实例 `applications`

| 数据结构 | 关键字段 |
| --- | --- |
| `InstanceCatalog` | `items: InstanceRecord[]`、`hosts: HostGroup[]`、`coverage: Coverage` |
| `InstanceRecord` | `id`、`host`、`containerId`、`processPid`、`status`、`statusReason`、`cpuUsageRatio`、`memoryUsedBytes`、`memoryLimitBytes`、`httpQps`、`rtP95Ms`、`blockedRatePercent`、`ruleVersion`、`lastReportAt`、`scope` |
| `HostGroup` | `host`、`instances[]` |
| `InstanceScopeSeries` | `points[]`、`scope`（host/container/process）、`scopeSupported`（未接入时为 `false`） |
| `InstanceProtectionSummary` | `flowThresholds[]`、`degradeThresholds[]` |

**硬约束**：宿主机/进程层未接入时 `scopeSupported=false`，UI 显示「未接入」，
不得复用容器曲线。

### 4.3 规则 `rules`

| 数据结构 | 关键字段 |
| --- | --- |
| `RuleBinding` | `appId`、`environment`、`ruleType`、`sourceKind`（nacos/consul）、`configKey`、`activeVersionId` |
| `RuleRecord` | `id`、`ruleType`、`resource`、`sentinelRule`（五类兼容字段之一）、`baseVersionId`、`scope`、`status` |
| `RuleDraftValidation` | `schemaErrors[]`、`semanticErrors[]`（含字段路径）、`isPublishable` |
| `RuleDiff` | `fromVersionId`、`toVersionId`、`operations[{op, path, before, after}]` |
| `PublishState` | `validated` / `configCenterWritten` / `readbackConsistent` / `instanceApplied{n,m}` —— **四个独立状态，不得合并** |
| `RuleVersion` | `versionId`、`baseVersionId`、`name`、`checksum`、`createdBy`、`createdAt`、`note`、`ruleCount`、`state`（active/scheduled/superseded） |
| `ActivationPlan` | `planId`、`activateAt`、`deactivateAt?`、`restoreVersionId`、`ianaTimeZone`、`state`、`blockedReason?` |

**兼容字段**（§4.3，逐字对应 Sentinel profile）：FlowRule `resource/limitApp/grade/count/
strategy/controlBehavior/clusterMode` + 条件 `refResource/warmUpPeriodSec/maxQueueingTimeMs/clusterConfig`；
DegradeRule `resource/grade/count/timeWindow/minRequestAmount/statIntervalMs` + `slowRatioThreshold`；
SystemRule `highestSystemLoad/avgRt/maxThread/qps/highestCpuUsage`（`-1` 表示未启用，CPU 为 0..1）；
AuthorityRule `resource/limitApp/strategy`；ParamFlowRule `resource/grade/count/durationInSec/
paramIdx/paramFlowItemList[{classType,object,count}]`。

### 4.4 实时监控 `realtime`

| 数据结构 | 关键字段 |
| --- | --- |
| `RealtimeSummary` | `httpQps`、`rtP95Ms`、`blockedRatePercent`、`cpuAvgRatio`，每项带 `unit` / `window` / `scope` / `source` / `asOf` |
| `RealtimeSeriesBundle` | `qps[]`、`rt[]`、`blocked[]`、`resource[]`，共用 `window` 与 `annotations[]` |
| `MetricSeries` | `points: MetricPoint[]`、`unit`、`source`、`scope`、`freshnessSeconds` |
| `StreamStatus` | `mode`（live/replay/static）、`paused`、`lastFrameAt`、`samplerInstalled` |

**硬约束**：未接入实时后端时 `mode='static'` 且 UI 必须标注「示例回放」，
现有 `setInterval` 假回放要换成 `TimeSeriesStore` 有界窗口。

### 4.5 故障分析 `faults`

| 数据结构 | 关键字段 |
| --- | --- |
| `IncidentList` | `Page<IncidentEvent>`（按 `at` 倒序） |
| `IncidentEvent` | `id`、`at`（含时区）、`severity`（critical/warning/info）、`category`（resource/rt/ruleChange）、`appId`、`instanceId?`、`title`、`observedFacts[]`、`suggestedActions[]` |
| `IncidentEvidence` | `relatedMetrics: MetricSeries`、`relatedRuleVersionId?`、`causality`（固定为 `unknown`，不自动断言） |

数据来源：Agent Reporting 事件（V1 已冻结 6 个 `event_kind`）+ 控制面发布审计。

### 4.6 系统管理 `system`

| 数据结构 | 关键字段 |
| --- | --- |
| `ConnectionStatus` | `kind`（config-center/metrics-backend/reporting-collector）、`name`、`state`、`latencyMs`、`coverageText`、`purpose`、`capabilityBoundary` |
| `PermissionDeclaration` | `capabilities: ['metrics:view','rules:write']`、`granted[]`、`deniedReason?` |
| `AuditChain` | `entries: AuditEntry[]`（`op`、`actor`、`at`、`target`、`result`） |
| `ProtocolBoundary` | `name`、`role`、`independence` |
| `VersionStatus` | `uiState`、`configCenterWriteback`、`liveMetrics`、`liveEvents` |

**硬约束**：连接凭证不在本页写入，走部署配置（§2）。

### 4.7 身份与初始化 `identity`（5 路由）

| 数据结构 | 关键字段 |
| --- | --- |
| `AccountSummary` | `id`、`username`、`roleId`、`status`、`builtIn`、`lastLoginAt`（**无密码哈希/重置令牌**） |
| `AccountDraft` | `username`、`password`（write-only，提交后从状态清除）、`roleId` |
| `IdentityRole` | `id`、`permissions[]`（只含两项能力） |
| `SetupStatus` | `initialized`、`currentStep`、`available` |
| `SetupDatabase` | `kind`（postgresql/mysql/sqlite）、`label`、`defaultPort`、`requiresNetworkConfiguration`、`usage` |
| `SetupRuleSource` | `kind`（nacos/consul）、`endpoint`、`namespace/group/dataId` 或 `key`、`authMode`、`credential?`（write-only） |
| `SessionState` | `authenticated`、`accountId`、`capabilities[]`、`expiresAt` |

**硬约束**：setup 是服务端治理的一次性窗口 —— 初始化成功后服务端关闭该窗口、
重复访问拒绝、客户端把 `#/setup` 深链重定向到 `#/login`、setup 无「返回登录」、login 无 setup 入口。

---

## 5. 路由静态地址管理类

**现状问题**：路由标识散在三处 —— `app/router/hashRoute.ts` 的 `DASHBOARD_ROUTES`、
`demoData.ts` 的 `PAGE_ITEMS`，以及 `App.tsx` 里 12 处裸字符串
（`navigate("applications")`、`page === "rules"` …）。`PAGE_ITEMS` 还用**数组下标绑定图标**
（`NAV_ICONS[index]`），新增或重排导航就会静默错位。

**目标**：单一来源 + 编译期校验 + 无魔法字符串。

```ts
// src/app/router/route.constants.ts
export const ROUTE = Object.freeze({
  Overview: "overview",
  Applications: "applications",
  Rules: "rules",
  Realtime: "realtime",
  Faults: "faults",
  System: "system",
  Accounts: "accounts",
  Roles: "roles",
  ChangePassword: "change-password",
  Login: "login",
  Setup: "setup",
} as const);

export type RouteId = (typeof ROUTE)[keyof typeof ROUTE];

/** 导航项自带 icon，不再靠下标对齐。 */
export interface NavigationEntry {
  readonly id: RouteId;
  readonly path: string;          // "#/overview"
  readonly icon: IconComponent;  // 显式绑定
  readonly order: number;
  readonly requires: "none" | "session" | "setup";
  readonly i18nKey: string;       // 标签来自语言包，不写死中文
}

export const NAVIGATION = Object.freeze([...]) satisfies readonly NavigationEntry[];
```

配套三个纯函数（`app/router/hashRoute.ts`）：`pathFor(routeId, params?)`、
`routeFromPath(path): RouteId`（白名单校验，未命中回落 `Overview`）、
`serializeNavigationContext({appId, range})` / `parseNavigationContext()`。

**规则**：查询上下文（`appId` / 时间范围 / 选中实例）按 §3.2「可分享的导航状态进 URL」
放路径查询参数，不再靠 `App.tsx` 的 props 逐层下传。

---

## 6. 服务端 API 契约草案

### 6.1 端点集中管理（用框架 `Url`）

```ts
// src/features/overview/api/overview.endpoints.ts
import { HttpMethod, defineUrlCatalog } from "@richie696/react-framework";

export const OverviewEndpoint = defineUrlCatalog({
  /** GET 的对象参数由 HttpClient 自动转 query。 */
  applications: { path: "/api/v1/applications", method: HttpMethod.GET },
  trend: { path: "/api/v1/metrics/fleet-trend", method: HttpMethod.GET },
  infra: { path: "/api/v1/system/connections", method: HttpMethod.GET },
});
```

规则发布端点必须开防重：

```ts
export const RuleEndpoint = defineUrlCatalog({
  list:   { path: "/api/v1/rules", method: HttpMethod.GET },
  publish: {
    path: "/api/v1/rulesets/{bindingId}/versions",
    method: HttpMethod.POST,
    needDuplicateCheck: true,   // 框架 DuplicateRequestGuard
  },
});
```

> 框架的 `Url.resolve()` 支持 `{placeholder}` 位置参数与 `options.query`，
> **JSX 与页面里不允许出现任何字符串路径**。

### 6.2 统一响应信封

所有端点返回框架 `ApiResult<T>`：`{ success, data, code, message, requestId, timestamp }`。
列表类 `data` 内含 `Page<T>`（`current` / `pages` / `size` / `total` / `records`）。

### 6.3 端点清单

| # | 方法 | 路径 | 请求体 | 应答 `data` | 能力 |
| --- | --- | --- | --- | --- | --- |
| 1 | GET | `/api/v1/session` | — | `SessionState` | 任意 |
| 2 | POST | `/api/v1/session` | `{username, password}` | `SessionState` | 任意 |
| 3 | DELETE | `/api/v1/session` | — | `null` | 任意 |
| 4 | POST | `/api/v1/session/password` | `{currentPassword, newPassword}` | `null` | 任意 |
| 5 | GET | `/api/v1/setup/status` | — | `SetupStatus` | 任意 |
| 6 | POST | `/api/v1/setup` | `{database, admin, ruleSource}` | `SetupStatus` | 仅未初始化 |
| 7 | GET | `/api/v1/applications` | query: `env,scope,window,page,size` | `Page<ApplicationSummary>` | `metrics:view` |
| 8 | GET | `/api/v1/applications/{appId}/instances` | query: `scope,statusFilter,page,size` | `InstanceCatalog` | `metrics:view` |
| 9 | GET | `/api/v1/instances/{instanceId}/series` | query: `scope,window,from,to` | `MetricSeries` | `metrics:view` |
| 10 | GET | `/api/v1/metrics/fleet-trend` | query: `env,appId?,window,metrics` | `FleetTrendSeries` | `metrics:view` |
| 11 | GET | `/api/v1/metrics/realtime-summary` | query: `appId,window` | `RealtimeSummary` | `metrics:view` |
| 12 | GET | `/api/v1/metrics/stream` (SSE) | query: `appId,scope` | 逐帧 `MetricPoint` | `metrics:view` |
| 13 | GET | `/api/v1/rulesets` | query: `appId,env,ruleType` | `Page<RuleBinding>` | 任意 |
| 14 | GET | `/api/v1/rulesets/{bindingId}/snapshot` | — | `RuleSnapshotDto` | 任意 |
| 15 | POST | `/api/v1/rulesets/{bindingId}/validate` | `RuleSnapshotDto` | `RuleDraftValidation` | `rules:write` |
| 16 | GET | `/api/v1/rulesets/{bindingId}/diff` | query: `from,to` | `RuleDiff` | 任意 |
| 17 | POST | `/api/v1/rulesets/{bindingId}/versions` | `{snapshot, baseVersionId, note, idempotencyKey}` | `PublishState` | `rules:write` |
| 18 | GET | `/api/v1/rulesets/{bindingId}/versions` | — | `Page<RuleVersion>` | 任意 |
| 19 | POST | `/api/v1/rulesets/{bindingId}/activation-plans` | `{versionId, activateAt, deactivateAt?, restoreVersionId, timeZone}` | `ActivationPlan` | `rules:write` |
| 20 | GET | `/api/v1/incidents` | query: `appId,severity,from,to,page,size` | `Page<IncidentEvent>` | `metrics:view` |
| 21 | GET | `/api/v1/incidents/{incidentId}` | — | `IncidentEvidence` | `metrics:view` |
| 22 | GET | `/api/v1/system/connections` | — | `ConnectionStatus[]` | 任意 |
| 23 | GET | `/api/v1/system/permissions` | — | `PermissionDeclaration` | 任意 |
| 24 | GET | `/api/v1/system/audit` | query: `from,to,page,size` | `Page<AuditEntry>` | `rules:write` |
| 25 | GET | `/api/v1/accounts` | query: `page,size` | `Page<AccountSummary>` | `rules:write` |
| 26 | POST | `/api/v1/accounts` | `AccountDraft` | `AccountSummary` | `rules:write` |
| 27 | PATCH | `/api/v1/accounts/{accountId}` | `{status?, roleId?}` | `AccountSummary` | `rules:write` |
| 28 | GET | `/api/v1/roles` | — | `IdentityRole[]` | 任意 |
| 29 | PUT | `/api/v1/accounts/{accountId}/roles` | `{roleId}` | `AccountSummary` | `rules:write` |

**POST 全部要求客户端携带 `idempotencyKey`**（框架 `RequestOptions.idempotencyKey`），
否则框架按设计**不重试**写操作；规则发布与计划创建同时开 `needDuplicateCheck`。

### 6.4 错误契约

统一用框架 `AppError` + `AppErrorKind` 映射到 UI 状态，**不把原始响应体或堆栈透给页面**：

| `AppErrorKind` | 触发 | UI 表现 |
| --- | --- | --- |
| `unauthorized` | 401 | 跳登录，清 `href` 到原路径 |
| `forbidden` | 403 缺能力 | 该区域「无权限」态，不请求图表 |
| `rate-limited` | 429 | 显示 `retryAfterMs` 倒计时 |
| `protocol` | 5xx / 信封损坏 | 「服务异常」+ requestId |
| `cancelled` | 取消/切筛选 | 静默，不弹错 |
| `network` / `timeout` | 断网/超时 | 区分于「无数据」 |

### 6.5 实时流

后端 `sentinel-dashboard` 已有 `GET /sse/metrics`（每 5s `event: metrics` + JSON）。
控制面侧对应 12 号端点。前端用 `http.requestStream(url, undefined, { parseData })`，
每帧写入 `TimeSeriesStore`（有界 300 点），组件用 `useExternalSnapshot` 订阅。
`samplerInstalled=false` 时 `StreamStatus.mode='static'`，UI 标注「示例回放」——
**禁止用定时器伪造回放冒充实时**。

---

## 7. 方向决策（已定，2026-10-05）

### 7.1 技术方向：React 为最终实现

**决策**：React 19 是 Console 的最终实现方向，按生产级 API 层建设。

原 `DASHBOARD_CONTROL_PLANE.md` §4.5 声明「正式 Web 实现为 Angular 22 的 `dashboard-web/`，
React 原型不属于生产交付物」，该声明已废止并改写。废止原因：`components/sentinel/dashboard-web`
从未创建，Angular 实现不存在，而本原型是当前唯一存在的前端工程；保留一个没有实现基础的框架
声明会让「React 只是原型」与「React 是产品」两种相反预期同时留在文档里。

配套：Angular Material/CDK 不再是依赖选型；PrimeNG 仍是禁止依赖项；
`DASHBOARD_CONTROL_PLANE.md` §4.5 已同步改写。

### 7.2 后端目标：独立控制台 Console API

**决策**：契约对齐独立控制台 Console API，不对齐 M6.6 per-process `sentinel-dashboard`。

- §6.3 的 29 个端点为正式契约基线，覆盖 §4.2 的完整控制台任务。
- 现有 `sentinel-dashboard`（Starlette，loopback + Bearer admin token）**降级为只读诊断视图**，
  其 6 个 JSON + 2 个 admin + 1 个 SSE 端点不并入 Console 契约；
  两者是不同的观察范围与鉴权边界，不互相冒充（§1、§2）。
- 代价：Console API 服务端尚未实现，需新建 Python 管理服务；前端在后端就绪前
  用 `fixtures/` + 契约测试推进，不宣称联调通过。


---

## 8. 改造清单（按依赖顺序）

### 阶段 0：地基（不改行为，可独立验收）

> **进度（2026-10-05）**：0.1、0.3、0.4 已完成并通过浏览器实测；0.2 未开始。

| # | 任务 | 状态 | 验收证据 |
| --- | --- | --- | --- |
| 0.1 | 升级框架到 1.0.1，删 `.npmrc` 私有 scope | ✅ | 公共源解析 4 包（framework / react / concurrency / security），`typecheck` 0 错、`build` 通过、`test:sites` 4/4 |
| 0.2 | 建 `core/styles/`（index/reset/themes/tokens），迁 `styles.css` 根变量 | ⬜ | 首屏无主题闪烁，深色基线不变 |
| 0.3 | 建 `app/router/route.constants.ts`，消除全部路由魔法字符串与下标绑图标 | ✅ | 路由魔法字符串 0 处；图标改为 `Record<MainNavRouteId, Icon>` 编译期穷尽；11 路由 + 时间窗口协议值集中 |
| 0.4 | `app/App.tsx` 瘦身：路由映射表 + shell 组合，URL 承载筛选上下文 | ✅ | 页面 props 收敛为 `DashboardPageProps`；`?app&range&account` 可分享，刷新/深链恢复；浏览器实测 0 console error |

**0.3/0.4 顺带修掉的既有问题**：

- 导航图标由 `NAV_ICONS[index]` 下标对齐改为按 `RouteId` 显式绑定（增删/重排不再静默错位）。
- `shell.navigation` 由位置数组改为 `shell.nav.*` 键控对象，11 条路由 + 时间窗口标签全部有 i18n 键。
- 时间范围状态由中文字面量（`"最近 15 分钟"`）改为协议值 `15m` / `1h`，标签走语言资源。
  切到 English 后标签为 "Last 1 hour" 而 URL 仍为 `range=1h`（已浏览器实测）。
- 路由静态表新增 `appFilter`（`fleet` / `single`）元数据，收敛原先藏在 `onNav` 里的第二份事实来源；
  `single` 路由不接受「全部应用」，导航与深链接**两条入口**都做收敛。
- `MetricPoint` 契约类型统一到 `shared/types/dashboard.ts`，删除 `TrendChart` 的
  `Record<string, string|number>` 索引签名副本；`metric` 改为 `MetricKey` 字面量联合。
- `Select` 适配层泛型化，`onChange` 直接传出协议值类型。
- `demoData` 移除已成死代码的 `PAGE_ITEMS` / `TIME_RANGES`，补 `TrendPoint` 与
  `numberText` 的参数类型。
- `SystemPage` 越过 feature 边界直接 import `features/identity` 的问题**尚未修**，
  属阶段 2.7 顺带项（identity 需要先建立显式公共入口）。

**已知未覆盖**：六页正文文案仍是硬编码中文（本次只迁移了 shell 导航、筛选项、
时间范围、实时监控指标筛选、总览趋势副标题）。`AGENTS.md` 已声明
「在六页所有用户可见文本完成迁移前，不得宣传为全控制台语言覆盖已完成」，
阶段 1.3 负责收口。

### 阶段 1：核心服务层

| # | 任务 | 产物 | 验收 |
| --- | --- | --- | --- |
| 1.1 | `core/api/httpClient.ts`：`HttpClient` 单例（`baseUrl`/`timeout`/`onUnauthorized`） | 单例 + Provider options 稳定 | 401 清理受管头并跳登录 |
| 1.2 | `core/api/errorMapping.ts`：`AppError` → i18n 文案 + 恢复动作 | 映射表 | 10 个 kind 全覆盖 |
| 1.3 | `core/i18n/`：`Translator` + 三语 locale 资源 | 翻译层 | 缺键回落 `zh-CN`，不回退协议键 |
| 1.4 | `core/session/`：会话与两项能力（`metrics:view` / `rules:write`） | session store | 无权限区域不请求图表 |

### 阶段 2：逐 feature 迁移（一次一条完整用户路径）

每个 feature 内部顺序固定：**`model`（协议常量 / 判别联合 / 强类型 i18n 契约 / 纯策略）
→ `state`（状态机 hook）→ `ui`（页面容器 + 私有面板 + 按类型拆分的子组件）→
`fixtures`（演示数据）→ 删除对 `demoData` 的引用**。

#### 验证方法：渲染等价而非肉眼比对

「重新实现但不影响展示效果」必须有可复现的证据，不能靠「看着差不多」。本工程的视觉
完全由 `styles.css` 的全局 class 驱动，因此**归一化 DOM 相等可以证明「这次改动没动到
渲染结构」**。但它**不能证明「当前渲染是对的」** —— DOM 可以在完全不变的前提下渲染成
错的。所以工具同时比较**整页 PNG**，两个信号分开报告。

`tests/visual/capture-baseline.mjs` 用系统 Chrome headless（零新增依赖）实现：

```bash
# 捕获基线
node tests/visual/capture-baseline.mjs capture <outDir>
# 与基线比对，退出码非 0 即存在差异
node tests/visual/capture-baseline.mjs compare <baseDir> <newDir>
# 只校验指定用例（并行重建时必需）
ONLY=realtime,faults node tests/visual/capture-baseline.mjs capture <outDir>
# 刻意修复布局缺陷时，声明接受该用例的渲染变化
ACCEPT_RENDER=faults node tests/visual/capture-baseline.mjs compare <baseDir> <newDir>
```

- 覆盖 16 个用例：11 条路由 + 时间窗口 / 单应用 vs 全部应用 / 15m vs 1h 等筛选组合。
  只覆盖路由本身会漏掉「切语言后时间范围标签失配」这类回归。
- 归一化只抹掉与展示**无关**的渲染期噪声：Vite HMR 脚本、Astryx 每次渲染重生成的
  `data-backend-node-id`、Nivo/SVG 随机实例 id。stylex 生成的 `x…` class 名**保留**，
  因为它们决定实际样式。
- Chrome headless 截图存在跨进程的抗锯齿抖动（实测同页两次捕获最多 89 像素 / 0.0077% /
  最大通道差 44），因此**渲染比对用容差像素 diff 而非文件摘要**。默认阈值
  `TOLERANCE_RATIO=0.0005`、`TOLERANCE_MAX_DELTA=80`（约为抖动上限的 6 倍与 1.8 倍），
  任一超限判为回归。PNG 解码用 Node 内置 zlib 自实现（`tests/visual/png-diff.mjs`），
  保持零新增依赖。
- 并行重建时用 `ONLY` 过滤，避免把其他 feature 的中间态算作回归。

**工具抓到的真实缺陷（2026-10-05）**：故障分析页事件时间线一直是坏的，而且**是两处叠加**——
① 事件内容被压进 `.event` 四列 grid 的 12px 首列逐字换行；② 解除①之后小标题仍溢出到行的
下方，因为 Astryx `md` 尺寸按钮带固定高度 `height: var(--size-element-md)`（实测按钮 35px、
内容盒 42px，溢出 24px）。两处根因都在 Astryx `Button`：它把 children 包在两层 span 里
（外层 `display:contents`，**内层是真实盒子**），并按尺寸锁定高度。修复是两条纯 CSS
（`.event > span > span { display: contents }` + `.event:not(#\#)×5 { height: auto }`），
DOM 未变、像素改变。工具为此新增了「DOM 等价但渲染不同」这一独立信号，并要求
`ACCEPT_RENDER` 显式声明才放行；基线 PNG 也已重新基线化。

> 教训：DOM 等价只能证明「没有改变」，不能证明「本来就对」。基线本身也可能是坏的，
> 所以基线必须偶尔被人眼看一遍，DOM 与像素双重比对不能取代这一步。

#### 进度（2026-10-05）

| Feature | 状态 | DOM 等价 |
| --- | --- | --- |
| `rules` | ✅ 已重建 | 16/16 全量等价 |
| `identity` | 🔄 进行中 | — |
| `applications` | 🔄 进行中 | — |
| `system` + `overview` | 🔄 进行中 | — |
| `realtime` + `faults` | 🔄 进行中 | — |

`rules` 重建带来的实际收益（可作为其他 feature 的验收基准）：

- 删掉 `RuleDraft = Record<string, any>`，改为五类规则的判别联合 + `RuleDraftMap`，
  收窄集中到单一 `narrowDraft()`。TypeScript 随即暴露了 14 处此前被 `any` 掩盖的
  无类型字段访问。
- `RuleEditor` 从 520 行 if/else 链拆成类型分发器 + 5 个独立表单组件 + 3 个字段包装。
- 校验从「接收 `t` 函数并产出已翻译字符串」改为返回结构化 `{key, path, params}`，
  领域判断不再绑定界面语言。
- 目录筛选、版本计划、草稿状态机各有单一所有者；`cloneRule` 从 JSON 往返改为
  `structuredClone`。
- 演示数据从跨 feature 的 `src/demoData.ts` 迁到 `features/rules/fixtures/`。



### 阶段 3：样式与视觉

| # | 任务 | 验收 |
| --- | --- | --- |
| 3.1 | 全量 `*.module.scss` 迁移，逐页从 `styles.css` 删对应选择器 | 2107 行全局 CSS 归零 |
| 3.2 | 图表 theme adapter 统一读 CSS token（`core/styles` 语义变量） | 切主题时图表同步 |
| 3.3 | 每页补齐 loading / empty / denied / error / stale / partial 态 | 六页 × 6 态 |
| 3.4 | 键盘操作、焦点顺序、`prefers-reduced-motion`、窄屏重排 | 浏览器核对 |

### 阶段 4：门禁

`typecheck`（已存在）、**新增 Hooks lint**、构建、feature 契约测试、
六页 × 6 态截图核对、浏览器实测（不能只凭 build 通过宣称验收）。

---

## 9. 顺带发现的存量问题

1. `ruleTypes.ts:2` 的 `RuleDraft = Record<string, any> & {...}` 直接违反
   `REACT_CODING_STANDARD` §1「避免 `any`」。五类规则应有判别联合类型。
2. `cloneRule()` 用 `JSON.parse(JSON.stringify())` 深拷贝，丢 `undefined`、对
   `Date`/非 JSON 值不安全；应改为显式 mapper。
3. `demoData.ts` 的 `numberText` 未标注参数类型（`value` 隐式 `any`），
   且项目 `tsconfig` 设了 `noImplicitAny: false` —— 建议打开。
4. `App.tsx` 的 `identityAccountId` 状态只服务于「记住上次看的账号」，
   按 URL 状态规则应进查询参数。
5. `SystemPage` 直接 `import` 了 `features/identity/ui/IdentityPages` ——
   违反「一个 feature 不导入另一个 feature」。应走 `app/router` 或 identity 的显式公共入口。
6. `AGENTS.md` 要求保留 `worker/index.js` / `scripts/prepare-sites-build.mjs` /
   `tests/sites-worker.test.mjs`，Sites 交接门禁依赖它们，迁移时不要删。
