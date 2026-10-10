import {
  CONSOLE_ACCESS,
  type ConsoleOperationContract,
} from "../../../core/api/protocol/operationContract";
import { OBSERVATION_CATALOG_ENDPOINT } from "./catalogHttp";
import {
  OBSERVATION_EXAMPLE_TIME,
  observationErrorExample,
} from "../../../shared/api/observationContractExamples";
export const OBSERVATION_CATALOG_HTTP_CONTRACT = Object.freeze([
  {
    operationId: "readObservationCatalog",
    summary: "读取当前会话可见的环境和应用选择目录",
    tag: "observation-catalog",
    security: "session",
    requiredAccess: CONSOLE_ACCESS.None,
    endpoint: OBSERVATION_CATALOG_ENDPOINT,
    input: null,
    pathParameters: [],
    examples: [
      {
        name: "authorized-selector",
        summary: "返回会话可见环境与应用，不包含配置源连接信息",
        kind: "positive",
        request: {},
        response: {
          status: 200,
          body: {
            asOf: OBSERVATION_EXAMPLE_TIME.asOf,
            environments: [{ id: "prod", name: "Production" }],
            applications: [{ id: "checkout", environmentId: "prod", name: "Checkout API" }],
          },
        },
      },
      {
        name: "session-required",
        summary: "未认证会话不能读取环境与应用选择目录",
        kind: "negative",
        request: {},
        response: { status: 401, body: observationErrorExample("unauthenticated") },
      },
    ],
    semanticRules: [
      "This is an authorized environment/application selector, not an exhaustive instance/resource inventory.",
      "Application identity is unique within environment; consumers must not invent or silently substitute a default selection.",
      "No configuration provider URL or credential is returned.",
    ],
  },
] satisfies readonly ConsoleOperationContract[]);
