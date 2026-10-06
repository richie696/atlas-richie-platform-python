/**
 * fixture-backed 的控制台网关。
 *
 * 中文
 * ----
 * 从各 feature 的 `fixtures/` 目录读数据，**模拟异步与延迟**，让页面的取数路径
 * 先跑通一遍真实形态（Promise、loading、错误分支），而不是继续让页面
 * `import { X_FIXTURES }` ——后者在接真实控制面时 7 个页面都得改。
 *
 * 它是**契约的可执行副本**：`docs/CONSOLE_API_CONTRACT.md` 写了返回形状，这里
 * 按同样的形状产出数据。契约改了这里要一起改，反过来也一样；两者不一致时
 * 页面会在接真服务端的那一刻炸掉，而不是在这里。
 *
 * ## 为什么现在不直接发 HTTP
 *
 * 控制面服务不存在（§6.1 契约先行）。但「页面直接 import fixtures」这个现状
 * 本身就是个隐患：数据来源渗透进了 7 个页面的 import 图，将来替换成本高。
 * 先把边界画出来，服务端到位时只换这一个文件。
 */
import type { ApplicationRecord } from "../../features/applications/model/instance";
import type { ApplicationSummary } from "../../features/overview/model/overview";
import {
  APPLICATION_SUMMARIES,
  FLEET_ATTENTION,
  FLEET_TREND,
  INFRA_STATUS,
  seriesForRange,
} from "../../features/overview/fixtures/overviewFixtures";
import type { FleetAttention } from "../../features/overview/model/overview";
import { INITIAL_ACCOUNTS, NEW_ACCOUNT_LAST_LOGIN } from "../../features/identity/fixtures/identityFixtures";
import { IDENTITY_ROLES } from "../../features/identity/model/account";
import { INCIDENT_FIXTURES, FAULTS_APP_FIXTURES } from "../../features/faults/fixtures/faultsFixtures";
import {
  APPLICATION_FIXTURES,
  ORDER_INSTANCE_FIXTURES,
  readInstanceSeries,
} from "../../features/applications/fixtures/applicationsFixtures";
// realtime 的 `FLEET_TREND` / `seriesForRange` 与 overview 的**同名但不同源**：
// 前者由 `makeTrendSeries()` 自生成，后者来自 overview 的演示序列。两个 feature
// 各有一份趋势数据是既有事实，这里用别名区分，避免 gateway 里静默取错那一份。
import {
  FLEET_TREND as REALTIME_TREND,
  REALTIME_APP_FIXTURES,
  REALTIME_SUMMARY_FIXTURES,
  seriesForRange as sliceRealtimeByRange,
} from "../../features/realtime/fixtures/realtimeFixtures";
import {
  RULE_APP_FIXTURES,
  RULE_FIXTURES,
  RULE_VERSION_FIXTURES,
} from "../../features/rules/fixtures/ruleFixtures";
import { CONNECTIONS, CONNECTION_SUMMARY_CARDS } from "../../features/system/fixtures/systemFixtures";
import type { InfraStatus } from "../../features/overview/model/overview";
import type { MetricPoint } from "../../shared/types/dashboard";
import { ApiError, type ConsoleGateway, type MetricQuery, type ScopedMetric } from "./contracts";

/**
 * 模拟的网络延迟。
 *
 * 不是装饰：页面需要真的经历一段「数据未到」的时段，否则 loading 与错误分支
 * 在接真服务端之前永远走不到，等于没有测过。0ms 会让这两个分支变成死代码。
 */
const SIMULATED_LATENCY_MS = 120;

function respond<T>(value: T, delay = SIMULATED_LATENCY_MS): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), delay));
}

/**
 * 指标未接入时的读数。
 *
 * 契约 §4：未接入的主机 / TPS 指标必须明确不可用，**不得**用 0 或空数组伪装。
 * 因此这里返回空点列 + 空 `source`，由页面显示「未接入」。
 */
const NOT_INTEGRATED: ScopedMetric = Object.freeze({
  points: Object.freeze([]) as readonly MetricPoint[],
  unit: "",
  scope: "",
  source: "",
  sampledAt: "",
});

export interface FixtureGateway extends ConsoleGateway {
  /**
   * 同步快照读取。
   *
   * 中文
   * ----
   * 页面首屏用它而不是 `await`：本原型要求「重构不得改变任何页面的展示效果」，
   * 而异步取数会让首帧多一个 loading 态，那本身就是展示变化。
   *
   * 真实控制面到位后，这两个方法的差别正是「首屏数据从哪来」的问题——
   * 到那时页面只需要在这一个文件里决定用同步兜底还是异步刷新，页面不用动。
   * 这就是先画边界的收益：不画边界，将来 7 个页面各写一套加载逻辑。
   */
  readFleetOverviewSync(): {
    applications: readonly ApplicationSummary[];
    attention: FleetAttention;
    infra: readonly InfraStatus[];
    trend: typeof FLEET_TREND;
    seriesForRange: typeof seriesForRange;
  };
  /** 总览页读模型。契约里对应 `/metrics/query` + `/system/connections` 的组合。 */
  getFleetOverview(): Promise<{
    applications: readonly ApplicationSummary[];
    attention: FleetAttention;
    infra: readonly InfraStatus[];
  }>;
  /** 应用与实例页读模型。 */
  getApplications(): Promise<readonly ApplicationRecord[]>;

  /** 其余五个页面的同步快照，形态与 `readFleetOverviewSync` 相同。 */
  readApplicationsSync(): typeof APPLICATIONS_SNAPSHOT;
  readRealtimeSync(): typeof REALTIME_SNAPSHOT;
  readFaultsSync(): typeof FAULTS_SNAPSHOT;
  readSystemSync(): typeof SYSTEM_SNAPSHOT;
  readRulesSync(): typeof RULES_SNAPSHOT;
  readAccountsSync(): typeof ACCOUNTS_SNAPSHOT;
}

/**
 * 各页的同步快照。
 *
 * 中文
 * ----
 * **形状就是各页面现在从 fixtures 拿到的那些值，一个不多一个不少。**
 * 不在这里做转换或归一——转换属于 gateway 的职责，但它必须先有真实的数据来源
 * 才能做；现在来源就是 fixtures，转换也就无从谈起。
 */
const APPLICATIONS_SNAPSHOT = Object.freeze({
  applications: APPLICATION_FIXTURES,
  instances: ORDER_INSTANCE_FIXTURES,
  readSeries: readInstanceSeries,
});

const REALTIME_SNAPSHOT = Object.freeze({
  trend: REALTIME_TREND,
  applications: REALTIME_APP_FIXTURES,
  summaryCards: REALTIME_SUMMARY_FIXTURES,
  sliceByRange: sliceRealtimeByRange,
});

const FAULTS_SNAPSHOT = Object.freeze({
  incidents: INCIDENT_FIXTURES,
  applications: FAULTS_APP_FIXTURES,
});

const SYSTEM_SNAPSHOT = Object.freeze({
  connections: CONNECTIONS,
  summaryCards: CONNECTION_SUMMARY_CARDS,
});

const RULES_SNAPSHOT = Object.freeze({
  applications: RULE_APP_FIXTURES,
  rules: RULE_FIXTURES,
  versions: RULE_VERSION_FIXTURES,
});

const ACCOUNTS_SNAPSHOT = Object.freeze({
  accounts: INITIAL_ACCOUNTS,
  newAccountLastLogin: NEW_ACCOUNT_LAST_LOGIN,
});

export const fixtureGateway: FixtureGateway = {
  readApplicationsSync() {
    return APPLICATIONS_SNAPSHOT;
  },
  readRealtimeSync() {
    return REALTIME_SNAPSHOT;
  },
  readFaultsSync() {
    return FAULTS_SNAPSHOT;
  },
  readSystemSync() {
    return SYSTEM_SNAPSHOT;
  },
  readRulesSync() {
    return RULES_SNAPSHOT;
  },
  readAccountsSync() {
    return ACCOUNTS_SNAPSHOT;
  },

  readFleetOverviewSync() {
    return {
      applications: APPLICATION_SUMMARIES,
      attention: FLEET_ATTENTION,
      infra: INFRA_STATUS,
      trend: FLEET_TREND,
      seriesForRange,
    };
  },

  getRuleSnapshot() {
    // 契约 §3：快照是**整体替换**而非增量。这里尚未实现发布，先返回空并说明。
    return respond<unknown>(
      // 规则快照的真实结构由 `docs/CONSOLE_API_CONTRACT.md` §2 的映射表决定，
      // 服务端到位前不臆造形状。
      Object.freeze({}),
    );
  },

  getConnections() {
    return respond<readonly InfraStatus[]>(INFRA_STATUS);
  },

  getPermissions() {
    return respond(
      IDENTITY_ROLES.map((role) => ({
        roleId: role.id,
        capabilities: [...role.permissions],
      })),
    );
  },

  queryMetrics(_query: MetricQuery) {
    // 契约 §4：没有采集源时明确不可用，不用 0 值伪装无流量。
    void _query;
    return respond<ScopedMetric>(NOT_INTEGRATED);
  },

  getFleetOverview() {
    return respond({
      applications: APPLICATION_SUMMARIES,
      attention: FLEET_ATTENTION,
      infra: INFRA_STATUS,
    });
  },

  getApplications() {
    return respond<readonly ApplicationRecord[]>(APPLICATION_FIXTURES);
  },
};

/** 鉴权与配置中心故障时的错误样例，供页面分支测试使用。 */
export const capabilityDenied = (capability: string): ApiError =>
  new ApiError("capability_denied", `缺少能力 ${capability}`, capability);