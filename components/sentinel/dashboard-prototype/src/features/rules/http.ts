/** Rules feature HTTP assembly; UI and workflows consume only their internal ports. */
export { createRuleSetHttp, RULE_SET_ENDPOINTS } from "./api/ruleSetHttp";
export {
  createRuleBindingScopeHttp,
  RULE_BINDING_SCOPE_ENDPOINT,
} from "./api/ruleBindingScopeHttp";
export { RULE_SET_HTTP_CONTRACT } from "./api/ruleSetContract";
export { RULE_OBSERVATION_HTTP_CONTRACT } from "./api/ruleObservationContract";
export { createRuleObservationHttp } from "./api/ruleObservationHttp";
export type { RuleObservationPort } from "./api/ruleObservationPort";
