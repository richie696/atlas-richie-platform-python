import {
  CONSOLE_ACCESS,
  type ConsoleOperationContract,
} from "../../../core/api/protocol/operationContract";
import { FleetParametersSchema } from "./fleetWire";
import { FLEET_ENDPOINT } from "./fleetHttp";
import {
  FLEET_OBSERVATION_CONTEXT,
  OBSERVATION_EXAMPLE_TIME,
  OPERATIONAL_METRIC_READINGS,
  UNKNOWN_OBSERVATION_COVERAGE,
  observationErrorExample,
  observationMetricBundle,
} from "../../../shared/api/observationContractExamples";

const fleetQueryParameters = {
  environmentId: "prod",
  scope: "fleet",
  from: OBSERVATION_EXAMPLE_TIME.from,
  to: OBSERVATION_EXAMPLE_TIME.to,
  page: 1,
  pageSize: 20,
  search: "",
  stepMs: 60_000,
};

export const FLEET_HTTP_CONTRACT = Object.freeze([
  {
    operationId: "readFleet",
    summary: "读取全范围总览及本页应用",
    tag: "fleet",
    security: "session",
    requiredAccess: CONSOLE_ACCESS.MetricsView,
    endpoint: FLEET_ENDPOINT,
    input: null,
    pathParameters: [],
    queryParameters: Object.entries(FleetParametersSchema.shape).map(([name, schema]) => ({
      name,
      schema,
    })),
    examples: [
      {
        name: "unknown-telemetry",
        summary: "清单与全局观测源尚未接入时返回明确 unknown，不虚构零样本",
        kind: "positive",
        request: { queryParameters: fleetQueryParameters },
        response: {
          status: 200,
          body: {
            query: {
              context: FLEET_OBSERVATION_CONTEXT,
              page: 1,
              pageSize: 20,
              search: "",
              stepMs: 60_000,
            },
            asOf: OBSERVATION_EXAMPLE_TIME.asOf,
            coverage: UNKNOWN_OBSERVATION_COVERAGE,
            totalApplications: 0,
            attentionApplications: 0,
            attentionTargets: [],
            applications: { items: [], total: 0, page: 1, pageSize: 20 },
            metrics: observationMetricBundle(
              FLEET_OBSERVATION_CONTEXT,
              OPERATIONAL_METRIC_READINGS.map(({ metric }) => metric),
              60_000,
            ),
            connections: [
              {
                id: "collector-primary",
                provider: "collector",
                state: "unknown",
                checkedAt: null,
                latencyMs: null,
              },
            ],
          },
        },
      },
      {
        name: "metrics-forbidden",
        summary: "会话没有 metrics:view 时拒绝总览读取",
        kind: "negative",
        request: { queryParameters: fleetQueryParameters },
        response: { status: 403, body: observationErrorExample("forbidden") },
      },
    ],
    semanticRules: [
      "Requires metrics:view; fleet/application scope never borrows an instance/resource scope.",
      "Global application/attention totals are not derived from the current page; attentionTargets is a bounded subset, not an exhaustive directory.",
      "Page query and every metric bundle preserve exact environment/application/window/step identities.",
      "All operational metrics are explicit including independently instrumented TPS; unknown/unintegrated values are not fabricated.",
      "Configuration health checkedAt/latencyMs is a separate dependency observation, not application sample time.",
      "Coverage source/denominator and metric units follow the common observation contract.",
    ],
  },
] satisfies readonly ConsoleOperationContract[]);
