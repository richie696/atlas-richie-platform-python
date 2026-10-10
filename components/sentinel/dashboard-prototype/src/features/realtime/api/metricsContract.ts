import {
  CONSOLE_ACCESS,
  type ConsoleOperationContract,
} from "../../../core/api/protocol/operationContract";
import { METRICS_ENDPOINT, MetricParametersSchema } from "./metricsHttp";
import { METRIC_ID } from "../../../shared/model/observation";
import {
  APPLICATION_OBSERVATION_CONTEXT,
  OBSERVATION_EXAMPLE_TIME,
  observationErrorExample,
  observationMetricBundle,
} from "../../../shared/api/observationContractExamples";

const metricQueryParameters = {
  environmentId: "prod",
  appId: "checkout",
  scope: "application",
  from: OBSERVATION_EXAMPLE_TIME.from,
  to: OBSERVATION_EXAMPLE_TIME.to,
  metrics: METRIC_ID.HttpQps,
  stepMs: 60_000,
};
export const METRICS_HTTP_CONTRACT = Object.freeze([
  {
    operationId: "readMetrics",
    summary: "查询同一观测窗口的指标与事件标记",
    tag: "metrics",
    security: "session",
    requiredAccess: CONSOLE_ACCESS.MetricsView,
    endpoint: METRICS_ENDPOINT,
    input: null,
    pathParameters: [],
    queryParameters: Object.entries(MetricParametersSchema.shape).map(([name, schema]) => ({
      name,
      schema,
    })),
    examples: [
      {
        name: "not-integrated-metric",
        summary: "Collector 未接入时保留请求身份并以 null 表示指标不可用",
        kind: "positive",
        request: { queryParameters: metricQueryParameters },
        response: {
          status: 200,
          body: observationMetricBundle(
            APPLICATION_OBSERVATION_CONTEXT,
            [METRIC_ID.HttpQps],
            60_000,
          ),
        },
      },
      {
        name: "metrics-forbidden",
        summary: "没有 metrics:view 时拒绝指标读取",
        kind: "negative",
        request: { queryParameters: metricQueryParameters },
        response: { status: 403, body: observationErrorExample("forbidden") },
      },
    ],
    semanticRules: [
      "Requires metrics:view on every request; optional identity absence means null, not string null.",
      "metrics is a comma-separated list of unique MetricId values; preserve requested identities, window, scope and stepMs.",
      "UTC window is half-open, at most seven days; step admits at most 1000 points per series.",
      "No implicit QPS-to-TPS substitution, averaging of percentiles, zero-filling, or ratio/percent confusion.",
      "Unknown inventory has null expected/source; available requires a known complete reporting population.",
      "Summary/series contain each requested metric exactly once with its declared unit; samples are ordered and inside the exact window.",
      "Annotations are management facts, not inferred root causes; asOf is read time, not sample time.",
    ],
  },
] satisfies readonly ConsoleOperationContract[]);
