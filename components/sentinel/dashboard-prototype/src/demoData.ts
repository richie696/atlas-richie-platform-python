export const PAGE_ITEMS = Object.freeze([
  { id: "overview", label: "总览" },
  { id: "applications", label: "应用与实例" },
  { id: "rules", label: "规则" },
  { id: "realtime", label: "实时监控" },
  { id: "faults", label: "故障分析" },
  { id: "system", label: "系统管理" },
]);

export const TIME_RANGES = Object.freeze(["最近 15 分钟", "最近 1 小时"]);

export const APPLICATIONS = Object.freeze([
  {
    id: "order-service",
    label: "order-service",
    state: "critical",
    stateLabel: "资源压力",
    running: 11,
    total: 12,
    cpu: 78,
    memory: 76,
    qps: 1240,
    rt: 420,
    blocked: 12.3,
    version: "v20260914-01",
    provider: "Nacos",
  },
  {
    id: "payment-service",
    label: "payment-service",
    state: "warning",
    stateLabel: "CPU 偏高",
    running: 8,
    total: 8,
    cpu: 62,
    memory: 68,
    qps: 980,
    rt: 310,
    blocked: 4.1,
    version: "v20260913-02",
    provider: "Consul",
  },
  {
    id: "user-service",
    label: "user-service",
    state: "healthy",
    stateLabel: "运行正常",
    running: 12,
    total: 12,
    cpu: 24,
    memory: 38,
    qps: 2100,
    rt: 180,
    blocked: 0.6,
    version: "v20260914-01",
    provider: "Nacos",
  },
]);

export const ORDER_INSTANCES = Object.freeze([
  {
    id: "order-1",
    host: "host-10-0-1-12",
    status: "healthy",
    statusLabel: "正常",
    cpu: 12,
    memory: 34,
    qps: 1240,
    rt: 36,
    blocked: 0.01,
    version: "v20260914-01",
  },
  {
    id: "order-2",
    host: "host-10-0-1-12",
    status: "healthy",
    statusLabel: "正常",
    cpu: 18,
    memory: 27,
    qps: 980,
    rt: 42,
    blocked: 0,
    version: "v20260914-01",
  },
  {
    id: "order-3",
    host: "host-10-0-1-12",
    status: "healthy",
    statusLabel: "正常",
    cpu: 16,
    memory: 35,
    qps: 1102,
    rt: 38,
    blocked: 0.02,
    version: "v20260914-01",
  },
  {
    id: "order-4",
    host: "host-10-0-1-12",
    status: "healthy",
    statusLabel: "正常",
    cpu: 14,
    memory: 32,
    qps: 876,
    rt: 41,
    blocked: 0,
    version: "v20260914-01",
  },
  {
    id: "order-5",
    host: "host-10-0-1-13",
    status: "critical",
    statusLabel: "CPU 高",
    cpu: 92,
    memory: 78,
    qps: 2341,
    rt: 420,
    blocked: 1.23,
    version: "v20260914-01",
  },
  {
    id: "order-6",
    host: "host-10-0-1-13",
    status: "healthy",
    statusLabel: "正常",
    cpu: 28,
    memory: 52,
    qps: 1420,
    rt: 68,
    blocked: 0.05,
    version: "v20260914-01",
  },
  {
    id: "order-7",
    host: "host-10-0-1-13",
    status: "healthy",
    statusLabel: "正常",
    cpu: 24,
    memory: 49,
    qps: 1306,
    rt: 63,
    blocked: 0.04,
    version: "v20260914-01",
  },
  {
    id: "order-8",
    host: "host-10-0-1-13",
    status: "healthy",
    statusLabel: "正常",
    cpu: 19,
    memory: 46,
    qps: 1035,
    rt: 59,
    blocked: 0.02,
    version: "v20260914-01",
  },
  {
    id: "order-9",
    host: "host-10-0-2-21",
    status: "healthy",
    statusLabel: "正常",
    cpu: 17,
    memory: 42,
    qps: 1005,
    rt: 47,
    blocked: 0.03,
    version: "v20260914-01",
  },
  {
    id: "order-10",
    host: "host-10-0-2-21",
    status: "warning",
    statusLabel: "内存高",
    cpu: 26,
    memory: 88,
    qps: 1562,
    rt: 120,
    blocked: 0.28,
    version: "v20260914-01",
  },
  {
    id: "order-11",
    host: "host-10-0-2-21",
    status: "healthy",
    statusLabel: "正常",
    cpu: 19,
    memory: 42,
    qps: 1290,
    rt: 58,
    blocked: 0.02,
    version: "v20260914-01",
  },
  {
    id: "order-12",
    host: "host-10-0-2-21",
    status: "healthy",
    statusLabel: "正常",
    cpu: 15,
    memory: 32,
    qps: 970,
    rt: 56,
    blocked: 0.02,
    version: "v20260914-01",
  },
]);

export const RULES = Object.freeze([
  {
    id: "flow-orders",
    app: "order-service",
    ruleType: "flow",
    kind: "流量控制",
    resource: "POST /api/orders",
    strategy: "QPS 直接拒绝",
    threshold: "2,000 次/秒",
    scope: "应用",
    status: "生效中",
    provider: "Nacos",
    version: "v20260914-01",
    sentinelRule: {
      resource: "POST /api/orders",
      limitApp: "default",
      grade: 1,
      count: 2000,
      strategy: 0,
      controlBehavior: 0,
      clusterMode: false,
    },
  },
  {
    id: "degrade-inventory",
    app: "order-service",
    ruleType: "degrade",
    kind: "熔断降级",
    resource: "inventory-service",
    strategy: "慢调用比例",
    threshold: "RT > 500 ms · 30%",
    scope: "应用",
    status: "生效中",
    provider: "Nacos",
    version: "v20260914-01",
    sentinelRule: {
      resource: "inventory-service",
      grade: 0,
      count: 500,
      timeWindow: 10,
      minRequestAmount: 20,
      statIntervalMs: 30000,
      slowRatioThreshold: 0.3,
    },
  },
  {
    id: "flow-checkout",
    app: "payment-service",
    ruleType: "flow",
    kind: "流量控制",
    resource: "POST /api/checkout",
    strategy: "并发控制",
    threshold: "最多 600 在途",
    scope: "应用",
    status: "生效中",
    provider: "Consul",
    version: "v20260913-02",
    sentinelRule: {
      resource: "POST /api/checkout",
      limitApp: "default",
      grade: 0,
      count: 600,
      strategy: 0,
      controlBehavior: 0,
      clusterMode: false,
    },
  },
  {
    id: "param-product",
    app: "user-service",
    ruleType: "param",
    kind: "热点参数",
    resource: "GET /api/products/{id}",
    strategy: "参数频率",
    threshold: "单值 120 次/秒",
    scope: "资源",
    status: "生效中",
    provider: "Nacos",
    version: "v20260914-01",
    sentinelRule: {
      resource: "GET /api/products/{id}",
      grade: 1,
      count: 120,
      durationInSec: 1,
      paramIdx: 0,
      paramFlowItemList: [
        {
          classType: "java.lang.String",
          object: "hot-product",
          count: 60,
        },
      ],
    },
  },
  {
    id: "authority-admin",
    app: "order-service",
    ruleType: "authority",
    kind: "访问控制",
    resource: "POST /api/admin/*",
    strategy: "来源白名单",
    threshold: "3 个可信来源",
    scope: "资源",
    status: "生效中",
    provider: "Nacos",
    version: "v20260914-01",
    sentinelRule: {
      resource: "POST /api/admin/*",
      limitApp: "admin-console,internal-job,ops-gateway",
      strategy: 0,
    },
  },
  {
    id: "system-user-service",
    app: "user-service",
    ruleType: "system",
    kind: "系统保护",
    resource: "应用入口流量",
    strategy: "入口 QPS + CPU",
    threshold: "QPS 4,000 · CPU 85%",
    scope: "应用",
    status: "生效中",
    provider: "Nacos",
    version: "v20260914-01",
    sentinelRule: {
      highestSystemLoad: -1,
      avgRt: -1,
      maxThread: -1,
      qps: 4000,
      highestCpuUsage: 0.85,
    },
  },
]);

export const RULESET_VERSIONS = Object.freeze([
  {
    id: "v20260914-01",
    name: "日常稳定基线",
    state: "active",
    stateLabel: "当前生效",
    source: "Nacos",
    publishedAt: "2026-09-14 09:20",
    summary: "6 条规则 · 日常容量基线",
    checksum: "a76c…81d4",
  },
  {
    id: "v20260930-promo",
    name: "国庆大促保护方案",
    state: "scheduled",
    stateLabel: "已计划",
    source: "Nacos",
    startsAt: "2026-09-30 19:00",
    endsAt: "2026-09-30 23:30",
    restoreVersion: "v20260914-01",
    summary: "6 条规则 · 提高保护强度",
    checksum: "d42e…5b91",
  },
  {
    id: "v20260907-03",
    name: "中秋活动方案",
    state: "superseded",
    stateLabel: "已归档",
    source: "Nacos",
    publishedAt: "2026-09-07 18:00",
    summary: "6 条规则 · 历史活动版本",
    checksum: "63ae…2f8b",
  },
]);

export const FAULT_EVENTS = Object.freeze([
  {
    id: "evt-1",
    at: "14:27:18",
    severity: "critical",
    title: "order-5 容器 CPU 持续高于 90%",
    kind: "资源压力",
    app: "order-service",
    instance: "order-5",
    detail: "CPU 持续 5 分钟高于 90%，同一时段 RT p95 上升至 420 ms。",
    action: "先核对容器限制与当前流量，再检查对应规则是否需要调整。",
  },
  {
    id: "evt-2",
    at: "14:22:04",
    severity: "warning",
    title: "order-service 规则版本未完全一致",
    kind: "规则生效",
    app: "order-service",
    instance: "order-7",
    detail:
      "一个实例在观测窗口内仍报告旧版本；配置中心写入成功不等于全部实例已应用。",
    action: "查看实例的最后上报时间和规则源健康状态。",
  },
  {
    id: "evt-3",
    at: "14:18:39",
    severity: "warning",
    title: "payment-service RT p95 上升",
    kind: "响应时间",
    app: "payment-service",
    instance: "payment-3",
    detail:
      "最近 15 分钟 p95 从 180 ms 上升至 310 ms，需结合下游和资源压力进一步排查。",
    action: "按时间线比对下游异常与规则发布。",
  },
  {
    id: "evt-4",
    at: "14:02:00",
    severity: "info",
    title: "order-service 发布规则版本 v20260914-01",
    kind: "规则发布",
    app: "order-service",
    instance: "—",
    detail: "规则内容发生变更，发布点已标注在相关趋势图中。",
    action: "查看发布差异与实例生效情况。",
  },
]);

export const CONNECTIONS = Object.freeze([
  {
    name: "Nacos",
    state: "可用",
    latency: "12 ms",
    scope: "3 个应用",
    purpose: "配置查询与规则发布",
    capability: "读写已配置",
  },
  {
    name: "Consul",
    state: "可用",
    latency: "18 ms",
    scope: "1 个应用",
    purpose: "KV 查询与条件写入",
    capability: "读写已配置",
  },
  {
    name: "指标后端",
    state: "演示模式",
    latency: "—",
    scope: "示例曲线",
    purpose: "主机、容器和进程时序指标",
    capability: "未连接真实后端",
  },
  {
    name: "Agent Reporting",
    state: "演示模式",
    latency: "—",
    scope: "示例事件",
    purpose: "实例版本与故障事件",
    capability: "未连接真实 Collector",
  },
]);

export const numberText = (value) =>
  new Intl.NumberFormat("zh-CN").format(value);

export function makeTrendSeries(pointCount = 61) {
  return Array.from({ length: pointCount }, (_, index) => {
    const minute =
      13 * 60 + 32 + Math.round((index * 60) / Math.max(1, pointCount - 1));
    const time = `${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;
    const postRelease = minute >= 14 * 60 + 2;
    const wave = Math.sin(index * 0.87) * 850 + Math.sin(index * 2.1) * 410;
    return {
      time,
      qps: Math.round((postRelease ? 15000 : 22900) + wave + index * 45),
      blocked: Number(
        ((postRelease ? 8.7 : 1.8) + Math.sin(index * 0.9) * 0.5).toFixed(2),
      ),
      cpu: Math.round(
        (postRelease ? 54 : 43) + index * 0.12 + Math.sin(index * 0.8) * 3,
      ),
      memory: Math.round(48 + index * 0.15 + Math.sin(index * 0.5) * 2),
      rt: Math.round(
        (postRelease ? 182 : 102) + Math.sin(index * 0.55) * 12 + index * 0.1,
      ),
    };
  });
}

export const FLEET_TREND = Object.freeze(makeTrendSeries());

export function seriesForRange(series, range) {
  return range === "最近 15 分钟" ? series.slice(-16) : series;
}

export function makeInstanceTrend(instance) {
  const highPressure = instance.status === "critical";
  return FLEET_TREND.map((item, index) => ({
    ...item,
    cpu: Math.min(
      100,
      Math.round(
        instance.cpu * (highPressure ? 0.62 : 0.75) +
          (index / 60) * instance.cpu * (highPressure ? 0.38 : 0.25) +
          Math.sin(index * 0.7) * 3,
      ),
    ),
    memory: Math.min(
      100,
      Math.round(
        instance.memory * (0.72 + (index / 60) * 0.28) +
          Math.sin(index * 0.38) * 2,
      ),
    ),
    qps: Math.max(
      0,
      Math.round(
        instance.qps * (0.55 + (index / 60) * 0.45) +
          Math.sin(index * 0.8) * 60,
      ),
    ),
    blocked: Number(
      Math.max(0, instance.blocked * (0.25 + (index / 60) * 0.75)).toFixed(2),
    ),
    rt: Math.max(
      0,
      Math.round(
        instance.rt * (0.65 + (index / 60) * 0.35) + Math.sin(index * 0.55) * 6,
      ),
    ),
  }));
}
