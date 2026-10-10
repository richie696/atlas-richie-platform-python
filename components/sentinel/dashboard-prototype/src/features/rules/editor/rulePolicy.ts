/** Pure, category-correlated form policy. No React, transport, labels or translation keys. */
import {
  DISABLED_SYSTEM_THRESHOLD,
  RULE_KIND,
  RULE_KIND_ALL,
  SentinelCode,
  type RuleKind,
  type RuleKindFilter,
} from "../model/ruleKinds";
import type { TypedRuleDraft } from "./ruleDraft";
import {
  AUTHORITY_VALUES,
  DEGRADE_VALUES,
  FLOW_BEHAVIOR_VALUES,
  FLOW_GRADE_VALUES,
  FLOW_STRATEGY_VALUES,
} from "../model/ruleOptions";

/** Stable internal issue codes; presentation owns their localized messages. */
export const RULE_ISSUE = Object.freeze({
  ResourceRequired: "resource-required",
  Positive: "positive",
  ReferenceRequired: "reference-required",
  Ratio: "ratio",
  PositiveRatio: "positive-ratio",
  NonNegative: "non-negative",
  ParameterIndex: "parameter-index",
  OriginsRequired: "origins-required",
  SystemEnabled: "system-enabled",
  Number: "number",
  Integer: "integer",
  Choice: "choice",
  Required: "required",
  Window: "window",
  Duplicate: "duplicate",
} as const);
export type RuleIssueCode = (typeof RULE_ISSUE)[keyof typeof RULE_ISSUE];

/** A path identifies a field, never includes user-supplied content. */
export interface RuleIssue {
  readonly code: RuleIssueCode;
  readonly path: string;
}

/** Empty/boolean/null values are not numeric zero. Numeric strings are permitted only in drafts. */
export function finiteDraftNumber(value: unknown): number | null {
  if (typeof value !== "number" && typeof value !== "string") return null;
  if (typeof value === "string" && !value.trim()) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

const SYSTEM_THRESHOLDS = [
  "highestSystemLoad",
  "avgRt",
  "maxThread",
  "qps",
  "highestCpuUsage",
] as const;

/**
 * Validate a local editable draft, not external JSON. Positive thresholds are this product's
 * existing editing policy; they are not a claim that all Java Sentinel zero thresholds are invalid.
 * Inactive conditional values are ignored here and must be omitted by the later wire mapper.
 * Server capability/codec validation, source conflicts and publication remain server responsibilities.
 */
export function validateRuleDraft(rule: TypedRuleDraft): readonly RuleIssue[] {
  const issues: RuleIssue[] = [];
  const push = (code: RuleIssueCode, path: string) => {
    issues.push({ code, path });
  };
  const required = (value: string, path: string, code: RuleIssueCode = RULE_ISSUE.Required) => {
    if (!value.trim()) push(code, path);
  };
  const choice = (value: number | string, allowed: readonly number[], path: string) => {
    // Enumerations must be actual numeric codes; free-text numeric coercion is not a valid choice.
    if (typeof value !== "number" || !allowed.includes(value)) push(RULE_ISSUE.Choice, path);
  };
  const numeric = (
    value: unknown,
    path: string,
    minimum: number,
    integer = false,
    maximum = Infinity,
    exclusive = false,
  ) => {
    const number = finiteDraftNumber(value);
    if (number === null) push(RULE_ISSUE.Number, path);
    else if (integer && !Number.isSafeInteger(number)) push(RULE_ISSUE.Integer, path);
    else if ((exclusive ? number <= minimum : number < minimum) || number > maximum)
      push(
        maximum === 1
          ? exclusive
            ? RULE_ISSUE.PositiveRatio
            : RULE_ISSUE.Ratio
          : exclusive
            ? RULE_ISSUE.Positive
            : RULE_ISSUE.NonNegative,
        path,
      );
    return number;
  };

  if (rule.kind !== RULE_KIND.System)
    required(rule.draft.resource, "resource", RULE_ISSUE.ResourceRequired);
  switch (rule.kind) {
    case RULE_KIND.Flow: {
      const draft = rule.draft;
      required(draft.limitApp, "limitApp", RULE_ISSUE.OriginsRequired);
      choice(draft.grade, FLOW_GRADE_VALUES, "grade");
      choice(draft.strategy, FLOW_STRATEGY_VALUES, "strategy");
      choice(draft.controlBehavior, FLOW_BEHAVIOR_VALUES, "controlBehavior");
      numeric(
        draft.count,
        "count",
        0,
        draft.grade === SentinelCode.FLOW_GRADE_THREAD,
        Infinity,
        true,
      );
      if (draft.strategy !== SentinelCode.FLOW_STRATEGY_DIRECT)
        required(draft.refResource ?? "", "refResource", RULE_ISSUE.ReferenceRequired);
      if (draft.controlBehavior === SentinelCode.FLOW_BEHAVIOR_WARM_UP)
        numeric(draft.warmUpPeriodSec, "warmUpPeriodSec", 0, true, Infinity, true);
      if (draft.controlBehavior === SentinelCode.FLOW_BEHAVIOR_QUEUEING)
        numeric(draft.maxQueueingTimeMs, "maxQueueingTimeMs", 0, true, Infinity, true);
      if (draft.clusterMode) {
        const cluster = draft.clusterConfig;
        if (!cluster) {
          push(RULE_ISSUE.Required, "clusterConfig");
          break;
        }
        choice(
          cluster.thresholdType,
          [SentinelCode.CLUSTER_THRESHOLD_AVERAGE_LOCAL, SentinelCode.CLUSTER_THRESHOLD_GLOBAL],
          "clusterConfig.thresholdType",
        );
        const count = numeric(
          cluster.sampleCount,
          "clusterConfig.sampleCount",
          0,
          true,
          Infinity,
          true,
        );
        const window = numeric(
          cluster.windowIntervalMs,
          "clusterConfig.windowIntervalMs",
          0,
          true,
          Infinity,
          true,
        );
        if (
          count !== null &&
          window !== null &&
          count > 0 &&
          window > 0 &&
          Number.isSafeInteger(count) &&
          Number.isSafeInteger(window) &&
          (window < count || window % count !== 0)
        )
          push(RULE_ISSUE.Window, "clusterConfig.windowIntervalMs");
      }
      break;
    }
    case RULE_KIND.Degrade: {
      const draft = rule.draft;
      choice(draft.grade, DEGRADE_VALUES, "grade");
      numeric(
        draft.count,
        "count",
        0,
        draft.grade === SentinelCode.DEGRADE_ERROR_COUNT,
        draft.grade === SentinelCode.DEGRADE_ERROR_RATIO ? 1 : Infinity,
        true,
      );
      numeric(draft.timeWindow, "timeWindow", 0, true, Infinity, true);
      numeric(draft.minRequestAmount, "minRequestAmount", 0, true, Infinity, true);
      numeric(draft.statIntervalMs, "statIntervalMs", 0, true, Infinity, true);
      if (draft.grade === SentinelCode.DEGRADE_SLOW_REQUEST_RATIO)
        numeric(draft.slowRatioThreshold, "slowRatioThreshold", 0, false, 1, true);
      break;
    }
    case RULE_KIND.System: {
      const draft = rule.draft;
      let enabled = false;
      for (const field of SYSTEM_THRESHOLDS) {
        const value = finiteDraftNumber(draft[field]);
        if (value === DISABLED_SYSTEM_THRESHOLD) continue;
        enabled = true;
        numeric(
          draft[field],
          field,
          0,
          field === "maxThread",
          field === "highestCpuUsage" ? 1 : Infinity,
        );
      }
      if (!enabled) push(RULE_ISSUE.SystemEnabled, "systemThresholds");
      break;
    }
    case RULE_KIND.Authority: {
      const draft = rule.draft;
      choice(draft.strategy, AUTHORITY_VALUES, "strategy");
      const origins = draft.limitApp.split(",").map((origin) => origin.trim());
      if (origins.some((origin) => !origin)) push(RULE_ISSUE.OriginsRequired, "limitApp");
      if (new Set(origins).size !== origins.length) push(RULE_ISSUE.Duplicate, "limitApp");
      break;
    }
    case RULE_KIND.ParamFlow: {
      const draft = rule.draft;
      choice(draft.grade, [SentinelCode.FLOW_GRADE_QPS], "grade");
      numeric(draft.count, "count", 0, false, Infinity, true);
      numeric(draft.durationInSec, "durationInSec", 0, true, Infinity, true);
      numeric(draft.paramIdx, "paramIdx", 0, true);
      const seen = new Set<string>();
      draft.paramFlowItemList.forEach((item, index) => {
        const path = `paramFlowItemList.${index}`;
        required(item.classType, `${path}.classType`);
        required(item.object, `${path}.object`);
        numeric(item.count, `${path}.count`, 0);
        const key = JSON.stringify([item.classType.trim(), item.object]);
        if (seen.has(key)) push(RULE_ISSUE.Duplicate, `${path}.object`);
        seen.add(key);
      });
      break;
    }
  }
  return issues;
}

/** Minimal searchable read model, independent of the catalog component. */
export interface RuleCatalogEntry {
  readonly id: string;
  readonly app: string;
  readonly ruleType: RuleKind;
  readonly resource: string;
  readonly strategy: string;
}
export interface RuleCatalogFilter {
  readonly appId: string;
  readonly allApplications: string;
  readonly kind: RuleKindFilter;
  readonly query: string;
}

/** Stable filtering preserves input order and never mutates the catalog. */
export function filterRuleCatalog<T extends RuleCatalogEntry>(
  entries: readonly T[],
  filter: RuleCatalogFilter,
): readonly T[] {
  const query = filter.query.trim().toLowerCase();
  return entries.filter(
    (entry) =>
      (filter.appId === filter.allApplications || entry.app === filter.appId) &&
      (filter.kind === RULE_KIND_ALL || entry.ruleType === filter.kind) &&
      `${entry.resource} ${entry.strategy}`.toLowerCase().includes(query),
  );
}
