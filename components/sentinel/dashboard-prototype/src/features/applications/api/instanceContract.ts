import { OpaqueIdentifierSchema } from "../../../core/api/protocol/common";
import {
  CONSOLE_ACCESS,
  type ConsoleOperationContract,
} from "../../../core/api/protocol/operationContract";
import { INSTANCE_ENDPOINTS } from "./instanceHttp";
import { InstanceCatalogParametersSchema, InstanceDetailParametersSchema } from "./instanceWire";
import {
  FLEET_OBSERVATION_CONTEXT,
  OBSERVATION_EXAMPLE_TIME,
  OPERATIONAL_METRIC_READINGS,
  PROCESS_OBSERVATION_CONTEXT,
  UNKNOWN_OBSERVATION_COVERAGE,
  observationErrorExample,
  observationMetricBundle,
} from "../../../shared/api/observationContractExamples";

const instanceCatalogParameters = {
  environmentId: "prod",
  scope: "fleet",
  from: OBSERVATION_EXAMPLE_TIME.from,
  to: OBSERVATION_EXAMPLE_TIME.to,
  page: 1,
  pageSize: 20,
  search: "",
  attentionOnly: false,
};
const instanceDetailParameters = {
  environmentId: "prod",
  appId: "checkout",
  scope: "process",
  from: OBSERVATION_EXAMPLE_TIME.from,
  to: OBSERVATION_EXAMPLE_TIME.to,
  processEpoch: "process-epoch-1",
  stepMs: 60_000,
};
export const INSTANCE_HTTP_CONTRACT = Object.freeze([
  {
    operationId: "readInstanceCatalog",
    summary: "分页查询实例与当前进程观测",
    tag: "instances",
    security: "session",
    requiredAccess: CONSOLE_ACCESS.MetricsView,
    endpoint: INSTANCE_ENDPOINTS.Catalog,
    input: null,
    pathParameters: [],
    queryParameters: Object.entries(InstanceCatalogParametersSchema.shape).map(
      ([name, schema]) => ({ name, schema }),
    ),
    examples: [
      {
        name: "unknown-inventory",
        summary: "实例目录尚无权威清单時返回未知覆盖与空页",
        kind: "positive",
        request: { queryParameters: instanceCatalogParameters },
        response: {
          status: 200,
          body: {
            query: {
              context: FLEET_OBSERVATION_CONTEXT,
              page: 1,
              pageSize: 20,
              search: "",
              attentionOnly: false,
            },
            asOf: OBSERVATION_EXAMPLE_TIME.asOf,
            coverage: UNKNOWN_OBSERVATION_COVERAGE,
            totalInstances: 0,
            attentionInstances: 0,
            filteredTotal: 0,
            items: [],
          },
        },
      },
      {
        name: "metrics-forbidden",
        summary: "没有 metrics:view 时拒绝实例目录读取",
        kind: "negative",
        request: { queryParameters: instanceCatalogParameters },
        response: { status: 403, body: observationErrorExample("forbidden") },
      },
    ],
    semanticRules: [
      "Requires metrics:view; only fleet/application directory scopes are accepted, with no instanceId/resource selector; application/environment scope and page/filter identities are explicit.",
      "Instance detail accepts only host, container or process collection layers; fleet and application scopes are invalid for this endpoint.",
      "Totals cover the whole requested population; filteredTotal and current page remain separate.",
      "Inventory expected/source may be unknown together; reporting never fabricates an expected population.",
      "Instance incarnation, rule receipt and process-level summary metrics are bound to the same processEpoch.",
      "Never select an implicit first instance when the requested page/filter is empty.",
    ],
  },
  {
    operationId: "readInstanceObservation",
    summary: "读取指定实例 incarnation 与采集层级指标",
    tag: "instances",
    security: "session",
    requiredAccess: CONSOLE_ACCESS.MetricsView,
    endpoint: INSTANCE_ENDPOINTS.Detail,
    input: null,
    pathParameters: [{ name: "instanceId", schema: OpaqueIdentifierSchema }],
    queryParameters: Object.entries(InstanceDetailParametersSchema.shape)
      .filter(([name]) => name !== "instanceId")
      .map(([name, schema]) => ({ name, schema })),
    examples: [
      {
        name: "unsupported-host-scope",
        summary: "实例未报告主机采集能力，返回 null 指标而不借用进程值",
        kind: "positive",
        request: {
          pathParameters: { instanceId: "checkout-1" },
          queryParameters: { ...instanceDetailParameters, scope: "host" },
        },
        response: {
          status: 200,
          body: {
            query: {
              context: { ...PROCESS_OBSERVATION_CONTEXT, scope: "host" },
              processEpoch: "process-epoch-1",
              stepMs: 60_000,
            },
            asOf: OBSERVATION_EXAMPLE_TIME.asOf,
            instance: {
              instanceId: "checkout-1",
              appId: "checkout",
              environmentId: "prod",
              hostId: null,
              containerId: null,
              processId: "pid-42",
              processEpoch: "process-epoch-1",
              health: "unknown",
              lastReportAt: null,
              supportedScopes: ["process"],
              ruleReceipt: {
                state: "unknown",
                desiredVersionId: null,
                appliedVersionId: null,
                processEpoch: "process-epoch-1",
                receivedAt: null,
              },
              processMetrics: OPERATIONAL_METRIC_READINGS,
            },
            metrics: null,
          },
        },
      },
      {
        name: "retired-incarnation",
        summary: "实例标识已复用但进程代次已变化时显式拒绝旧观察查询",
        kind: "negative",
        request: {
          pathParameters: { instanceId: "checkout-1" },
          queryParameters: instanceDetailParameters,
        },
        response: { status: 410, body: observationErrorExample("target_retired") },
      },
    ],
    semanticRules: [
      "Path target, application, environment, requested scope and processEpoch must identify one current process.",
      "A retired incarnation returns target_retired; the adapter maps it to explicit instance_incarnation_changed so old data is invalidated.",
      "Unsupported scope is an explicit instance fact with null metrics; never borrow process or container data.",
      "Applied receipt must match the exact current incarnation and desired version; asOf is separate from sample/receipt time.",
      "A new processEpoch invalidates prior observations even when instanceId is reused.",
    ],
  },
] satisfies readonly ConsoleOperationContract[]);
