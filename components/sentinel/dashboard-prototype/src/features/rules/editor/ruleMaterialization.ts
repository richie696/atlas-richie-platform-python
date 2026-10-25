import { RULE_KIND, SentinelCode } from "../model/ruleKinds";
import { validateRuleDraft, finiteDraftNumber, type RuleIssue } from "./rulePolicy";
import type { TypedRuleDraft } from "./ruleDraft";
import type { TypedRuleValue } from "../model/ruleValue";

/** Local materialization is not server codec/capability validation or a publish authorization. */
export type RuleMaterialization =
  | { readonly valid: false; readonly issues: readonly RuleIssue[] }
  | { readonly valid: true; readonly rule: TypedRuleValue };

/** Convert only validated active fields. No undefined-as-zero, conditional garbage or form identities enter facts. */
export function materializeRuleDraft(rule: TypedRuleDraft): RuleMaterialization {
  const issues = validateRuleDraft(rule);
  if (issues.length) return { valid: false, issues };
  // Every active numeric input has passed the shared policy; inactive values are never read here.
  const number = (value: unknown) => finiteDraftNumber(value)!;
  switch (rule.kind) {
    case RULE_KIND.Flow: {
      const value = rule.draft;
      return {
        valid: true,
        rule: {
          kind: RULE_KIND.Flow,
          value: {
            resource: value.resource,
            limitApp: value.limitApp,
            grade: value.grade,
            count: number(value.count),
            strategy: value.strategy,
            controlBehavior: value.controlBehavior,
            clusterMode: value.clusterMode,
            ...(value.strategy === SentinelCode.FLOW_STRATEGY_DIRECT
              ? {}
              : { refResource: value.refResource! }),
            ...(value.controlBehavior === SentinelCode.FLOW_BEHAVIOR_WARM_UP
              ? { warmUpPeriodSec: number(value.warmUpPeriodSec) }
              : {}),
            ...(value.controlBehavior === SentinelCode.FLOW_BEHAVIOR_QUEUEING
              ? { maxQueueingTimeMs: number(value.maxQueueingTimeMs) }
              : {}),
            ...(value.clusterMode
              ? {
                  clusterConfig: {
                    thresholdType: value.clusterConfig!.thresholdType,
                    fallbackToLocalWhenFail: value.clusterConfig!.fallbackToLocalWhenFail,
                    sampleCount: number(value.clusterConfig!.sampleCount),
                    windowIntervalMs: number(value.clusterConfig!.windowIntervalMs),
                  },
                }
              : {}),
          },
        },
      };
    }
    case RULE_KIND.Degrade: {
      const value = rule.draft;
      return {
        valid: true,
        rule: {
          kind: RULE_KIND.Degrade,
          value: {
            resource: value.resource,
            grade: value.grade,
            count: number(value.count),
            timeWindow: number(value.timeWindow),
            minRequestAmount: number(value.minRequestAmount),
            statIntervalMs: number(value.statIntervalMs),
            ...(value.grade === SentinelCode.DEGRADE_SLOW_REQUEST_RATIO
              ? { slowRatioThreshold: number(value.slowRatioThreshold) }
              : {}),
          },
        },
      };
    }
    case RULE_KIND.System: {
      const value = rule.draft;
      return {
        valid: true,
        rule: {
          kind: RULE_KIND.System,
          value: {
            highestSystemLoad: number(value.highestSystemLoad),
            avgRt: number(value.avgRt),
            maxThread: number(value.maxThread),
            qps: number(value.qps),
            highestCpuUsage: number(value.highestCpuUsage),
          },
        },
      };
    }
    case RULE_KIND.Authority: {
      const value = rule.draft;
      return {
        valid: true,
        rule: {
          kind: RULE_KIND.Authority,
          value: {
            resource: value.resource,
            strategy: value.strategy,
            limitApp: value.limitApp
              .split(",")
              .map((item) => item.trim())
              .join(","),
          },
        },
      };
    }
    case RULE_KIND.ParamFlow: {
      const value = rule.draft;
      return {
        valid: true,
        rule: {
          kind: RULE_KIND.ParamFlow,
          value: {
            resource: value.resource,
            grade: value.grade,
            count: number(value.count),
            durationInSec: number(value.durationInSec),
            paramIdx: number(value.paramIdx),
            paramFlowItemList: value.paramFlowItemList.map((item) => ({
              classType: item.classType.trim(),
              object: item.object,
              count: number(item.count),
            })),
          },
        },
      };
    }
  }
}

/** Editable copy of one numeric record. Form identity is local and never becomes a rule id. */
export function editableRule(
  rule: TypedRuleValue,
  keyOfItem: (index: number) => string,
): TypedRuleDraft {
  switch (rule.kind) {
    case RULE_KIND.Flow:
      return { kind: rule.kind, draft: structuredClone(rule.value) };
    case RULE_KIND.Degrade:
      return { kind: rule.kind, draft: structuredClone(rule.value) };
    case RULE_KIND.System:
      return { kind: rule.kind, draft: structuredClone(rule.value) };
    case RULE_KIND.Authority:
      return { kind: rule.kind, draft: structuredClone(rule.value) };
    case RULE_KIND.ParamFlow:
      return {
        kind: rule.kind,
        draft: {
          ...structuredClone(rule.value),
          paramFlowItemList: rule.value.paramFlowItemList.map((item, index) => ({
            ...item,
            formKey: keyOfItem(index),
          })),
        },
      };
  }
}
