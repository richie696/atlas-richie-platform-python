/**
 * 规则工作台的演示数据。
 *
 * 中文
 * ----
 * fixture 只在本目录与测试中使用；生产代码路径不导入它
 * （`REACT_PROJECT_SKELETON` §2：`fixtures/` 是显式测试/演示数据）。
 * 接入 Console API 后本文件整体删除，目录数据改由 `rules.gateway` 提供。
 *
 * 所有数值都是**示例**，不代表任何真实部署：`sentinelRule` 里的字段会原样进入
 * 配置中心预览，因此这里刻意覆盖五类规则各自的典型形态（含 FlowRule 的集群模式、
 * DegradeRule 的慢调用比例、ParamFlowRule 的例外项），以便校验逻辑能被真实触发。
 */
import type { RuleWorkbenchEntry } from "../state/useRuleWorkbench";
import { RULE_KIND, RULE_SCOPE, RULE_SOURCE } from "../model/ruleKinds";
import { VERSION_STATE, type RuleVersion } from "../model/ruleVersion";

export const RULE_FIXTURES: readonly RuleWorkbenchEntry[] = Object.freeze([
  {
    id: "flow-orders",
    app: "order-service",
    ruleType: RULE_KIND.Flow,
    resource: "POST /api/orders",
    strategy: "QPS 直接拒绝",
    threshold: "2,000 次/秒",
    scope: RULE_SCOPE.Application,
    provider: RULE_SOURCE.Nacos,
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
    ruleType: RULE_KIND.Degrade,
    resource: "inventory-service",
    strategy: "慢调用比例",
    threshold: "RT > 500 ms · 30%",
    scope: RULE_SCOPE.Application,
    provider: RULE_SOURCE.Nacos,
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
    ruleType: RULE_KIND.Flow,
    resource: "POST /api/checkout",
    strategy: "并发控制",
    threshold: "最多 600 在途",
    scope: RULE_SCOPE.Application,
    provider: RULE_SOURCE.Consul,
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
    ruleType: RULE_KIND.ParamFlow,
    resource: "GET /api/products/{id}",
    strategy: "参数频率",
    threshold: "单值 120 次/秒",
    scope: RULE_SCOPE.Resource,
    provider: RULE_SOURCE.Nacos,
    version: "v20260914-01",
    sentinelRule: {
      resource: "GET /api/products/{id}",
      grade: 1,
      count: 120,
      durationInSec: 1,
      paramIdx: 0,
      paramFlowItemList: [
        { classType: "java.lang.String", object: "hot-product", count: 60 },
      ],
    },
  },
  {
    id: "authority-admin",
    app: "order-service",
    ruleType: RULE_KIND.Authority,
    resource: "POST /api/admin/*",
    strategy: "来源白名单",
    threshold: "3 个可信来源",
    scope: RULE_SCOPE.Resource,
    provider: RULE_SOURCE.Nacos,
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
    ruleType: RULE_KIND.System,
    resource: "应用入口流量",
    strategy: "入口 QPS + CPU",
    threshold: "QPS 4,000 · CPU 85%",
    scope: RULE_SCOPE.Application,
    provider: RULE_SOURCE.Nacos,
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

/**
 * 规则集版本。
 *
 * `checksum` 是**示例字符串**，不是真实校验和：生产环境由服务端对规范化后的完整
 * 快照计算，客户端不生成也不校验它。
 */
export const RULE_VERSION_FIXTURES: readonly RuleVersion[] = Object.freeze([
  {
    id: "v20260914-01",
    name: "日常稳定基线",
    state: VERSION_STATE.Active,
    source: RULE_SOURCE.Nacos,
    publishedAt: "2026-09-14 09:20",
    summary: "6 条规则 · 日常容量基线",
    checksum: "a76c…81d4",
  },
  {
    id: "v20260930-promo",
    name: "国庆大促保护方案",
    state: VERSION_STATE.Scheduled,
    source: RULE_SOURCE.Nacos,
    startsAt: "2026-09-30 19:00",
    endsAt: "2026-09-30 23:30",
    restoreVersion: "v20260914-01",
    summary: "6 条规则 · 提高保护强度",
    checksum: "d42e…5b91",
  },
  {
    id: "v20260907-03",
    name: "中秋活动方案",
    state: VERSION_STATE.Superseded,
    source: RULE_SOURCE.Nacos,
    publishedAt: "2026-09-07 18:00",
    summary: "6 条规则 · 历史活动版本",
    checksum: "63ae…2f8b",
  },
]);

/**
 * 规则工作台可见的应用目录。
 *
 * 从规则条目派生而不是读取全局应用表：规则页能看到的应用，恰好是**存在规则绑定**
 * 的应用。这与 `DASHBOARD_CONTROL_PLANE.md` §4.2「规则页读模型 = 配置中心权威快照 +
 * 来源/版本」一致，也让筛选下拉不会列出没有任何规则的应用。
 */
export const RULE_APP_FIXTURES: readonly { readonly id: string; readonly label: string }[] =
  Object.freeze(
    [...new Set(RULE_FIXTURES.map((entry) => entry.app))]
      .sort()
      .map((id) => Object.freeze({ id, label: id })),
  );
