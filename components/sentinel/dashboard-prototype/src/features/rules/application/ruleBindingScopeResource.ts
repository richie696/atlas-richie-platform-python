import { AppError, AppErrorKind } from "@richie696/react-framework";
import { createQueryResource } from "../../../shared/state/queryResource";
import type { RuleBindingScopePort } from "../api/ruleBindingScopePort";
import { validRuleBindingScopeCatalog } from "../model/ruleBindingScope";

/** Own the authoritative, rule-specific scope snapshot for one Rules route lifetime. */
export function createRuleBindingScopeResource(port: RuleBindingScopePort) {
  return createQueryResource<
    void,
    Awaited<ReturnType<RuleBindingScopePort["readRuleBindingScopes"]>>
  >({
    keyOf: () => "rule-binding-scopes",
    async read(_query, signal) {
      const value = await port.readRuleBindingScopes(signal);
      if (!validRuleBindingScopeCatalog(value))
        throw new AppError(AppErrorKind.PROTOCOL, "Invalid rule binding scopes", {
          status: 502,
          code: "console_response_invalid",
        });
      return value;
    },
    classify: (catalog) => (catalog.environments.length === 0 ? "empty" : "ready"),
  });
}
