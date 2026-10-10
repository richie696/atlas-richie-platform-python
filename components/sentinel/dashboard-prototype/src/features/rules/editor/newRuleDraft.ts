import {
  RULE_KIND,
  SentinelCode,
  DISABLED_SYSTEM_THRESHOLD,
  type RuleKind,
} from "../model/ruleKinds";
import type { TypedRuleDraft } from "./ruleDraft";
const DEFAULT_ORIGIN = "default";
/** Empty numeric fields require deliberate values. These are new-form defaults, never a live configuration seed. */
export function newRuleDraft(kind: RuleKind): TypedRuleDraft {
  switch (kind) {
    case RULE_KIND.Flow:
      return {
        kind,
        draft: {
          resource: "",
          limitApp: DEFAULT_ORIGIN,
          grade: SentinelCode.FLOW_GRADE_QPS,
          count: "",
          strategy: SentinelCode.FLOW_STRATEGY_DIRECT,
          controlBehavior: SentinelCode.FLOW_BEHAVIOR_REJECT,
          clusterMode: false,
        },
      };
    case RULE_KIND.Degrade:
      return {
        kind,
        draft: {
          resource: "",
          grade: SentinelCode.DEGRADE_SLOW_REQUEST_RATIO,
          count: "",
          timeWindow: "",
          minRequestAmount: "",
          statIntervalMs: "",
          slowRatioThreshold: "",
        },
      };
    case RULE_KIND.System:
      return {
        kind,
        draft: {
          highestSystemLoad: DISABLED_SYSTEM_THRESHOLD,
          avgRt: DISABLED_SYSTEM_THRESHOLD,
          maxThread: DISABLED_SYSTEM_THRESHOLD,
          qps: DISABLED_SYSTEM_THRESHOLD,
          highestCpuUsage: DISABLED_SYSTEM_THRESHOLD,
        },
      };
    case RULE_KIND.Authority:
      return {
        kind,
        draft: { resource: "", limitApp: "", strategy: SentinelCode.AUTHORITY_WHITE },
      };
    case RULE_KIND.ParamFlow:
      return {
        kind,
        draft: {
          resource: "",
          grade: SentinelCode.FLOW_GRADE_QPS,
          count: "",
          durationInSec: "",
          paramIdx: "",
          paramFlowItemList: [],
        },
      };
  }
}
