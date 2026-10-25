import type {
  RuleBindingStatesPage,
  RuleBindingStatesQuery,
  RuleLoadObservationPage,
  RuleLoadObservationQuery,
  RuleLoadObservationHistoryPage,
  RuleLoadObservationHistoryQuery,
} from "../model/ruleObservations";

export interface RuleObservationPort {
  readonly readBindingStates: (
    query: RuleBindingStatesQuery,
    signal: AbortSignal,
  ) => Promise<RuleBindingStatesPage>;
  readonly readRuleLoadObservations: (
    query: RuleLoadObservationQuery,
    signal: AbortSignal,
  ) => Promise<RuleLoadObservationPage>;
  readonly readRuleLoadObservationHistory: (
    query: RuleLoadObservationHistoryQuery,
    signal: AbortSignal,
  ) => Promise<RuleLoadObservationHistoryPage>;
}
