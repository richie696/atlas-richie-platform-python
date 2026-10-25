import {
  CONSOLE_ACCESS,
  type ConsoleOperationContract,
} from "../../../core/api/protocol/operationContract";
import { z } from "zod";
import {
  RULE_BINDING_STATES_ENDPOINT,
  RULE_LOAD_OBSERVATIONS_ENDPOINT,
  RULE_LOAD_OBSERVATION_HISTORY_ENDPOINT,
} from "./ruleObservationHttp";
import {
  RuleBindingStatesParametersSchema,
  RuleLoadObservationParametersSchema,
  RuleLoadObservationHistoryParametersSchema,
} from "./ruleObservationWire";

const queryFields = (shape: Record<string, z.ZodType>) =>
  Object.entries(shape).map(([name, schema]) => ({ name, schema }));

/** API 0.9 observations are additive and remain independent of the legacy 0.8 catalog DTO. */
export const RULE_OBSERVATION_HTTP_CONTRACT: readonly ConsoleOperationContract[] = Object.freeze([
  {
    operationId: "readRuleBindingObservedStates",
    summary: "读取规则绑定的配置中心观测状态",
    tag: "rulesets",
    security: "session",
    requiredAccess: CONSOLE_ACCESS.None,
    endpoint: RULE_BINDING_STATES_ENDPOINT,
    input: null,
    pathParameters: [],
    queryParameters: queryFields(RuleBindingStatesParametersSchema.shape),
    semanticRules: [
      "Reads only the SQL projection for registered bindings; it never calls a provider synchronously.",
      "A confirmed empty rule array is distinct from an absent provider target; missing targets do not delete last-known-good rules.",
      "Authenticated admin and view sessions may read this page; credentials and provider payloads are never returned.",
      "This operation is additive in Console API 0.9.0; all 0.8.0 routes and DTOs remain unchanged.",
    ],
    examples: [
      {
        name: "configured-empty-binding",
        summary: "配置源确认存在，但规则数组为空",
        kind: "positive",
        request: {
          queryParameters: { environmentId: "prod", appId: "orders", page: 1, pageSize: 20 },
        },
        response: {
          status: 200,
          body: {
            query: { environmentId: "prod", appId: "orders", kind: null, page: 1, pageSize: 20 },
            asOf: "2026-10-16T08:00:00.000Z",
            coverage: "complete",
            total: 1,
            hasMore: false,
            items: [
              {
                binding: {
                  id: "orders-flow",
                  environmentId: "prod",
                  appId: "orders",
                  kind: "flow",
                  profile: "sentinel-python-v1",
                  sourceId: "nacos-main",
                  sourceLabel: "Nacos production",
                  location: "public/DEFAULT_GROUP/orders-flow",
                },
                state: "configured_empty",
                ruleCount: 0,
                sourceRevision: "revision-1",
                lastAttemptAt: "2026-10-16T07:59:55.000Z",
                freshness: "current",
                hasLastKnownGood: true,
              },
            ],
          },
        },
      },
      {
        name: "anonymous-reader-rejected",
        summary: "匿名会话不能读取规则绑定状态",
        kind: "negative",
        request: {
          queryParameters: { environmentId: "prod", appId: "orders", page: 1, pageSize: 20 },
        },
        response: {
          status: 401,
          body: { error: { code: "unauthenticated", requestId: "rule-binding-state-anonymous" } },
        },
      },
    ],
  },
  {
    operationId: "readRuleLoadObservations",
    summary: "读取每个规则绑定在各运行时实例上的加载状态",
    tag: "rulesets",
    security: "session",
    requiredAccess: CONSOLE_ACCESS.None,
    endpoint: RULE_LOAD_OBSERVATIONS_ENDPOINT,
    input: null,
    pathParameters: [],
    queryParameters: queryFields(RuleLoadObservationParametersSchema.shape),
    semanticRules: [
      "Expected targets are all non-revoked Reporter enrollments for the exact environment/application; each worker is an instance.",
      "Collector receivedAt is authoritative; an observation is stale strictly after 90 seconds, and revoked enrollments are excluded.",
      "Unknown/incomplete inventories and unknown or incompatible profiles never imply unused, unsupported, or not-loaded.",
      "Certificate principals, raw payloads, credentials, and rule bodies are never returned; only authenticated readers may view member fingerprints.",
      "This operation is additive in Console API 0.9.0; Agent Reporting, Runtime Receipt, and Metrics V2 wires are unchanged.",
    ],
    examples: [
      {
        name: "expected-runtime-worker-not-observed",
        summary: "有效 Reporter enrollment 尚无当前绑定回执",
        kind: "positive",
        request: {
          queryParameters: { environmentId: "prod", appId: "orders", page: 1, pageSize: 20 },
        },
        response: {
          status: 200,
          body: {
            query: {
              environmentId: "prod",
              appId: "orders",
              bindingId: null,
              instanceId: null,
              page: 1,
              pageSize: 20,
            },
            asOf: "2026-10-16T08:00:00.000Z",
            coverage: "complete",
            targets: {
              source: "active_reporter_enrollment",
              expected: 1,
              observed: 0,
              stale: 0,
              notObserved: 1,
            },
            total: 1,
            hasMore: false,
            items: [
              {
                bindingId: "orders-flow",
                instanceId: "orders-0",
                processId: "worker-0",
                processEpoch: null,
                profileId: null,
                loadState: "not_observed",
                eventKind: null,
                activeSnapshot: null,
                attempt: null,
                observedAt: null,
                receivedAt: null,
                freshness: "unknown",
              },
            ],
          },
        },
      },
      {
        name: "anonymous-reader-rejected",
        summary: "匿名会话不能读取实例规则加载状态",
        kind: "negative",
        request: {
          queryParameters: { environmentId: "prod", appId: "orders", page: 1, pageSize: 20 },
        },
        response: {
          status: 401,
          body: {
            error: { code: "unauthenticated", requestId: "rule-load-observation-anonymous" },
          },
        },
      },
    ],
  },
  {
    operationId: "readRuleLoadObservationHistory",
    summary: "读取规则绑定的历史进程加载观察",
    tag: "rulesets",
    security: "session",
    requiredAccess: CONSOLE_ACCESS.None,
    endpoint: RULE_LOAD_OBSERVATION_HISTORY_ENDPOINT,
    input: null,
    pathParameters: [],
    queryParameters: queryFields(RuleLoadObservationHistoryParametersSchema.shape),
    semanticRules: [
      "Requires exact environment, application, and binding scope; optional instance and stable bounded pagination are supported.",
      "Reads immutable Collector inbox facts only when the process epoch is superseded, revoked, or has no current epoch; active epochs are excluded.",
      "History is separate from current target counts and never implies current usage, non-usage, or a current instance inventory.",
      "Returns safe observation metadata and fingerprints only; certificate principal, credentials, raw body, and rule payload are never exposed.",
      "This additive read does not change the frozen current-observation operation or reporting protocols.",
    ],
    examples: [
      {
        name: "superseded-process-epoch",
        summary: "新进程 epoch 替代后的历史加载事件",
        kind: "positive",
        request: {
          queryParameters: {
            environmentId: "prod",
            appId: "orders",
            bindingId: "orders-flow",
            page: 1,
            pageSize: 20,
          },
        },
        response: {
          status: 200,
          body: {
            query: {
              environmentId: "prod",
              appId: "orders",
              bindingId: "orders-flow",
              instanceId: null,
              page: 1,
              pageSize: 20,
            },
            asOf: "2026-10-17T08:00:00.000Z",
            coverage: "complete",
            total: 0,
            hasMore: false,
            items: [],
          },
        },
      },
      {
        name: "anonymous-history-reader-rejected",
        summary: "匿名会话不能读取历史进程加载观察",
        kind: "negative",
        request: {
          queryParameters: {
            environmentId: "prod",
            appId: "orders",
            bindingId: "orders-flow",
            page: 1,
            pageSize: 20,
          },
        },
        response: {
          status: 401,
          body: {
            error: { code: "unauthenticated", requestId: "rule-load-history-anonymous" },
          },
        },
      },
    ],
  },
]);
