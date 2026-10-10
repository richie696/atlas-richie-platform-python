import type { RuleSetSnapshot } from "../../src/features/rules/model/ruleSet";
import { RULE_KIND, SentinelCode } from "../../src/features/rules/model/ruleKinds";
import type { FlowRuleValue } from "../../src/features/rules/model/ruleValue";
export const flowValue: FlowRuleValue = {
  resource: "POST /orders",
  limitApp: "default",
  grade: SentinelCode.FLOW_GRADE_QPS,
  count: 20,
  strategy: SentinelCode.FLOW_STRATEGY_DIRECT,
  controlBehavior: SentinelCode.FLOW_BEHAVIOR_REJECT,
  clusterMode: false,
};
/** Synthetic full-set facts. No production seed or manufactured client version/checksum computation. */
export const ruleSet: RuleSetSnapshot = {
  binding: {
    id: "binding-one",
    environmentId: "test-env",
    appId: "app-one",
    kind: RULE_KIND.Flow,
    profile: "test-profile",
    sourceId: "source-one",
    sourceLabel: "Test configuration source",
    location: "test-redacted-location",
  },
  versionId: "version-one",
  checksum: "server-checksum-one",
  sourceRevision: "opaque-source-revision",
  asOfMs: 1791331800000,
  records: [
    { id: "rule-one", rule: { kind: RULE_KIND.Flow, value: flowValue } },
    {
      id: "rule-two",
      rule: { kind: RULE_KIND.Flow, value: { ...flowValue, resource: "GET /orders", count: 40 } },
    },
  ],
};
