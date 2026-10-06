/**
 * 规则的纯规则：校验与目录筛选。
 *
 * 中文
 * ----
 * 本模块不依赖 React、语言包或网络，只接收数据、返回结论。
 *
 * 校验结果用**结构化问题**而不是已翻译的字符串：旧实现让 `validationErrors`
 * 接收一个 `t` 函数并直接产出文案，于是「规则是否合法」这个领域判断被绑死在
 * 界面语言上，既无法单测，也无法在别处复用同一份判断。问题里只保留消息键与插值
 * 参数，翻译发生在 UI 层。
 */
import {
  DISABLED_SYSTEM_THRESHOLD,
  RULE_KIND,
  RULE_KIND_ALL,
  SentinelCode,
} from "./ruleKinds";
import type { RuleKind, RuleKindFilter } from "./ruleKinds";
import { narrowDraft, type RuleDraft } from "./ruleDraft";

/** 校验失败的消息键。取值与语言包 `rules.errors.*` 一一对应。 */
export type RuleIssueKey =
  | "rules.errors.resourceRequired"
  | "rules.errors.countPositive"
  | "rules.errors.referenceRequired"
  | "rules.errors.degradePositive"
  | "rules.errors.slowRatio"
  | "rules.errors.parameterIndex"
  | "rules.errors.originsRequired"
  | "rules.errors.systemEnabled";

/** 一条校验问题。UI 层负责把 {@link key} 与 {@link params} 翻译为文案。 */
export interface RuleIssue {
  readonly key: RuleIssueKey;
  /** 触发该问题的字段路径，便于在表单上定位。 */
  readonly path: string;
  readonly params?: Readonly<Record<string, string | number>>;
}

const isPositiveNumber = (value: unknown): boolean => Number(value) > 0;
const isNonEmptyString = (value: unknown): boolean => String(value ?? "").trim().length > 0;

/** SystemRule 的五个阈值字段。 */
const SYSTEM_THRESHOLDS = [
  "highestSystemLoad",
  "avgRt",
  "maxThread",
  "qps",
  "highestCpuUsage",
] as const;

/**
 * 校验一条规则草稿是否可以提交。
 *
 * 中文
 * ----
 * 这里只做**本地语义校验**：schema 形状与取值范围。跨实例影响面、基准版本冲突和
 * 配置中心回读一致性由服务端在发布时判断，前端不得代替。
 */
export function validateRuleDraft(kind: RuleKind, draft: RuleDraft): readonly RuleIssue[] {
  const issues: RuleIssue[] = [];
  const push = (key: RuleIssueKey, path: string, params?: RuleIssue["params"]) => {
    issues.push(params ? { key, path, params } : { key, path });
  };

  if (kind !== RULE_KIND.System) {
    const resource = "resource" in draft ? draft.resource : undefined;
    if (!isNonEmptyString(resource)) {
      push("rules.errors.resourceRequired", "resource");
    }
  }

  if (kind === RULE_KIND.Flow || kind === RULE_KIND.ParamFlow) {
    if (!isPositiveNumber(narrowDraft(kind, draft).count)) {
      push("rules.errors.countPositive", "count");
    }
  }

  if (kind === RULE_KIND.Flow) {
    const flow = narrowDraft(RULE_KIND.Flow, draft);
    if (
      flow.strategy !== SentinelCode.FLOW_STRATEGY_DIRECT &&
      !isNonEmptyString(flow.refResource)
    ) {
      push("rules.errors.referenceRequired", "refResource");
    }
  }

  if (kind === RULE_KIND.Degrade) {
    const degrade = narrowDraft(RULE_KIND.Degrade, draft);
    if (!isPositiveNumber(degrade.count) || !isPositiveNumber(degrade.timeWindow)) {
      push("rules.errors.degradePositive", "count");
    }
    if (
      degrade.grade === SentinelCode.DEGRADE_SLOW_REQUEST_RATIO &&
      !(isPositiveNumber(degrade.slowRatioThreshold) && Number(degrade.slowRatioThreshold) <= 1)
    ) {
      push("rules.errors.slowRatio", "slowRatioThreshold");
    }
  }

  if (kind === RULE_KIND.ParamFlow) {
    const param = narrowDraft(RULE_KIND.ParamFlow, draft);
    if (!Number.isInteger(Number(param.paramIdx)) || Number(param.paramIdx) < 0) {
      push("rules.errors.parameterIndex", "paramIdx");
    }
  }

  if (kind === RULE_KIND.Authority) {
    const authority = narrowDraft(RULE_KIND.Authority, draft);
    if (!isNonEmptyString(authority.limitApp)) {
      push("rules.errors.originsRequired", "limitApp");
    }
  }

  if (kind === RULE_KIND.System) {
    const system = narrowDraft(RULE_KIND.System, draft);
    if (SYSTEM_THRESHOLDS.every((field) => Number(system[field]) === DISABLED_SYSTEM_THRESHOLD)) {
      push("rules.errors.systemEnabled", "systemThresholds");
    }
  }

  return issues;
}

/** 目录条目，用于筛选。字段与 `features/rules/fixtures` 的形状一致。 */
export interface RuleCatalogEntry {
  readonly id: string;
  readonly app: string;
  readonly ruleType: RuleKind;
  readonly resource: string;
  readonly strategy: string;
}

/** 目录筛选条件。 */
export interface RuleCatalogFilter {
  /** 选中的应用；`all` 表示不限应用。 */
  readonly appId: string;
  /** 不限应用时的哨兵值。 */
  readonly allApplications: string;
  readonly kind: RuleKindFilter;
  /** 搜索词，对资源与策略做大小写不敏感的包含匹配。 */
  readonly query: string;
}

/**
 * 按应用、类型与搜索词筛选规则目录。
 *
 * 纯函数：同样的输入必然得到同样的顺序，因此目录行不会在无关渲染中重排。
 */
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
