/**
 * 应用与实例页的文案。
 *
 * 中文
 * ----
 * 归属本 feature：改这一页的一个词只动这里。
 *
 * ## 跨行 JSX 文本的空格
 *
 * `ApplicationsPage` 的空实例提示原本写成两行：
 *
 *     <Info size={16} /> 下方仍为 order-service
 *     的示例矩阵，应用筛选不改变这组演示数据。
 *
 * JSX 把每行前后的空白去掉、把换行规范化成**一个空格**，所以渲染结果是
 * 「下方仍为 order-service 的示例矩阵，……」——`order-service` 后面有空格。
 * 照着源码抄会得到「order-service的示例矩阵」，DOM 立刻不等价。
 * 这里的译文取自实际渲染文本，不是源码字面量。
 *
 * ## 不在这里的内容
 *
 * 应用名、实例 id、宿主机、状态、指标数字、规则版本都来自
 * `fixtures/`，是数据。`app.stateLabel` / `instance.statusLabel` 暂留在 fixture
 * （枚举标签的收敛见 `features/overview` 里 `healthReason` 的处理）。
 */
import type { LocaleBundle } from "../../../core/i18n/types";

export const APPLICATIONS_COPY = {
  "zh-CN": {
    "applications.intro.title": "应用与实例",
    "applications.intro.description":
      "先比较实例，再按宿主机、容器或进程定位资源压力与流控影响。",
    "applications.summary.anomalyCount":
      "{instanceCount} 个实例中 {anomalyCount} 个资源压力偏高",
    "applications.summary.advice":
      "两个实例出现 CPU 或内存持续高位，建议尽快处理。",
    "applications.summary.noSamples":
      "此原型仅有 order-service 的实例示例，不会伪造其他应用的实例。",
    "applications.action.viewAnomalies": "查看异常实例",
    "applications.card.ruleVersion": "当前规则版本",
    "applications.card.configProvider": "配置来源",
    "applications.card.effective": "示例生效",
    "applications.card.instances": "{running} / {total} 实例",
    "applications.action.viewRuleDetail": "查看规则详情",
    "applications.note.matrixScope":
      "下方仍为 order-service 的示例矩阵，应用筛选不改变这组演示数据。",
    "applications.scope.host": "宿主机",
    "applications.scope.container": "容器",
    "applications.scope.process": "进程",
    "applications.metrics.demo": "{scope}指标 · 演示数据",
    "applications.metrics.empty": "{scope}指标尚无示例数据",
    "applications.detail.title": "实例详情",
    "applications.detail.emptySubtitle": "实例目录为空",
    "applications.detail.emptyBody": "实例目录为空：0",
    "applications.detail.subtitle": "{host} · container: {id} · 示例",
    "applications.detail.usage": "CPU / 内存使用率",
    "applications.detail.memory": "内存",
    "applications.detail.http": "HTTP QPS / 请求拦截率",
    "applications.detail.blockedRate": "拦截率",
    "applications.detail.scopeNote":
      "当前原型只提供容器级示例曲线；宿主机和进程指标需接入对应采集源。",
    "applications.detail.currentRule": "当前流控规则",
    "applications.detail.ruleThreshold": "QPS 阈值 2,000 · 慢调用比例 20%",
    "applications.action.viewRules": "查看规则",
    "applications.matrix.head.instance": "实例 / 宿主机",
    "applications.matrix.head.status": "状态",
    "applications.matrix.head.containerCpu": "容器 CPU",
    "applications.matrix.head.containerMemory": "容器内存",
    "applications.matrix.head.httpQps": "HTTP QPS",
    "applications.matrix.head.rtP95": "RT p95",
    "applications.matrix.head.blockedRate": "请求拦截率",
    "applications.matrix.head.ruleVersion": "规则版本",
    /**
     * 值带**前导空格**，且不含括号——这是刻意的。
     *
     * 原 JSX 是 `<span>({rows.length} 个实例)</span>`，children 是数组
     * `["(", 2, " 个实例)"]`。React 在数组元素之间插入 `<!-- -->` 注释标记，
     * 而 `capture-baseline.mjs` 的归一化不剥离注释。若把它改成
     * `t("applications.matrix.hostCount", { count })` 这一个字符串，children
     * 变成单值、注释标记消失，DOM 立刻不等价。键里保留前导空格能让 JSX 写成
     * `({rows.length}{t(...)})`，children 形态与原来逐项相同。
     */
    "applications.matrix.hostCountUnit": " 个实例)",
    "applications.matrix.title": "实例健康矩阵",
    "applications.matrix.subtitle":
      "共 {count} 个示例实例，按宿主机分组 · {filter}",
    "applications.matrix.anomaliesOnly": "仅看异常",
    "applications.matrix.all": "全部",
  },
  "en-US": {
    "applications.intro.title": "Applications and instances",
    "applications.intro.description":
      "Compare instances first, then locate resource pressure and flow-control impact by host, container or process.",
    "applications.summary.anomalyCount":
      "{anomalyCount} of {instanceCount} instances under resource pressure",
    "applications.summary.advice":
      "Two instances show sustained high CPU or memory; handle them as soon as possible.",
    "applications.summary.noSamples":
      "This prototype only has instance samples for order-service; it will not fabricate instances for other applications.",
    "applications.action.viewAnomalies": "View affected instances",
    "applications.card.ruleVersion": "Current rule version",
    "applications.card.configProvider": "Config source",
    "applications.card.effective": "Sample effective on",
    "applications.card.instances": "{running} / {total} instances",
    "applications.action.viewRuleDetail": "View rule details",
    "applications.note.matrixScope":
      "The matrix below still shows order-service samples; the application filter does not change this demo data.",
    "applications.scope.host": "Host",
    "applications.scope.container": "Container",
    "applications.scope.process": "Process",
    "applications.metrics.demo": "{scope} metrics · demo data",
    "applications.metrics.empty": "No sample data for {scope} metrics",
    "applications.detail.title": "Instance details",
    "applications.detail.emptySubtitle": "Instance directory is empty",
    "applications.detail.emptyBody": "Instance directory is empty: 0",
    "applications.detail.subtitle": "{host} · container: {id} · sample",
    "applications.detail.usage": "CPU / memory usage",
    "applications.detail.memory": "Memory",
    "applications.detail.http": "HTTP QPS / request block rate",
    "applications.detail.blockedRate": "Block rate",
    "applications.detail.scopeNote":
      "This prototype only provides container-level sample curves; host and process metrics need their own collection sources.",
    "applications.detail.currentRule": "Current flow-control rule",
    "applications.detail.ruleThreshold": "QPS threshold 2,000 · slow-call ratio 20%",
    "applications.action.viewRules": "View rules",
    "applications.matrix.head.instance": "Instance / host",
    "applications.matrix.head.status": "Status",
    "applications.matrix.head.containerCpu": "Container CPU",
    "applications.matrix.head.containerMemory": "Container memory",
    "applications.matrix.head.httpQps": "HTTP QPS",
    "applications.matrix.head.rtP95": "RT p95",
    "applications.matrix.head.blockedRate": "Request block rate",
    "applications.matrix.head.ruleVersion": "Rule version",
    "applications.matrix.hostCountUnit": " instances)",
    "applications.matrix.title": "Instance health matrix",
    "applications.matrix.subtitle":
      "{count} sample instances in total, grouped by host · {filter}",
    "applications.matrix.anomaliesOnly": "Affected only",
    "applications.matrix.all": "All",
  },
  "ja-JP": {
    "applications.intro.title": "アプリケーションとインスタンス",
    "applications.intro.description":
      "まずインスタンスを比較し、次にホスト・コンテナ・プロセス単位でリソース圧迫と流量制御の影響を特定します。",
    "applications.summary.anomalyCount":
      "{instanceCount} 個中 {anomalyCount} 個のインスタンスでリソース圧迫",
    "applications.summary.advice":
      "2 つのインスタンスで CPU またはメモリが継続的に高水準です。至急対応してください。",
    "applications.summary.noSamples":
      "このプロトタイプには order-service のインスタンス例しかなく、他のアプリケーションのインスタンスは生成しません。",
    "applications.action.viewAnomalies": "異常インスタンスを表示",
    "applications.card.ruleVersion": "現在のルールバージョン",
    "applications.card.configProvider": "設定元",
    "applications.card.effective": "サンプル適用",
    "applications.card.instances": "{running} / {total} インスタンス",
    "applications.action.viewRuleDetail": "ルール詳細を表示",
    "applications.note.matrixScope":
      "以下のマトリクスは order-service のサンプルデータのままで、アプリケーションフィルタでは変わりません。",
    "applications.scope.host": "ホスト",
    "applications.scope.container": "コンテナ",
    "applications.scope.process": "プロセス",
    "applications.metrics.demo": "{scope}の指標 · デモデータ",
    "applications.metrics.empty": "{scope}の指標にはサンプルデータがありません",
    "applications.detail.title": "インスタンス詳細",
    "applications.detail.emptySubtitle": "インスタンス一覧が空です",
    "applications.detail.emptyBody": "インスタンス一覧が空です：0",
    "applications.detail.subtitle": "{host} · container: {id} · サンプル",
    "applications.detail.usage": "CPU / メモリ使用率",
    "applications.detail.memory": "メモリ",
    "applications.detail.http": "HTTP QPS / リクエスト遮断率",
    "applications.detail.blockedRate": "遮断率",
    "applications.detail.scopeNote":
      "このプロトタイプが提供するのはコンテナ単位のサンプル曲線のみです。ホストとプロセスの指標には対応する収集源が必要です。",
    "applications.detail.currentRule": "現在の流量制御ルール",
    "applications.detail.ruleThreshold": "QPS 閾値 2,000 · スローコール比率 20%",
    "applications.action.viewRules": "ルールを表示",
    "applications.matrix.head.instance": "インスタンス / ホスト",
    "applications.matrix.head.status": "状態",
    "applications.matrix.head.containerCpu": "コンテナ CPU",
    "applications.matrix.head.containerMemory": "コンテナメモリ",
    "applications.matrix.head.httpQps": "HTTP QPS",
    "applications.matrix.head.rtP95": "RT p95",
    "applications.matrix.head.blockedRate": "リクエスト遮断率",
    "applications.matrix.head.ruleVersion": "ルールバージョン",
    "applications.matrix.hostCountUnit": " インスタンス)",
    "applications.matrix.title": "インスタンス健全性マトリクス",
    "applications.matrix.subtitle":
      "サンプル {count} インスタンスをホスト別にグループ化 · {filter}",
    "applications.matrix.anomaliesOnly": "異常のみ",
    "applications.matrix.all": "すべて",
  },
} as const satisfies LocaleBundle;
