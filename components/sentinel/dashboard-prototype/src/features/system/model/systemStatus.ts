/**
 * 系统管理的领域类型、协议常量与纯规则。
 *
 * 中文
 * ----
 * 本模块只回答「系统管理这页有哪些只读事实、它们属于哪一类」，不依赖 React、
 * 语言包或网络。读模型的字段对应 `REWRITE_PLAN.md` §4.6：连接状态、权限声明、
 * 协议边界与版本状态；展示组件只负责把这些结论渲染成 `styles.css` 已有的 class。
 *
 * 旧实现（`SystemPage` 单文件 205 行）的问题：
 *
 * - tab 状态、连接表格数据、权限文案、审计链、协议说明和版本清单全部塞在一个组件里，
 *   改一处要在 200 行内定位，页面既管导航状态又管业务事实。
 * - 「连接是否可用对应哪个状态色」写成了组件体内的三元表达式，规则没有名字、
 *   也没有第二个消费者可以复用，只能靠渲染结果验证。
 * - tab 标签是散落的字符串字面量，tab 顺序和标签值混在 JSX 的 `.map` 里。
 *
 * 这里把三件事分开：协议常量与稳定 id（本文件）、随环境变化的读模型
 * （`fixtures/`，接后端后由 `system.gateway` 提供）、UI 导航状态（`SystemPage`）。
 */

/**
 * 连接类别。
 *
 * 中文
 * ----
 * 这是 `DASHBOARD_CONTROL_PLANE.md` §2/§4.2 的链路分类：配置中心、指标后端、
 * 上报采集器三条链路各自独立健康，任何一条断开都不代表其余两条不可用。
 * 分类值只用于读模型自身，页面文案由 UI 层决定。
 */
export const CONNECTION_KIND = Object.freeze({
  ConfigCenter: "config-center",
  MetricsBackend: "metrics-backend",
  ReportingCollector: "reporting-collector",
} as const);

/** {@link CONNECTION_KIND} 的值联合。 */
export type ConnectionKind = (typeof CONNECTION_KIND)[keyof typeof CONNECTION_KIND];

/** 连接可用时的状态文案。判定状态色时用它，避免散落字面量。 */
export const CONNECTION_AVAILABLE_STATE = "可用";

/**
 * 一条连接状态。
 *
 * 中文
 * ----
 * - `state` 是**探测结果**，`latency` / `scope` 是同一时刻的观察值；
 *   `purpose` 与 `capability` 说明这条链路能做什么、做不到什么——
 *   「未连接真实 Collector」是能力边界，不能被渲染成「健康」。
 * - 单元格的 `latency` / `scope` 保留展示形态（`"12 ms"`、`"3 个应用"`）：
 *   Console API 返回的是 `latencyMs` 与已上报实例数，映射发生在 gateway 层，
 *   model 不做二次拼装。
 */
export interface ConnectionStatus {
  readonly kind: ConnectionKind;
  /** 展示名，同时作为表格行的稳定 key。 */
  readonly name: string;
  readonly state: string;
  readonly latency: string;
  readonly scope: string;
  readonly purpose: string;
  readonly capability: string;
}

/**
 * 连接状态 → 状态色。
 *
 * 中文
 * ----
 * 旧实现写的是 `item.state === "可用" ? "healthy" : "blue"`，规则只存在于 JSX 里。
 * 这里是它唯一的归属：未连通的链路用 `blue`（中性提示），不是 `critical`——
 * 原型阶段「未接入」是产品事实，不是故障。
 */
export function connectionStatusTone(state: string): "healthy" | "blue" {
  return state === CONNECTION_AVAILABLE_STATE ? "healthy" : "blue";
}

/** 连接表格的列头。集中在 model，避免 JSX 里写一串无名字符串。 */
export const CONNECTION_HEADERS: readonly string[] = Object.freeze([
  "组件",
  "状态",
  "延迟",
  "覆盖",
  "用途",
  "能力边界",
]);

/** 「连接与采集」顶部四个概览数字。 */
export interface ConnectionSummaryCard {
  readonly label: string;
  readonly value: string;
  /** 缺省为空串，与 `NumberCard` 的默认值一致。 */
  readonly unit?: string;
  readonly note: string;
  /** 缺省为空串；非空时作为 `NumberCard` 的语义 class。 */
  readonly tone?: string;
}

/**
 * 页面 tab 的稳定标识。
 *
 * 中文
 * ----
 * 值是**协议 id**（会进 URL query），不是展示文案。旧实现用中文标签同时充当状态值
 * 与展示文本，改一次文案就会让已分享的链接失效——与时间范围曾经的
 * `"最近 1 小时"` 是同一类错误，这里不再重复。
 *
 * 标签由 {@link SYSTEM_TAB_LABEL} 提供；接入 `core/i18n` 后改为语言键，id 不变，
 * 深链因此长期有效。顺序即渲染顺序，调整会改变首屏按钮排列。
 */
export const SYSTEM_TAB = Object.freeze({
  Connections: "connections",
  Permissions: "permissions",
  Protocol: "protocol",
  Accounts: "accounts",
  Roles: "roles",
} as const);

/** {@link SYSTEM_TAB} 的值联合。 */
export type SystemTab = (typeof SYSTEM_TAB)[keyof typeof SYSTEM_TAB];

/**
 * tab 展示文案。
 *
 * 键与 {@link SYSTEM_TAB} 一一对应；缺一个键即类型错误。文本与旧实现逐字相同，
 * 因此渲染结果不变。
 */
export const SYSTEM_TAB_LABEL: Readonly<Record<SystemTab, string>> = Object.freeze({
  [SYSTEM_TAB.Connections]: "连接与采集",
  [SYSTEM_TAB.Permissions]: "权限与审计",
  [SYSTEM_TAB.Protocol]: "协议与版本",
  [SYSTEM_TAB.Accounts]: "账户维护",
  [SYSTEM_TAB.Roles]: "角色绑定",
});

/** tab 渲染顺序。首屏默认停在 {@link SYSTEM_TAB.Connections}。 */
export const SYSTEM_TABS: readonly SystemTab[] = Object.freeze([
  SYSTEM_TAB.Connections,
  SYSTEM_TAB.Permissions,
  SYSTEM_TAB.Protocol,
  SYSTEM_TAB.Accounts,
  SYSTEM_TAB.Roles,
]);

/** 首屏默认 tab。 */
export const DEFAULT_SYSTEM_TAB: SystemTab = SYSTEM_TAB.Connections;

/**
 * 把 URL 里的 `view` 解析成受控 tab。
 *
 * 中文
 * ----
 * 合法值集合属于本 feature，因此校验放在这里而不是路由边界——`app/router` 不应该
 * 知道某个页面有几个 tab。非法或缺失一律回落默认 tab，绝不「就近猜一个」：
 * 猜错会让用户以为自己在看某个分区。
 */
export function resolveSystemTab(value: string | undefined): SystemTab {
  return (SYSTEM_TABS as readonly string[]).includes(value ?? "")
    ? (value as SystemTab)
    : DEFAULT_SYSTEM_TAB;
}

/** 控制台只判断的两项能力（`DASHBOARD_CONTROL_PLANE.md` §2）。 */
export const CAPABILITY = Object.freeze({
  MetricsView: "metrics:view",
  RulesWrite: "rules:write",
} as const);

/** {@link CAPABILITY} 的值联合。 */
export type Capability = (typeof CAPABILITY)[keyof typeof CAPABILITY];

/** 最小权限模型里的一条角色说明。 */
export interface PermissionDeclaration {
  /** 稳定 id，同时是面板选择图标的键。 */
  readonly id: "viewer" | "rule-maintainer";
  readonly title: string;
  /** 该角色被授予的能力标识。 */
  readonly capability: Capability;
  readonly description: string;
  /** 展示用状态标签的语义 tone。 */
  readonly tone: "blue" | "warning";
  /** 展示用状态标签文案（「只读」/「可变更」）。 */
  readonly statusLabel: string;
}

/**
 * 权限声明。
 *
 * 中文
 * ----
 * 首版不引入 Viewer/Editor/Approver 角色层级，也不做多租户 RBAC；这里只有两条
 * 声明，用于回答「谁能看到指标、谁能改规则」。角色 id 与能力是**协议事实**，
 * 接入 `core/session` 后由会话能力列表校验，界面隐藏按钮不是安全边界。
 *
 * 两条声明是**按 id 命名的单条常量**而不是数组：权限面板必须把身份入口排在
 * 两条声明之间，数组只能靠下标取元素，反而把渲染顺序写进数据里。
 */
export const VIEWER_PERMISSION: PermissionDeclaration = Object.freeze({
  id: "viewer",
  title: "观察者",
  capability: CAPABILITY.MetricsView,
  description: "可查看总览、应用实例、实时指标、故障事件与规则详情。",
  tone: "blue",
  statusLabel: "只读",
});

export const RULE_MAINTAINER_PERMISSION: PermissionDeclaration = Object.freeze({
  id: "rule-maintainer",
  title: "规则维护者",
  capability: CAPABILITY.RulesWrite,
  description: "可提交规则变更；生产流程仍需基准版本校验与审计。",
  tone: "warning",
  statusLabel: "可变更",
});

/** 发布审计链的一步。原型不产生真实记录，只声明链路顺序。 */
export interface AuditChainStep {
  readonly step: string;
  readonly title: string;
  readonly detail: string;
}

/**
 * 发布审计链。
 *
 * 中文
 * ----
 * 四步对应 `DASHBOARD_CONTROL_PLANE.md` §4.3 的发布合同，**不能合并**：
 * 「本地草稿已验证」「配置中心写入成功」「回读一致」「实例已生效」是四条独立事实，
 * 前一步永远不能被当作后一步的结论。
 */
export const AUDIT_CHAIN_STEPS: readonly AuditChainStep[] = Object.freeze([
  { step: "01", title: "编辑并校验", detail: "schema、阈值、影响范围" },
  { step: "02", title: "生成差异", detail: "基准版本、操作者、理由" },
  { step: "03", title: "条件写回", detail: "Nacos / Consul 成功确认" },
  { step: "04", title: "观察生效", detail: "各实例版本与失败项" },
]);

/** 协议边界的稳定 id，同时是面板选择图标的键。 */
export type ProtocolBoundaryId = "rule-config" | "agent-reporting" | "cluster-token";

/**
 * 一条协议边界说明。
 *
 * 中文
 * ----
 * 只有两个字段：协议名与它负责的事。`REWRITE_PLAN.md` §4.6 还列了
 * `independence`，但当前面板并不展示该维度，**不提前加入未渲染的字段**——
 * 接入 Console API、面板真要显示独立面时再补。
 */
export interface ProtocolBoundary {
  /** 稳定 id，同时是面板选择图标的键。 */
  readonly id: ProtocolBoundaryId;
  readonly name: string;
  /** 这条协议负责什么。 */
  readonly role: string;
}

/**
 * 协议边界。
 *
 * 中文
 * ----
 * 控制面与观测面独立演进：规则写入、实例上报、配额决策分属不同协议，
 * 任何一方故障都不应被解释成另一方不可用。这三条是**产品边界声明**，
 * 不随部署环境变化，因此属于 model 常量而不是读模型。
 */
export const PROTOCOL_BOUNDARIES: readonly ProtocolBoundary[] = Object.freeze([
  {
    id: "rule-config",
    name: "规则配置",
    role: "Nacos / Consul 为权威规则源；Dashboard 通过管理服务写入。",
  },
  {
    id: "agent-reporting",
    name: "Agent Reporting",
    role: "上报实例版本、健康与事件，不参与准入决策。",
  },
  {
    id: "cluster-token",
    name: "Cluster Token",
    role: "负责配额决策，与规则编辑和事件上报分离。",
  },
]);

/** 版本与状态面板的一行。 */
export interface DeliveryStatusItem {
  readonly label: string;
  readonly value: string;
}

/**
 * 交付形态的版本与状态。
 *
 * 中文
 * ----
 * 这一组值描述的是**本交付物走到了哪一步**，不是对部署环境的探测结果，所以放在
 * model 而不是读模型。接入 Console API 后，「配置中心写回 / 真实指标数据 /
 * 实时事件」三项会变成 gateway 返回的探测值；「界面状态」仍是产品自身的事实。
 */
export const DELIVERY_STATUS_ITEMS: readonly DeliveryStatusItem[] = Object.freeze([
  { label: "界面状态", value: "设计原型" },
  { label: "配置中心写回", value: "未实现" },
  { label: "真实指标数据", value: "未连接" },
  { label: "实时事件", value: "未连接" },
]);
