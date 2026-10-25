import { AppError, AppErrorKind, defineUrl } from "@richie696/react-framework";
import type { z } from "zod";
import type {
  ConsoleEndpoint,
  ConsoleTransport,
} from "../../../core/api/transport/consoleEndpoint";
import { parseConsoleInput } from "../../../core/api/protocol/parseInput";
import type {
  RuleBindingStatesPage,
  RuleBindingStatesQuery,
  RuleLoadObservationPage,
  RuleLoadObservationQuery,
  RuleLoadObservationHistoryPage,
  RuleLoadObservationHistoryQuery,
} from "../model/ruleObservations";
import {
  RuleBindingStatesPageSchema,
  RuleBindingStatesParametersSchema,
  RuleLoadObservationPageSchema,
  RuleLoadObservationParametersSchema,
  RuleLoadObservationHistoryPageSchema,
  RuleLoadObservationHistoryParametersSchema,
} from "./ruleObservationWire";
import type { RuleObservationPort } from "./ruleObservationPort";

const errors = ["invalid_request", "unauthenticated", "service_unavailable"] as const;
export const RULE_BINDING_STATES_ENDPOINT: ConsoleEndpoint<
  z.infer<typeof RuleBindingStatesPageSchema>
> = {
  url: defineUrl("/api/v2/rules/catalog/binding-states"),
  response: RuleBindingStatesPageSchema,
  successStatus: 200,
  command: false,
  idempotency: "none",
  csrf: false,
  expireOnUnauthorized: true,
  errors,
};
export const RULE_LOAD_OBSERVATIONS_ENDPOINT: ConsoleEndpoint<
  z.infer<typeof RuleLoadObservationPageSchema>
> = {
  url: defineUrl("/api/v2/rules/load-observations"),
  response: RuleLoadObservationPageSchema,
  successStatus: 200,
  command: false,
  idempotency: "none",
  csrf: false,
  expireOnUnauthorized: true,
  errors,
};
export const RULE_LOAD_OBSERVATION_HISTORY_ENDPOINT: ConsoleEndpoint<
  z.infer<typeof RuleLoadObservationHistoryPageSchema>
> = {
  url: defineUrl("/api/v2/rules/load-observation-history"),
  response: RuleLoadObservationHistoryPageSchema,
  successStatus: 200,
  command: false,
  idempotency: "none",
  csrf: false,
  expireOnUnauthorized: true,
  errors,
};

const invalid = () =>
  new AppError(AppErrorKind.PROTOCOL, "Invalid rule observation response", {
    status: 502,
    code: "console_response_invalid",
  });
const sameBindingQuery = (left: RuleBindingStatesQuery, right: RuleBindingStatesQuery) =>
  left.environmentId === right.environmentId &&
  left.appId === right.appId &&
  left.kind === right.kind &&
  left.page === right.page &&
  left.pageSize === right.pageSize;
const sameLoadQuery = (left: RuleLoadObservationQuery, right: RuleLoadObservationQuery) =>
  left.environmentId === right.environmentId &&
  left.appId === right.appId &&
  left.bindingId === right.bindingId &&
  left.instanceId === right.instanceId &&
  left.page === right.page &&
  left.pageSize === right.pageSize;
const sameHistoryQuery = (
  left: RuleLoadObservationHistoryQuery,
  right: RuleLoadObservationHistoryQuery,
) =>
  left.environmentId === right.environmentId &&
  left.appId === right.appId &&
  left.bindingId === right.bindingId &&
  left.instanceId === right.instanceId &&
  left.page === right.page &&
  left.pageSize === right.pageSize;

/** Runtime-validate both 0.9 read DTOs before they enter any page/workflow. */
export function createRuleObservationHttp(transport: ConsoleTransport): RuleObservationPort {
  return Object.freeze({
    async readBindingStates(query, signal): Promise<RuleBindingStatesPage> {
      const params = parseConsoleInput(RuleBindingStatesParametersSchema, {
        environmentId: query.environmentId,
        ...(query.appId === null ? {} : { appId: query.appId }),
        ...(query.kind === null ? {} : { kind: query.kind }),
        page: query.page,
        pageSize: query.pageSize,
      });
      const value = await transport.send(RULE_BINDING_STATES_ENDPOINT, { signal, query: params });
      const parsed = RuleBindingStatesPageSchema.safeParse(value);
      if (!parsed.success || !sameBindingQuery(parsed.data.query, query)) throw invalid();
      return {
        ...parsed.data,
        query: { ...parsed.data.query },
        items: parsed.data.items.map((item) => ({ ...item, binding: { ...item.binding } })),
      };
    },
    async readRuleLoadObservations(query, signal): Promise<RuleLoadObservationPage> {
      const params = parseConsoleInput(RuleLoadObservationParametersSchema, {
        environmentId: query.environmentId,
        appId: query.appId,
        ...(query.bindingId === null ? {} : { bindingId: query.bindingId }),
        ...(query.instanceId === null ? {} : { instanceId: query.instanceId }),
        page: query.page,
        pageSize: query.pageSize,
      });
      const value = await transport.send(RULE_LOAD_OBSERVATIONS_ENDPOINT, {
        signal,
        query: params,
      });
      const parsed = RuleLoadObservationPageSchema.safeParse(value);
      if (!parsed.success || !sameLoadQuery(parsed.data.query, query)) throw invalid();
      return {
        ...parsed.data,
        query: { ...parsed.data.query },
        targets: { ...parsed.data.targets },
        items: parsed.data.items.map((item) => ({
          ...item,
          activeSnapshot: item.activeSnapshot
            ? {
                ...item.activeSnapshot,
                members: item.activeSnapshot.members.map((member) => ({ ...member })),
              }
            : null,
          attempt: item.attempt ? { ...item.attempt } : null,
        })),
      };
    },
    async readRuleLoadObservationHistory(query, signal): Promise<RuleLoadObservationHistoryPage> {
      const params = parseConsoleInput(RuleLoadObservationHistoryParametersSchema, {
        environmentId: query.environmentId,
        appId: query.appId,
        bindingId: query.bindingId,
        ...(query.instanceId === null ? {} : { instanceId: query.instanceId }),
        page: query.page,
        pageSize: query.pageSize,
      });
      const value = await transport.send(RULE_LOAD_OBSERVATION_HISTORY_ENDPOINT, {
        signal,
        query: params,
      });
      const parsed = RuleLoadObservationHistoryPageSchema.safeParse(value);
      if (!parsed.success || !sameHistoryQuery(parsed.data.query, query)) throw invalid();
      return {
        ...parsed.data,
        query: { ...parsed.data.query },
        items: parsed.data.items.map((entry) => ({
          ...entry,
          observation: {
            ...entry.observation,
            activeSnapshot: entry.observation.activeSnapshot
              ? {
                  ...entry.observation.activeSnapshot,
                  members: entry.observation.activeSnapshot.members.map((member) => ({
                    ...member,
                  })),
                }
              : null,
            attempt: entry.observation.attempt ? { ...entry.observation.attempt } : null,
          },
        })),
      };
    },
  } satisfies RuleObservationPort);
}
