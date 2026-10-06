/**
 * 系统管理页的文案。
 *
 * 中文
 * ----
 * 归属本 feature。这一页的特殊之处是：**大部分文案原本在 `model/systemStatus.ts`**。
 *
 * 角色声明（title / description / statusLabel）、审计链步骤（title / detail）、
 * 协议边界（name / role）、交付状态对（label / value）都是产品常量，
 * 它们用中文写死，于是永远不跟随语言切换。全部搬到这里，model 里改存语言键。
 *
 * ## 两个 tab 标签复用 `shell.nav.*`
 *
 * `SYSTEM_TAB.Accounts` / `Roles` 的标签（「账户维护」「角色绑定」）与壳层导航
 * 指向同一页面。壳层已有 `shell.nav.accounts` / `shell.nav.roles`，这里直接复用，
 * 不另建一份——同一个词两处定义，改一处不会提示另一处已经对不上。
 * 「连接与采集」「权限与审计」「协议与版本」是本 feature 独有的，新建 `system.tab.*`。
 *
 * ## 连接状态：判定不再依赖文案
 *
 * 原本 `connectionStatusTone(state)` 写的是 `state === "可用"`，即**用展示文案做
 * 判定**。翻译一次就会让所有链路变成中性蓝，而这种失效没有任何测试能发现。
 * 现在 `state` 是协议枚举，判定基于枚举值，译文在 `system.connection.state.*`。
 */
import type { LocaleBundle } from "../../../core/i18n/types";

export const SYSTEM_COPY = {
  "zh-CN": {
    "system.intro.title": "系统管理",
    "system.intro.description":
      "检查配置中心、指标采集和事件上报边界，保持运维权限简单明确。",
    "system.intro.aside": "演示环境 · 无凭证操作",
    "system.intro.tabGroupLabel": "系统管理分类",

    "system.tab.connections": "连接与采集",
    "system.tab.permissions": "权限与审计",
    "system.tab.protocol": "协议与版本",

    "system.connection.title": "连接与能力状态",
    "system.connection.subtitle":
      "配置中心读写、指标与事件上报是不同链路；下列状态均为示例。",
    "system.connection.head.component": "组件",
    "system.connection.head.state": "状态",
    "system.connection.head.latency": "延迟",
    "system.connection.head.coverage": "覆盖",
    "system.connection.head.purpose": "用途",
    "system.connection.head.capability": "能力边界",
    "system.connection.state.available": "可用",
    "system.connection.state.demo": "演示模式",
    "system.connection.note":
      "真正的 Nacos / Consul 健康检查、条件写入和回滚能力需由独立管理服务实现。",
    "system.connection.action.openRules": "查看规则工作台",

    "system.permissions.grantHint":
      "授予方式：在「账户维护」创建账号，再在「角色绑定」为它指定角色。界面隐藏不是安全边界，服务端会在每次写操作时独立校验。",
    "system.permissions.title": "最小权限模型",
    "system.permissions.subtitle": "只区分查看与修改规则，不引入多租户 RBAC。",
    "system.permissions.viewer.title": "观察者",
    "system.permissions.viewer.description":
      "可查看总览、应用实例、实时指标、故障事件与规则详情。",
    "system.permissions.viewer.status": "只读",
    "system.permissions.maintainer.title": "规则维护者",
    "system.permissions.maintainer.description":
      "可提交规则变更；生产流程仍需基准版本校验与审计。",
    "system.permissions.maintainer.status": "可变更",
    "system.permissions.auditTitle": "发布审计链",
    "system.permissions.auditSubtitle": "本原型不产生真实发布记录。",
    "system.permissions.audit.step1.title": "编辑并校验",
    "system.permissions.audit.step1.detail": "schema、阈值、影响范围",
    "system.permissions.audit.step2.title": "生成差异",
    "system.permissions.audit.step2.detail": "基准版本、操作者、理由",
    "system.permissions.audit.step3.title": "条件写回",
    "system.permissions.audit.step3.detail": "Nacos / Consul 成功确认",
    "system.permissions.audit.step4.title": "观察生效",
    "system.permissions.audit.step4.detail": "各实例版本与失败项",

    "system.protocol.boundaryTitle": "协议边界",
    "system.protocol.boundarySubtitle": "控制面与观测面独立演进。",
    "system.protocol.ruleConfig.name": "规则配置",
    "system.protocol.ruleConfig.role":
      "Nacos / Consul 为权威规则源；Dashboard 通过管理服务写入。",
    "system.protocol.agentReporting.name": "Agent Reporting",
    "system.protocol.agentReporting.role":
      "上报实例版本、健康与事件，不参与准入决策。",
    "system.protocol.clusterToken.name": "Cluster Token",
    "system.protocol.clusterToken.role":
      "负责配额决策，与规则编辑和事件上报分离。",
    "system.protocol.deliveryTitle": "版本与状态",
    "system.protocol.deliverySubtitle": "示例值不代表部署环境现状。",
    "system.protocol.delivery.uiState.label": "界面状态",
    "system.protocol.delivery.uiState.value": "设计原型",
    "system.protocol.delivery.configWriteback.label": "配置中心写回",
    "system.protocol.delivery.configWriteback.value": "未实现",
    "system.protocol.delivery.realMetrics.label": "真实指标数据",
    "system.protocol.delivery.realMetrics.value": "未连接",
    "system.protocol.delivery.liveEvents.label": "实时事件",
    "system.protocol.delivery.liveEvents.value": "未连接",
    "system.protocol.note":
      "正式交付前需分开验证 UI、管理服务、配置中心和实例生效闭环。",
  },
  "en-US": {
    "system.intro.title": "System management",
    "system.intro.description":
      "Inspect the boundaries between config center, metric collection and event reporting, keeping operational permissions simple and explicit.",
    "system.intro.aside": "Demo environment · no credential operations",
    "system.intro.tabGroupLabel": "System management sections",

    "system.tab.connections": "Connections and collection",
    "system.tab.permissions": "Permissions and audit",
    "system.tab.protocol": "Protocol and versions",

    "system.connection.title": "Connection and capability status",
    "system.connection.subtitle":
      "Config-center read/write, metrics and event reporting are separate links; every status below is a sample.",
    "system.connection.head.component": "Component",
    "system.connection.head.state": "Status",
    "system.connection.head.latency": "Latency",
    "system.connection.head.coverage": "Coverage",
    "system.connection.head.purpose": "Purpose",
    "system.connection.head.capability": "Capability boundary",
    "system.connection.state.available": "Available",
    "system.connection.state.demo": "Demo mode",
    "system.connection.note":
      "Real Nacos / Consul health checks, conditional writes and rollback must be implemented by a separate management service.",
    "system.connection.action.openRules": "Open the rule workbench",

    "system.permissions.grantHint":
      "How to grant: create the account under “Account maintenance”, then assign it a role under “Role binding”. Hiding UI is not a security boundary; the server re-validates on every write.",
    "system.permissions.title": "Least-privilege model",
    "system.permissions.subtitle":
      "Only distinguishes viewing from modifying rules; no multi-tenant RBAC.",
    "system.permissions.viewer.title": "Viewer",
    "system.permissions.viewer.description":
      "Can view the overview, application instances, live metrics, incidents and rule details.",
    "system.permissions.viewer.status": "Read-only",
    "system.permissions.maintainer.title": "Rule maintainer",
    "system.permissions.maintainer.description":
      "Can submit rule changes; the production flow still requires baseline version checks and auditing.",
    "system.permissions.maintainer.status": "Can modify",
    "system.permissions.auditTitle": "Release audit chain",
    "system.permissions.auditSubtitle": "This prototype does not produce real release records.",
    "system.permissions.audit.step1.title": "Edit and validate",
    "system.permissions.audit.step1.detail": "Schema, thresholds, blast radius",
    "system.permissions.audit.step2.title": "Generate the diff",
    "system.permissions.audit.step2.detail": "Baseline version, operator, reason",
    "system.permissions.audit.step3.title": "Conditional write-back",
    "system.permissions.audit.step3.detail": "Nacos / Consul confirmed",
    "system.permissions.audit.step4.title": "Observe effect",
    "system.permissions.audit.step4.detail": "Per-instance versions and failures",

    "system.protocol.boundaryTitle": "Protocol boundaries",
    "system.protocol.boundarySubtitle": "Control plane and observability plane evolve independently.",
    "system.protocol.ruleConfig.name": "Rule configuration",
    "system.protocol.ruleConfig.role":
      "Nacos / Consul is the authoritative rule source; the Dashboard writes through the management service.",
    "system.protocol.agentReporting.name": "Agent Reporting",
    "system.protocol.agentReporting.role":
      "Reports instance versions, health and events; takes no part in admission decisions.",
    "system.protocol.clusterToken.name": "Cluster Token",
    "system.protocol.clusterToken.role":
      "Owns quota decisions, separate from rule editing and event reporting.",
    "system.protocol.deliveryTitle": "Versions and status",
    "system.protocol.deliverySubtitle": "Sample values do not reflect the deployment environment.",
    "system.protocol.delivery.uiState.label": "UI status",
    "system.protocol.delivery.uiState.value": "Design prototype",
    "system.protocol.delivery.configWriteback.label": "Config-center write-back",
    "system.protocol.delivery.configWriteback.value": "Not implemented",
    "system.protocol.delivery.realMetrics.label": "Real metric data",
    "system.protocol.delivery.realMetrics.value": "Not connected",
    "system.protocol.delivery.liveEvents.label": "Live events",
    "system.protocol.delivery.liveEvents.value": "Not connected",
    "system.protocol.note":
      "Before delivery, verify the UI, the management service, the config center and the instance-effect loop separately.",
  },
  "ja-JP": {
    "system.intro.title": "システム管理",
    "system.intro.description":
      "設定センタ、メトリクス収集、イベント送信の境界を確認し、運用権限を単純で明確に保ちます。",
    "system.intro.aside": "デモ環境 · 認証情報の操作なし",
    "system.intro.tabGroupLabel": "システム管理の分類",

    "system.tab.connections": "接続と収集",
    "system.tab.permissions": "権限と監査",
    "system.tab.protocol": "プロトコルとバージョン",

    "system.connection.title": "接続と能力の状態",
    "system.connection.subtitle":
      "設定センターの読み書き、メトリクス、イベント送信はそれぞれ独立した経路です。以下の状態はすべてサンプルです。",
    "system.connection.head.component": "コンポーネント",
    "system.connection.head.state": "状態",
    "system.connection.head.latency": "レイテンシ",
    "system.connection.head.coverage": "適用率",
    "system.connection.head.purpose": "用途",
    "system.connection.head.capability": "能力の境界",
    "system.connection.state.available": "利用可能",
    "system.connection.state.demo": "デモモード",
    "system.connection.note":
      "実際の Nacos / Consul のヘルスチェック、条件付き書き込み、ロールバックは独立した管理サービスでの実装が必要です。",
    "system.connection.action.openRules": "ルールワークベンチを開く",

    "system.permissions.grantHint":
      "付与方法：「アカウント管理」でアカウントを作成し、「ロール割り当て」でロールを指定します。UI の非表示はセキュリティ境界ではなく、サーバーは書き込みごとに独立して再検証します。",
    "system.permissions.title": "最小権限モデル",
    "system.permissions.subtitle":
      "閲覧と変更のみを区別し、マルチテナント RBAC は導入しません。",
    "system.permissions.viewer.title": "閲覧者",
    "system.permissions.viewer.description":
      "概要、アプリケーションインスタンス、リアルタイムメトリクス、障害イベント、ルール詳細を閲覧できます。",
    "system.permissions.viewer.status": "読み取り専用",
    "system.permissions.maintainer.title": "ルール保守担当",
    "system.permissions.maintainer.description":
      "ルールの変更を提出できます。本番フローでは基準バージョンの検証と監査が別途必要です。",
    "system.permissions.maintainer.status": "変更可能",
    "system.permissions.auditTitle": "公開監査チェーン",
    "system.permissions.auditSubtitle":
      "このプロトタイプは実際の公開記録を生成しません。",
    "system.permissions.audit.step1.title": "編集と検証",
    "system.permissions.audit.step1.detail": "スキーマ、しきい値、影響範囲",
    "system.permissions.audit.step2.title": "差分の生成",
    "system.permissions.audit.step2.detail": "基準バージョン、実行者、理由",
    "system.permissions.audit.step3.title": "条件付き書き戻し",
    "system.permissions.audit.step3.detail": "Nacos / Consul の成功確認",
    "system.permissions.audit.step4.title": "適用の確認",
    "system.permissions.audit.step4.detail": "インスタンスごとのバージョンと失敗項目",

    "system.protocol.boundaryTitle": "プロトコルの境界",
    "system.protocol.boundarySubtitle": "コントロールプレーンと可観測性プレーンは独立して進化します。",
    "system.protocol.ruleConfig.name": "ルール設定",
    "system.protocol.ruleConfig.role":
      "Nacos / Consul が権威あるルールソースです。Dashboard は管理サービス経由で書き込みます。",
    "system.protocol.agentReporting.name": "Agent Reporting",
    "system.protocol.agentReporting.role":
      "インスタンスのバージョン・健全性・イベントを報告し、准入判断には関与しません。",
    "system.protocol.clusterToken.name": "Cluster Token",
    "system.protocol.clusterToken.role":
      "クォータ決定を担当し、ルール編集とイベント送信から分離されています。",
    "system.protocol.deliveryTitle": "バージョンと状態",
    "system.protocol.deliverySubtitle":
      "サンプルの値はデプロイ環境の現状を 나타しません。",
    "system.protocol.delivery.uiState.label": "UI の状態",
    "system.protocol.delivery.uiState.value": "プロトタイプ",
    "system.protocol.delivery.configWriteback.label": "設定センターへの書き戻し",
    "system.protocol.delivery.configWriteback.value": "未実装",
    "system.protocol.delivery.realMetrics.label": "実メトリクスデータ",
    "system.protocol.delivery.realMetrics.value": "未接続",
    "system.protocol.delivery.liveEvents.label": "リアルタイムイベント",
    "system.protocol.delivery.liveEvents.value": "未接続",
    "system.protocol.note":
      "リリース前に、UI・管理サービス・設定センター・インスタンスへの適用のループを個別に検証してください。",
  },
} as const satisfies LocaleBundle;
