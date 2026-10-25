import { AppError, AppErrorKind, defineUrl } from "@richie696/react-framework";
import type { z } from "zod";
import type {
  ConsoleEndpoint,
  ConsoleTransport,
} from "../../../core/api/transport/consoleEndpoint";
import type { RuleBindingScopeCatalog } from "../model/ruleBindingScope";
import { validRuleBindingScopeCatalog } from "../model/ruleBindingScope";
import type { RuleBindingScopePort } from "./ruleBindingScopePort";
import { RuleBindingScopeCatalogSchema } from "./ruleBindingScopeWire";
import { ruleBindingScopeCatalogFromWire } from "./ruleBindingScopeMapper";

const readErrors = ["invalid_request", "unauthenticated", "service_unavailable"] as const;

export const RULE_BINDING_SCOPE_ENDPOINT: ConsoleEndpoint<
  z.infer<typeof RuleBindingScopeCatalogSchema>
> = {
  url: defineUrl("/api/v2/rules/binding-scopes"),
  response: RuleBindingScopeCatalogSchema,
  successStatus: 200,
  command: false,
  idempotency: "none",
  csrf: false,
  expireOnUnauthorized: true,
  errors: readErrors,
};

/** Create the feature-owned Rules-scope gateway used in both mock and live modes. */
export function createRuleBindingScopeHttp(transport: ConsoleTransport): RuleBindingScopePort {
  return Object.freeze({
    async readRuleBindingScopes(signal): Promise<RuleBindingScopeCatalog> {
      const wire = await transport.send(RULE_BINDING_SCOPE_ENDPOINT, { signal });
      const value = ruleBindingScopeCatalogFromWire(wire);
      if (!validRuleBindingScopeCatalog(value))
        throw new AppError(AppErrorKind.PROTOCOL, "Invalid rule binding scopes", {
          status: 502,
          code: "console_response_invalid",
        });
      return value;
    },
  } satisfies RuleBindingScopePort);
}
