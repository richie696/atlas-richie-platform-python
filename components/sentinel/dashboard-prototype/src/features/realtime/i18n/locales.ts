/**
 * 实时监控页的文案。
 *
 * 中文
 * ----
 * 归属本 feature：改这一页的一个词只动这里。
 *
 * ## 搬自 `ruleI18n.ts` 的 `realtime.metric.*`
 *
 * `METRIC_FILTER_LABEL_KEY` 早已指向 `realtime.metric.*` 五个键，译文在旧包里。
 * 本页是最后一个还在调 `createRuleTranslator` 的 feature，迁移时把这五个键的
 * 译文原样搬过来，不重新翻译。
 *
 * 注意 `realtime.metric.blocked`（筛选下拉里的「拦截率」）与
 * `realtime.chart.blocked`（图表标题的「请求拦截率」）措辞不同，**不能合并**——
 * 一个是筛选项的短名，一个是图表的完整标题。
 *
 * ## 跨行 JSX 文本的空格
 *
 * 底部提示原本写成两行，`TPS 需由……不能由 HTTP` / `QPS 推算。`。JSX 把换行
 * 规范化成一个空格，渲染结果是「不能由 HTTP QPS 推算」。译文取自实际渲染文本。
 */
import type { LocaleBundle } from "../../../core/i18n/types";

export const REALTIME_COPY = {
  "zh-CN": {
    // 搬自 ruleI18n
    "realtime.metric.all": "全部指标",
    "realtime.metric.qps": "HTTP QPS",
    "realtime.metric.rt": "RT p95",
    "realtime.metric.blocked": "拦截率",
    "realtime.metric.cpu": "CPU",

    "realtime.intro.title": "实时监控",
    "realtime.intro.description":
      "用同一时间轴观察流量、响应时间、拦截与资源压力的先后关系。",
    "realtime.filter.metric": "指标",
    "realtime.stream.live": "实时数据流",
    "realtime.stream.replay": "示例回放",
    "realtime.stream.static": "静态样本",
    "realtime.stream.paused": "回放已暂停",
    "realtime.action.resumeReplay": "继续回放",
    "realtime.action.pauseReplay": "暂停回放",
    "realtime.action.viewFaults": "查看关联故障",
    "realtime.bar.liveHint": "光标跟随实时数据流",
    "realtime.bar.replayHint": "光标移动仅演示交互，未连接实时数据流",
    "realtime.bar.replayRange": "{range} · 示例曲线回放",
    "realtime.chart.qps": "HTTP QPS",
    "realtime.chart.rt": "RT p95",
    "realtime.chart.blocked": "请求拦截率",
    "realtime.chart.cpu": "CPU 与内存使用率",
    "realtime.subtitle.qps": "整体请求量与规则发布时点",
    "realtime.subtitle.rt": "尾部响应时间，单位 ms",
    "realtime.subtitle.blocked": "被 Sentinel 拒绝的请求占比",
    "realtime.subtitle.cpu": "示例应用资源压力",
    "realtime.subtitle.qpsWithoutRelease": "当前窗口请求量（无发布时点）",
    "realtime.note.tps":
      "TPS 需由业务成功交易事件定义并单独接入，不能由 HTTP QPS 推算。",
  },
  "en-US": {
    // 搬自 ruleI18n
    "realtime.metric.all": "All metrics",
    "realtime.metric.qps": "HTTP QPS",
    "realtime.metric.rt": "RT p95",
    "realtime.metric.blocked": "Block rate",
    "realtime.metric.cpu": "CPU",

    "realtime.intro.title": "Live monitoring",
    "realtime.intro.description":
      "Watch traffic, response time, blocking and resource pressure on one timeline, in the order they happen.",
    "realtime.filter.metric": "Metric",
    "realtime.stream.live": "Live data stream",
    "realtime.stream.replay": "Sample replay",
    "realtime.stream.static": "Static sample",
    "realtime.stream.paused": "Replay paused",
    "realtime.action.resumeReplay": "Resume replay",
    "realtime.action.pauseReplay": "Pause replay",
    "realtime.action.viewFaults": "View related incidents",
    "realtime.bar.liveHint": "The cursor follows the live data stream",
    "realtime.bar.replayHint":
      "Cursor movement only demonstrates the interaction; no live data stream is connected",
    "realtime.bar.replayRange": "{range} · sample curve replay",
    "realtime.chart.qps": "HTTP QPS",
    "realtime.chart.rt": "RT p95",
    "realtime.chart.blocked": "Request block rate",
    "realtime.chart.cpu": "CPU and memory usage",
    "realtime.subtitle.qps": "Overall request volume and rule release points",
    "realtime.subtitle.rt": "Tail response time, in ms",
    "realtime.subtitle.blocked": "Share of requests rejected by Sentinel",
    "realtime.subtitle.cpu": "Resource pressure of the sample application",
    "realtime.subtitle.qpsWithoutRelease": "Request volume in this window (no release point)",
    "realtime.note.tps":
      "TPS must be defined by successful business transactions and integrated separately; it cannot be derived from HTTP QPS.",
  },
  "ja-JP": {
    // 搬自 ruleI18n
    "realtime.metric.all": "全指標",
    "realtime.metric.qps": "HTTP QPS",
    "realtime.metric.rt": "RT p95",
    "realtime.metric.blocked": "遮断率",
    "realtime.metric.cpu": "CPU",

    "realtime.intro.title": "リアルタイム監視",
    "realtime.intro.description":
      "トラフィック、応答時間、遮断、リソース圧迫がどの順に起きたかを同じ時間軸で確認します。",
    "realtime.filter.metric": "指標",
    "realtime.stream.live": "リアルタイムデータストリーム",
    "realtime.stream.replay": "サンプル再生",
    "realtime.stream.static": "静的サンプル",
    "realtime.stream.paused": "再生を一時停止中",
    "realtime.action.resumeReplay": "再生を再開",
    "realtime.action.pauseReplay": "再生を一時停止",
    "realtime.action.viewFaults": "関連する障害を表示",
    "realtime.bar.liveHint": "カーソルはリアルタイムデータストリームに追従します",
    "realtime.bar.replayHint":
      "カーソル移動は操作のデモンストレーションのみで、リアルタイムデータストリームは接続されていません",
    "realtime.bar.replayRange": "{range} · サンプル曲線再生",
    "realtime.chart.qps": "HTTP QPS",
    "realtime.chart.rt": "RT p95",
    "realtime.chart.blocked": "リクエスト遮断率",
    "realtime.chart.cpu": "CPU とメモリ使用率",
    "realtime.subtitle.qps": "全体のリクエスト量とルール公開時点",
    "realtime.subtitle.rt": "テールレイテンシ（単位: ms）",
    "realtime.subtitle.blocked": "Sentinel が拒否したリクエストの割合",
    "realtime.subtitle.cpu": "サンプルアプリケーションのリソース圧迫",
    "realtime.subtitle.qpsWithoutRelease": "現在のウィンドウのリクエスト量（公開時点なし）",
    "realtime.note.tps":
      "TPS は業務上の成功トランザクションで定義し、別途で取り込む必要があります。HTTP QPS から算出してはいけません。",
  },
} as const satisfies LocaleBundle;
