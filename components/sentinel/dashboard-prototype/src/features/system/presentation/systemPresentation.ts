/** Presentation metadata owned by this feature; never part of a wire/domain contract. */
import {
  CAPABILITY,
  CONNECTION_STATE,
  SYSTEM_TAB,
  type Capability,
  type ConnectionKind,
  type ConnectionState,
  type SystemTab,
  type ProtocolBoundaryId,
} from "../model/systemStatus";
import type { TranslationKey } from "../../../shared/types/translation";

/** 连接状态的展示文案键。 */
export const CONNECTION_STATE_LABEL_KEY: Readonly<Record<ConnectionState, TranslationKey>> =
  Object.freeze({
    [CONNECTION_STATE.Available]: "system.connection.state.available",
    [CONNECTION_STATE.Demo]: "system.connection.state.demo",
  } as const);

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
  /** 探测结果。枚举值，渲染时按 `CONNECTION_STATE_LABEL_KEY` 取译文。 */
  readonly state: ConnectionState;
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
export function connectionStatusTone(state: ConnectionState): "healthy" | "blue" {
  return state === CONNECTION_STATE.Available ? "healthy" : "blue";
}

/** 连接表格的列头（语言键）。集中在 model，避免 JSX 里写一串无名字符串。 */
export const CONNECTION_HEADERS: readonly TranslationKey[] = Object.freeze([
  "system.connection.head.component",
  "system.connection.head.state",
  "system.connection.head.latency",
  "system.connection.head.coverage",
  "system.connection.head.purpose",
  "system.connection.head.capability",
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
 * tab 展示文案的**键**。
 *
 * `Accounts` / `Roles` 指向的就是壳层导航里的那两个页面，壳层已有
 * `shell.nav.accounts` / `shell.nav.roles`，这里直接复用——同一个词两处定义时，
 * 改一处不会提示另一处已经对不上。
 */
export const SYSTEM_TAB_LABEL_KEY: Readonly<Record<SystemTab, TranslationKey>> = Object.freeze({
  [SYSTEM_TAB.Connections]: "system.tab.connections",
  [SYSTEM_TAB.Permissions]: "system.tab.permissions",
  [SYSTEM_TAB.Protocol]: "system.tab.protocol",
  [SYSTEM_TAB.Audit]: "system.tab.audit",
  [SYSTEM_TAB.Accounts]: "shell.nav.accounts",
  [SYSTEM_TAB.Roles]: "shell.nav.roles",
  [SYSTEM_TAB.Settings]: "system.tab.settings",
});

/** 最小权限模型里的一条角色说明。 */
export interface PermissionDeclaration {
  /** 稳定 id，同时是面板选择图标的键。 */
  readonly id: "viewer" | "rule-maintainer";
  /** 该角色被授予的能力标识（协议值，不翻译）。 */
  readonly capability: Capability;
  /** 展示用状态标签的语义 tone。 */
  readonly tone: "blue" | "warning";
  /** 展示用状态标签的**键**。 */
  readonly statusLabelKey: TranslationKey;
  /** 标题与说明的语言键。 */
  readonly titleKey: TranslationKey;
  readonly descriptionKey: TranslationKey;
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
  titleKey: "system.permissions.viewer.title",
  capability: CAPABILITY.MetricsView,
  descriptionKey: "system.permissions.viewer.description",
  tone: "blue",
  statusLabelKey: "system.permissions.viewer.status",
});

export const RULE_MAINTAINER_PERMISSION: PermissionDeclaration = Object.freeze({
  id: "rule-maintainer",
  titleKey: "system.permissions.maintainer.title",
  capability: CAPABILITY.RulesWrite,
  descriptionKey: "system.permissions.maintainer.description",
  tone: "warning",
  statusLabelKey: "system.permissions.maintainer.status",
});

/** 发布审计链的一步。原型不产生真实记录，只声明链路顺序。 */
export interface AuditChainStep {
  /** 步骤序号（协议值，非文案）。 */
  readonly step: string;
  /** 标题与说明的语言键。 */
  readonly titleKey: TranslationKey;
  readonly detailKey: TranslationKey;
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
  {
    step: "01",
    titleKey: "system.permissions.audit.step1.title",
    detailKey: "system.permissions.audit.step1.detail",
  },
  {
    step: "02",
    titleKey: "system.permissions.audit.step2.title",
    detailKey: "system.permissions.audit.step2.detail",
  },
  {
    step: "03",
    titleKey: "system.permissions.audit.step3.title",
    detailKey: "system.permissions.audit.step3.detail",
  },
  {
    step: "04",
    titleKey: "system.permissions.audit.step4.title",
    detailKey: "system.permissions.audit.step4.detail",
  },
]);

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
  /**
   * 协议展示名的语言键。
   *
   * 三条都用键而不是「一半数据一半文案」：`Agent Reporting` 与 `Cluster Token`
   * 在中文里本来就是英文，借用 zh 译文免去在三种语言里各写一遍；等真的需要
   * 「用中文解释这个协议叫什么」时再加一个独立的 `displayName`。
   */
  readonly nameKey: TranslationKey;
  /** 这条协议负责什么的语言键。 */
  readonly roleKey: TranslationKey;
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
    nameKey: "system.protocol.ruleConfig.name",
    roleKey: "system.protocol.ruleConfig.role",
  },
  {
    id: "agent-reporting",
    nameKey: "system.protocol.agentReporting.name",
    roleKey: "system.protocol.agentReporting.role",
  },
  {
    id: "cluster-token",
    nameKey: "system.protocol.clusterToken.name",
    roleKey: "system.protocol.clusterToken.role",
  },
]);

/** 版本与状态面板的一行。 */
export interface DeliveryStatusItem {
  /** 标签与取值的语言键。 */
  readonly labelKey: TranslationKey;
  readonly valueKey: TranslationKey;
  /** 稳定 id，作为 `key` 用——标签会随语言变化，不能拿它当 key。 */
  readonly id: string;
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
  {
    id: "ui-state",
    labelKey: "system.protocol.delivery.uiState.label",
    valueKey: "system.protocol.delivery.uiState.value",
  },
  {
    id: "config-writeback",
    labelKey: "system.protocol.delivery.configWriteback.label",
    valueKey: "system.protocol.delivery.configWriteback.value",
  },
  {
    id: "real-metrics",
    labelKey: "system.protocol.delivery.realMetrics.label",
    valueKey: "system.protocol.delivery.realMetrics.value",
  },
  {
    id: "live-events",
    labelKey: "system.protocol.delivery.liveEvents.label",
    valueKey: "system.protocol.delivery.liveEvents.value",
  },
]);
