/**
 * 故障分析的演示数据。
 *
 * 中文
 * ----
 * fixture 只在本目录与测试中使用；生产代码路径不导入它
 * （`REACT_PROJECT_SKELETON` §2）。接入 Console API 后本文件整体删除，事件改由
 * `faults.gateway` 依据 Agent Reporting 事件流 + 控制面发布审计提供。
 *
 * 事件按发生时间**倒序**排列，这是列表的读模型契约（§4.5 `IncidentList`），筛选保持
 * 顺序不变。
 *
 * 事件之间的关联（资源压力与 RT 上升发生在同一时段）是**示例**，不是因果结论：详情页
 * 因此只陈述观测事实与建议下一步，不做自动根因断言。
 */
import { INCIDENT_CATEGORY, INCIDENT_SEVERITY, NO_INSTANCE, type IncidentEvent } from "../model/incident";

/** 示例事件。全部落在 2026-09-14 14:02 – 14:27 之间。 */
export const INCIDENT_FIXTURES: readonly IncidentEvent[] = Object.freeze([
  {
    id: "evt-1",
    date: "2026-09-14",
    at: "14:27:18",
    severity: INCIDENT_SEVERITY.Critical,
    category: INCIDENT_CATEGORY.Resource,
    appId: "order-service",
    instanceId: "order-5",
    title: "order-5 容器 CPU 持续高于 90%",
    observedFact: "CPU 持续 5 分钟高于 90%，同一时段 RT p95 上升至 420 ms。",
    suggestedAction: "先核对容器限制与当前流量，再检查对应规则是否需要调整。",
  },
  {
    id: "evt-2",
    date: "2026-09-14",
    at: "14:22:04",
    severity: INCIDENT_SEVERITY.Warning,
    category: INCIDENT_CATEGORY.RuleEffective,
    appId: "order-service",
    instanceId: "order-7",
    title: "order-service 规则版本未完全一致",
    observedFact:
      "一个实例在观测窗口内仍报告旧版本；配置中心写入成功不等于全部实例已应用。",
    suggestedAction: "查看实例的最后上报时间和规则源健康状态。",
  },
  {
    id: "evt-3",
    date: "2026-09-14",
    at: "14:18:39",
    severity: INCIDENT_SEVERITY.Warning,
    category: INCIDENT_CATEGORY.ResponseTime,
    appId: "payment-service",
    instanceId: "payment-3",
    title: "payment-service RT p95 上升",
    observedFact:
      "最近 15 分钟 p95 从 180 ms 上升至 310 ms，需结合下游和资源压力进一步排查。",
    suggestedAction: "按时间线比对下游异常与规则发布。",
  },
  {
    id: "evt-4",
    date: "2026-09-14",
    at: "14:02:00",
    severity: INCIDENT_SEVERITY.Info,
    category: INCIDENT_CATEGORY.RulePublished,
    appId: "order-service",
    instanceId: NO_INSTANCE,
    title: "order-service 发布规则版本 v20260914-01",
    observedFact: "规则内容发生变更，发布点已标注在相关趋势图中。",
    suggestedAction: "查看发布差异与实例生效情况。",
  },
]);

/**
 * 故障分析可见的应用目录。
 *
 * 中文
 * ----
 * 旧实现读跨 feature 的全局应用常量，于是「故障分析能选哪些应用」由所有页面共用的
 * 一份数组决定（`DASHBOARD_CONTROL_PLANE.md` §4.2：应用目录属于各 feature 自己的读
 * 模型）。生产实现来自事件流与指标后端可查询到的应用目录。
 *
 * `user-service` 在示例窗口内没有事件：选中它会看到空列表，这是诚实的「无事件」，
 * 不该靠从下拉里删掉该应用来隐藏。
 */
export const FAULTS_APP_FIXTURES: readonly { readonly id: string; readonly label: string }[] =
  Object.freeze([
    { id: "order-service", label: "order-service" },
    { id: "payment-service", label: "payment-service" },
    { id: "user-service", label: "user-service" },
  ]);
