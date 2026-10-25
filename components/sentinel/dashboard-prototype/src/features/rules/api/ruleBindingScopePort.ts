import type { RuleBindingScopeCatalog } from "../model/ruleBindingScope";

/** Read selector scopes owned by persisted rule bindings, independently of metrics telemetry. */
export interface RuleBindingScopePort {
  readonly readRuleBindingScopes: (signal: AbortSignal) => Promise<RuleBindingScopeCatalog>;
}
