/**
 * 系统管理的演示数据。
 *
 * 中文
 * ----
 * fixture 只在本 feature 的 UI 与测试中使用；**生产代码路径不导入它**
 * （`REACT_PROJECT_SKELETON` §2：`fixtures/` 是显式测试/演示数据）。
 * 接入 Console API 后本文件整体删除，连接状态改由 `system.gateway` 提供
 * （`GET /api/v1/system/connections`）。
 *
 * 这里放的是**随环境变化的读模型**：连接状态、覆盖率、采样覆盖率。
 * 权限模型、协议边界和交付形态状态在 `model/systemStatus.ts`，因为它们是产品
 * 常量而非某次采集的结果。
 *
 * 所有数值都是示例，不代表任何真实部署；`state: "演示模式"` 是刻意保留的事实，
 * 不得为了让页面「看起来健康」而改成可用。
 */
import {
  CONNECTION_KIND,
  CONNECTION_STATE,
  type ConnectionStatus,
  type ConnectionSummaryCard,
} from "../model/systemStatus";

/** 「连接与采集」的连接状态表。 */
export const CONNECTIONS: readonly ConnectionStatus[] = Object.freeze([
  {
    kind: CONNECTION_KIND.ConfigCenter,
    name: "Nacos",
    state: CONNECTION_STATE.Available,
    latency: "12 ms",
    scope: "3 个应用",
    purpose: "配置查询与规则发布",
    capability: "读写已配置",
  },
  {
    kind: CONNECTION_KIND.ConfigCenter,
    name: "Consul",
    state: CONNECTION_STATE.Available,
    latency: "18 ms",
    scope: "1 个应用",
    purpose: "KV 查询与条件写入",
    capability: "读写已配置",
  },
  {
    kind: CONNECTION_KIND.MetricsBackend,
    name: "指标后端",
    state: CONNECTION_STATE.Demo,
    latency: "—",
    scope: "示例曲线",
    purpose: "主机、容器和进程时序指标",
    capability: "未连接真实后端",
  },
  {
    kind: CONNECTION_KIND.ReportingCollector,
    name: "Agent Reporting",
    state: CONNECTION_STATE.Demo,
    latency: "—",
    scope: "示例事件",
    purpose: "实例版本与故障事件",
    capability: "未连接真实 Collector",
  },
]);

/**
 * 顶部四个概览数字。
 *
 * 中文
 * ----
 * `unit` / `tone` 只在需要时出现：缺省即 `NumberCard` 的空串默认值，补成显式空串
 * 不会改变 DOM，但会让「哪些卡片有语义色」变成噪声。
 */
export const CONNECTION_SUMMARY_CARDS: readonly ConnectionSummaryCard[] = Object.freeze([
  {
    label: "配置中心",
    value: "2 / 2",
    note: "Nacos 与 Consul（示例）",
    tone: "green",
  },
  { label: "采样覆盖率", value: "100", unit: "%", note: "演示指标" },
  {
    label: "规则生效覆盖",
    value: "98",
    unit: "%",
    note: "142 / 145 实例（示例）",
  },
  {
    label: "采集链路",
    value: "未连接",
    note: "真实 Collector 尚未接入",
    tone: "amber",
  },
]);
