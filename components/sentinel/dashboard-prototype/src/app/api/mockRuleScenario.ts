/** Canonical rule-workbench demo facts; imported only by the app's explicit Mock assembly. */
import { MOCK_OBSERVATION_SCENARIO } from "./mockObservationScenario";
import { MOCK_SYSTEM_SCENARIO } from "./mockSystemScenario";
import { RULE_KIND, SentinelCode } from "../../features/rules/mock";
import type {
  RuleBinding,
  RuleKind,
  RuleRecord,
  RuleSetMockScenario,
  RuleSetSnapshot,
} from "../../features/rules/mock";

const RULE_BINDINGS: readonly RuleBinding[] = Object.freeze(
  [
    RULE_KIND.Flow,
    RULE_KIND.Degrade,
    RULE_KIND.System,
    RULE_KIND.Authority,
    RULE_KIND.ParamFlow,
  ].map((kind) =>
    Object.freeze({
      id:
        kind === RULE_KIND.Flow
          ? `binding-${MOCK_SYSTEM_SCENARIO.applicationId}`
          : `binding-${MOCK_SYSTEM_SCENARIO.applicationId}-${kind}`,
      environmentId: MOCK_OBSERVATION_SCENARIO.environment.id,
      appId: MOCK_SYSTEM_SCENARIO.applicationId,
      kind,
      profile: "sentinel-python-v1",
      sourceId: MOCK_SYSTEM_SCENARIO.primarySource.id,
      sourceLabel: MOCK_SYSTEM_SCENARIO.primarySource.name,
      location: `sentinel/rules/${MOCK_SYSTEM_SCENARIO.applicationId}/${kind}`,
    }),
  ),
);

function initialRule(kind: RuleKind): RuleRecord["rule"] {
  switch (kind) {
    case RULE_KIND.Flow:
      return {
        kind,
        value: {
          resource: "POST /api/orders",
          limitApp: "default",
          grade: SentinelCode.FLOW_GRADE_QPS,
          count: 2000,
          strategy: SentinelCode.FLOW_STRATEGY_DIRECT,
          controlBehavior: SentinelCode.FLOW_BEHAVIOR_REJECT,
          clusterMode: false,
        },
      };
    case RULE_KIND.Degrade:
      return {
        kind,
        value: {
          resource: "inventory-service",
          grade: SentinelCode.DEGRADE_SLOW_REQUEST_RATIO,
          count: 500,
          timeWindow: 10,
          minRequestAmount: 20,
          statIntervalMs: 30000,
          slowRatioThreshold: 0.3,
        },
      };
    case RULE_KIND.System:
      return {
        kind,
        value: {
          highestSystemLoad: SentinelCode.DISABLED_SYSTEM_THRESHOLD,
          avgRt: SentinelCode.DISABLED_SYSTEM_THRESHOLD,
          maxThread: SentinelCode.DISABLED_SYSTEM_THRESHOLD,
          qps: 4000,
          highestCpuUsage: 0.85,
        },
      };
    case RULE_KIND.Authority:
      return {
        kind,
        value: {
          resource: "POST /api/admin/*",
          limitApp: "admin-console,internal-job",
          strategy: SentinelCode.AUTHORITY_WHITE,
        },
      };
    case RULE_KIND.ParamFlow:
      return {
        kind,
        value: {
          resource: "GET /api/products/{id}",
          grade: SentinelCode.FLOW_GRADE_QPS,
          count: 120,
          durationInSec: 1,
          paramIdx: 0,
          paramFlowItemList: [{ classType: "builtins.str", object: "hot-product", count: 60 }],
        },
      };
  }
}

const RULE_SNAPSHOTS: readonly RuleSetSnapshot[] = Object.freeze(
  RULE_BINDINGS.map((binding, index) =>
    Object.freeze({
      binding,
      versionId: "version-one",
      checksum: `server-checksum-${binding.kind}`,
      sourceRevision: `source-revision-${binding.kind}`,
      asOfMs: MOCK_OBSERVATION_SCENARIO.window.fromMs + 5 * 60_000 + index,
      records: Object.freeze([
        Object.freeze({ id: `rule-${binding.kind}`, rule: initialRule(binding.kind) }),
      ]),
    }),
  ),
);

const eventBindingId = `binding-${MOCK_SYSTEM_SCENARIO.applicationId}`;
const eventSnapshot = RULE_SNAPSHOTS.find((snapshot) => snapshot.binding.id === eventBindingId);
if (!eventSnapshot)
  throw new Error("The demo rule scenario must contain its event binding snapshot");
const appliedInstance = MOCK_OBSERVATION_SCENARIO.instances.find(
  (instance) => instance.appId === MOCK_SYSTEM_SCENARIO.applicationId,
);
if (!appliedInstance)
  throw new Error("The demo rule scenario requires an instance from its selected application");

const EVENT_VERSION_RECORDS: readonly RuleRecord[] = Object.freeze(
  eventSnapshot.records.map((record) => {
    if (record.rule.kind !== RULE_KIND.Flow)
      throw new Error("The event-version demo seed requires its Flow binding");
    return Object.freeze({
      id: record.id,
      rule: {
        kind: RULE_KIND.Flow,
        value: { ...record.rule.value, count: 1500 },
      },
    });
  }),
);

/** Complete immutable rule facts used by the demo HTTP simulator. */
export const MOCK_RULE_SCENARIO: RuleSetMockScenario = Object.freeze({
  ...MOCK_OBSERVATION_SCENARIO,
  bindings: RULE_BINDINGS,
  snapshots: RULE_SNAPSHOTS,
  deployment: Object.freeze({
    baselineVersion: Object.freeze({
      id: "version-one",
      name: "示例基线",
      note: "仅供界面演示使用；这是不可变的规则内容快照。",
    }),
    baselinePublication: Object.freeze({
      id: "publication-20261007-01",
      createdAt: new Date(eventSnapshot.asOfMs).toISOString(),
      phaseState: "succeeded" as const,
    }),
    eventVersion: Object.freeze({
      id: "version-event-flow",
      bindingId: eventBindingId,
      baseVersionId: "version-one",
      checksum: "demo-checksum-flow-event",
      name: "演练活动版",
      note: "用于演示限时发布；计划结束后明确恢复到示例基线。",
      createdAtOffsetMs: 1000,
      records: EVENT_VERSION_RECORDS,
    }),
    eventPublication: Object.freeze({
      id: "publication-event-flow-01",
      createdAtOffsetMs: 2000,
      phaseState: "succeeded" as const,
    }),
    receipt: Object.freeze({
      publicationId: "publication-event-flow-01",
      appliedInstanceId: appliedInstance.id,
      appliedState: "applied" as const,
      pendingState: "pending" as const,
      appliedAtOffsetMs: -60_000,
      lastReportAtOffsetMs: -10_000,
    }),
    initialPlan: Object.freeze({
      id: "plan-event-flow-01",
      revision: "plan-event-flow-r1",
      versionId: "version-event-flow",
      restoreVersionId: "version-one",
      activateAfterMs: 60 * 60_000,
      durationMs: 60 * 60_000,
      timeZone: "Asia/Shanghai",
      state: "pending" as const,
    }),
  }),
});
