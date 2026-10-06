/**
 * 故障分析页的文案。
 *
 * 中文
 * ----
 * 归属本 feature：`docs/PRE_CODING_REVIEW.md` 第 2 问要求「一个文件一个主要变化
 * 原因」。改故障分析的一个词只动这里，不进任何共享文案包。
 *
 * 键以 `faults.` 前缀，避免与其他 feature 撞名（`buildDictionary` 会在组装期
 * 对重复键抛错，那是刻意的：键名冲突说明消息归属没定清楚）。
 *
 * 事件标题、观测事实、建议动作等**数据内容**不在这里 —— 它们来自
 * `features/faults/fixtures` 与未来的 gateway，属于读模型而非界面文案。
 */
import type { LocaleBundle } from "../../../core/i18n/types";

export const FAULTS_COPY = {
  "zh-CN": {
    "faults.intro.eyebrow": "DIAGNOSIS / INCIDENTS",
    "faults.intro.title": "故障分析",
    "faults.intro.description":
      "把压力、响应变慢、拦截升高和规则发布放到同一条证据时间线上。",
    "faults.summary.critical": "严重事件",
    "faults.summary.criticalUnit": "个严重事件",
    "faults.summary.criticalNote": "需要处理",
    "faults.summary.warning": "警告事件",
    "faults.summary.warningNote": "持续观察",
    "faults.summary.ruleChange": "规则变更",
    "faults.summary.ruleChangeNote": "当前筛选窗口",
    "faults.summary.affectedApps": "影响应用",
    "faults.summary.affectedAppsNote": "当前筛选窗口",
    "faults.timeline.title": "事件时间线",
    "faults.timeline.subtitle": "示例事件按发生时间倒序排列",
    "faults.timeline.severityFilter": "事件级别",
    "faults.timeline.empty": "当前筛选条件下没有示例事件。",
    "faults.evidence.title": "事件证据",
    "faults.evidence.subtitle": "先确认事实，再判断相关性；时间接近不等于因果关系。",
    "faults.evidence.emptySubtitle": "选择事件查看观测事实与建议动作。",
    "faults.evidence.empty": "暂无可展示的事件证据。",
    "faults.evidence.occurredAt": "发生时间",
    "faults.evidence.affectedApp": "影响应用",
    "faults.evidence.relatedInstance": "关联实例",
    "faults.evidence.observed": "观测事实",
    "faults.evidence.suggested": "建议下一步",
    "faults.evidence.noCausality": "关联为示例，不提供自动根因断言。",
    "faults.evidence.viewApp": "查看应用与实例",
    "faults.severity.critical": "严重",
    "faults.severity.warning": "警告",
    "faults.severity.info": "信息",
    "faults.severity.all": "全部级别",
    "faults.category.resource": "资源压力",
    "faults.category.responseTime": "响应时间",
    "faults.category.rulePublished": "规则发布",
    "faults.category.ruleEffective": "规则生效",
  },
  "en-US": {
    "faults.intro.eyebrow": "DIAGNOSIS / INCIDENTS",
    "faults.intro.title": "Fault analysis",
    "faults.intro.description":
      "Put resource pressure, response slowdown, block-rate increases and rule releases on one evidence timeline.",
    "faults.summary.critical": "Critical events",
    "faults.summary.criticalUnit": "critical events",
    "faults.summary.criticalNote": "Needs action",
    "faults.summary.warning": "Warning events",
    "faults.summary.warningNote": "Keep watching",
    "faults.summary.ruleChange": "Rule changes",
    "faults.summary.ruleChangeNote": "Current filter window",
    "faults.summary.affectedApps": "Affected applications",
    "faults.summary.affectedAppsNote": "Current filter window",
    "faults.timeline.title": "Event timeline",
    "faults.timeline.subtitle": "Sample events sorted by time, newest first",
    "faults.timeline.severityFilter": "Event severity",
    "faults.timeline.empty": "No sample events match the current filters.",
    "faults.evidence.title": "Event evidence",
    "faults.evidence.subtitle":
      "Confirm the facts before judging correlation; close in time is not causation.",
    "faults.evidence.emptySubtitle": "Select an event to see observed facts and suggested actions.",
    "faults.evidence.empty": "No event evidence to show.",
    "faults.evidence.occurredAt": "Occurred at",
    "faults.evidence.affectedApp": "Affected application",
    "faults.evidence.relatedInstance": "Related instance",
    "faults.evidence.observed": "Observed facts",
    "faults.evidence.suggested": "Suggested next step",
    "faults.evidence.noCausality":
      "Correlation is illustrative; no automatic root-cause claim is made.",
    "faults.evidence.viewApp": "View applications and instances",
    "faults.severity.critical": "Critical",
    "faults.severity.warning": "Warning",
    "faults.severity.info": "Info",
    "faults.severity.all": "All levels",
    "faults.category.resource": "Resource pressure",
    "faults.category.responseTime": "Response time",
    "faults.category.rulePublished": "Rule published",
    "faults.category.ruleEffective": "Rule effective",
  },
  "ja-JP": {
    "faults.intro.eyebrow": "DIAGNOSIS / INCIDENTS",
    "faults.intro.title": "障害分析",
    "faults.intro.description":
      "リソース圧迫、応答劣化、ブロック率の上昇、ルール公開を 1 本の証跡タイムラインにまとめます。",
    "faults.summary.critical": "重大なイベント",
    "faults.summary.criticalUnit": "件の重大なイベント",
    "faults.summary.criticalNote": "要対応",
    "faults.summary.warning": "警告イベント",
    "faults.summary.warningNote": "継続監視",
    "faults.summary.ruleChange": "ルール変更",
    "faults.summary.ruleChangeNote": "現在の絞り込み期間",
    "faults.summary.affectedApps": "影響アプリケーション",
    "faults.summary.affectedAppsNote": "現在の絞り込み期間",
    "faults.timeline.title": "イベントタイムライン",
    "faults.timeline.subtitle": "サンプルイベントを発生時刻の降順で並べています",
    "faults.timeline.severityFilter": "イベント重要度",
    "faults.timeline.empty": "現在の絞り込み条件に一致するサンプルイベントはありません。",
    "faults.evidence.title": "イベント証跡",
    "faults.evidence.subtitle":
      "関連性を判断する前に事実を確認してください。時刻が近いことは因果を意味しません。",
    "faults.evidence.emptySubtitle": "イベントを選択すると観測事実と推奨アクションが表示されます。",
    "faults.evidence.empty": "表示できるイベント証跡はありません。",
    "faults.evidence.occurredAt": "発生時刻",
    "faults.evidence.affectedApp": "影響アプリケーション",
    "faults.evidence.relatedInstance": "関連インスタンス",
    "faults.evidence.observed": "観測事実",
    "faults.evidence.suggested": "推奨する次の対応",
    "faults.evidence.noCausality":
      "関連性はサンプルのものであり、自動的な原因断定は行いません。",
    "faults.evidence.viewApp": "アプリケーションとインスタンスを見る",
    "faults.severity.critical": "重大",
    "faults.severity.warning": "警告",
    "faults.severity.info": "情報",
    "faults.severity.all": "すべての重要度",
    "faults.category.resource": "リソース圧迫",
    "faults.category.responseTime": "応答時間",
    "faults.category.rulePublished": "ルール公開",
    "faults.category.ruleEffective": "ルール有効化",
  },
} as const satisfies LocaleBundle;
