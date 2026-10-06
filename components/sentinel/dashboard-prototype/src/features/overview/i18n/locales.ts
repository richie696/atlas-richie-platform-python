/**
 * 全局运行概览页的文案。
 *
 * 中文
 * ----
 * 归属本 feature：改总览的一个词只动这里，不进任何共享文案包。
 * 键以 `overview.` 前缀，`buildDictionary` 会在组装期对重复键抛错。
 *
 * ## 搬自 `ruleI18n.ts` 的两个键
 *
 * `overview.trend.windowExcludesRelease` / `sharedWindow` 原本就以 `overview.` 前缀
 * 存在旧包里（嵌套在 `overview.trend` 下），译文直接搬过来，不重新翻译——
 * 重新翻译会让切换语言前后的措辞不一致，而这类差异没有任何测试能发现。
 *
 * ## 不在这里的内容
 *
 * 应用名、实例名、健康状态、规则版本、CPU/内存/QPS 数字都来自
 * `fixtures/overviewFixtures.ts`，是**数据**不是界面文案。趋势图的时间轴标签同理。
 * 把它们搬进文案包会让「演示数据」和「界面语言」耦在一起，fixture 一改就要动三份翻译。
 */
import type { LocaleBundle } from "../../../core/i18n/types";

export const OVERVIEW_COPY = {
  "zh-CN": {
    "overview.intro.title": "全局运行概览",
    "overview.intro.description":
      "从应用视角了解整体流量与防护状况，快速定位需要关注的服务。",
    "overview.attention.appsRunning": "{count} 个应用运行中，",
    "overview.attention.needsAttention": "{count} 个需要关注",
    "overview.attention.viewApps": "查看异常应用",
    "overview.infra.title": "基础组件与规则状态",
    "overview.infra.demoOnly": "均为演示状态",
    "overview.infra.state.available": "可用",
    "overview.infra.state.unavailable": "不可用",
    "overview.infra.state.connecting": "连接中",
    "overview.infra.component.ruleDelivery": "规则版本下发",
    "overview.trend.title": "全局流量与防护趋势",
    "overview.trend.qpsTitle": "总 HTTP QPS（次/秒）",
    "overview.trend.blockedTitle": "请求拦截率（Blocked Rate）",
    "overview.trend.sampleWindow": "14:17–14:32 · 示例窗口",
    "overview.trend.beforeRelease": "发布前",
    "overview.trend.afterRelease": "发布后",
    "overview.trend.tpsNote": "TPS 暂无接入 · 不与 QPS 混用",
    "overview.trend.windowExcludesRelease":
      "当前窗口不含 14:02 发布时点；切换到{longer}查看发布前后对比。",
    "overview.trend.sharedWindow": "上下图共用时间范围；蓝色虚线标注一次示例规则发布。",
    "overview.table.title": "应用运行状态",
    "overview.table.head.name": "应用名称",
    "overview.table.head.status": "状态",
    "overview.table.head.instances": "实例数",
    "overview.table.head.cpuAvg": "CPU 平均",
    "overview.table.head.memoryAvg": "内存平均",
    "overview.table.head.httpQps": "HTTP QPS",
    "overview.table.head.rtP95": "RT p95",
    "overview.table.head.blockedRate": "拦截率",
    "overview.table.head.ruleVersion": "规则版本",
    "overview.table.head.actions": "操作",
    "overview.table.health.critical": "资源压力",
    "overview.table.health.warning": "CPU 偏高",
    "overview.table.health.healthy": "运行正常",
    "overview.table.subtitle": "按应用聚合的关键指标，点击应用可进入实例矩阵。",
    "overview.table.viewAll": "查看全部应用",
    "overview.table.detail": "详情",
    "overview.table.note": "演示列表显示 {shown} / {total} 个应用。",
  },
  "en-US": {
    "overview.intro.title": "Fleet overview",
    "overview.intro.description":
      "Understand overall traffic and protection from an application perspective, and quickly locate services that need attention.",
    "overview.attention.appsRunning": "{count} applications running, ",
    "overview.attention.needsAttention": "{count} need attention",
    "overview.attention.viewApps": "View affected applications",
    "overview.infra.title": "Infrastructure and rule delivery",
    "overview.infra.demoOnly": "all demo states",
    "overview.infra.state.available": "Available",
    "overview.infra.state.unavailable": "Unavailable",
    "overview.infra.state.connecting": "Connecting",
    "overview.infra.component.ruleDelivery": "Rule version delivery",
    "overview.trend.title": "Fleet traffic and protection trends",
    "overview.trend.qpsTitle": "Total HTTP QPS (req/s)",
    "overview.trend.blockedTitle": "Request block rate (Blocked Rate)",
    "overview.trend.sampleWindow": "14:17–14:32 · sample window",
    "overview.trend.beforeRelease": "Before release",
    "overview.trend.afterRelease": "After release",
    "overview.trend.tpsNote": "TPS not integrated · never mixed with QPS",
    "overview.trend.windowExcludesRelease":
      "This window excludes the 14:02 release; switch to {longer} to compare before and after.",
    "overview.trend.sharedWindow":
      "Both charts share one time range; the blue dashed line marks a sample rule release.",
    "overview.table.title": "Application status",
    "overview.table.head.name": "Application",
    "overview.table.head.status": "Status",
    "overview.table.head.instances": "Instances",
    "overview.table.head.cpuAvg": "Avg CPU",
    "overview.table.head.memoryAvg": "Avg memory",
    "overview.table.head.httpQps": "HTTP QPS",
    "overview.table.head.rtP95": "RT p95",
    "overview.table.head.blockedRate": "Block rate",
    "overview.table.head.ruleVersion": "Rule version",
    "overview.table.head.actions": "Actions",
    "overview.table.health.critical": "Resource pressure",
    "overview.table.health.warning": "High CPU",
    "overview.table.health.healthy": "Healthy",
    "overview.table.subtitle":
      "Key metrics aggregated per application; click an application to open its instance matrix.",
    "overview.table.viewAll": "View all applications",
    "overview.table.detail": "Details",
    "overview.table.note": "The demo list shows {shown} / {total} applications.",
  },
  "ja-JP": {
    "overview.intro.title": "全体ランタイム概観",
    "overview.intro.description":
      "アプリケーション視点で全体のトラフィックと防御状況を確認し、注目すべきサービスをすばやく特定します。",
    "overview.attention.appsRunning": "{count} 個のアプリケーションが稼働中、",
    "overview.attention.needsAttention": "{count} 個が要注目",
    "overview.attention.viewApps": "異常アプリケーションを表示",
    "overview.infra.title": "基盤コンポーネントとルール配信",
    "overview.infra.demoOnly": "すべてデモ状態",
    "overview.infra.state.available": "利用可能",
    "overview.infra.state.unavailable": "利用不可",
    "overview.infra.state.connecting": "接続中",
    "overview.infra.component.ruleDelivery": "ルールバージョン配信",
    "overview.trend.title": "全体のトラフィックと防御傾向",
    "overview.trend.qpsTitle": "HTTP QPS 合計（req/s）",
    "overview.trend.blockedTitle": "リクエスト遮断率（Blocked Rate）",
    "overview.trend.sampleWindow": "14:17–14:32 · サンプルウィンドウ",
    "overview.trend.beforeRelease": "リリース前",
    "overview.trend.afterRelease": "リリース後",
    "overview.trend.tpsNote": "TPS は未連携 · QPS とは混合しません",
    "overview.trend.windowExcludesRelease":
      "このウィンドウには 14:02 のリリースは含まれません。{longer}に切替えると前後を比較できます。",
    "overview.trend.sharedWindow":
      "両グラフは同じ時間範囲を使用します。青い破線はルールリリースの例を示します。",
    "overview.table.title": "アプリケーション稼働状況",
    "overview.table.head.name": "アプリケーション",
    "overview.table.head.status": "状態",
    "overview.table.head.instances": "インスタンス数",
    "overview.table.head.cpuAvg": "CPU 平均",
    "overview.table.head.memoryAvg": "メモリ平均",
    "overview.table.head.httpQps": "HTTP QPS",
    "overview.table.head.rtP95": "RT p95",
    "overview.table.head.blockedRate": "遮断率",
    "overview.table.head.ruleVersion": "ルールバージョン",
    "overview.table.head.actions": "操作",
    "overview.table.health.critical": "リソース圧迫",
    "overview.table.health.warning": "CPU 高め",
    "overview.table.health.healthy": "正常",
    "overview.table.subtitle":
      "アプリケーションごとに集約した主要指標です。クリックでインスタンス一覧へ移動します。",
    "overview.table.viewAll": "すべてのアプリケーションを表示",
    "overview.table.detail": "詳細",
    "overview.table.note": "デモ一覧は {shown} / {total} 個のアプリケーションを表示しています。",
  },
} as const satisfies LocaleBundle;
