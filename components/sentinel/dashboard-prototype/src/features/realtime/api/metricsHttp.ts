import { AppError, AppErrorKind, defineUrl } from "@richie696/react-framework";
import { z } from "zod";
import type {
  ConsoleEndpoint,
  ConsoleTransport,
} from "../../../core/api/transport/consoleEndpoint";
import {
  MetricBundleSchema,
  MetricQuerySchema,
  ObservationContextParametersSchema,
  ObservationStepSchema,
} from "../../../shared/api/observationWire";
import {
  observationContextToWire,
  observationContextParameters,
  metricBundleFromWire,
} from "../../../shared/api/observationMapper";
import { parseConsoleInput } from "../../../core/api/protocol/parseInput";
import { utf16BoundedString } from "../../../core/api/protocol/common";
import { validMetricQuery, validMetricBundle, METRIC_ID } from "../../../shared/model/observation";
import type { RealtimePort } from "./metricsPort";

export const METRICS_ENDPOINT: ConsoleEndpoint<z.infer<typeof MetricBundleSchema>> = {
  url: defineUrl("/api/v1/metrics/query"),
  response: MetricBundleSchema,
  successStatus: 200,
  command: false,
  idempotency: "none",
  csrf: false,
  expireOnUnauthorized: true,
  errors: [
    "invalid_request",
    "unauthenticated",
    "forbidden",
    "not_found",
    "target_retired",
    "rate_limited",
    "service_unavailable",
  ],
};
export const MetricParametersSchema = ObservationContextParametersSchema.extend({
  metrics: utf16BoundedString(Object.values(METRIC_ID).join(",").length).min(1),
  stepMs: ObservationStepSchema,
});
/** Fixed/rolling windows are resolved by the caller, not silently replaced by a browser-local relative interval. */
export function createMetricsHttp(transport: ConsoleTransport): RealtimePort {
  return Object.freeze({
    async readMetrics(query, signal) {
      if (!validMetricQuery(query))
        throw new AppError(AppErrorKind.PROTOCOL, "Invalid metric query", {
          status: 400,
          code: "console_request_invalid",
        });
      parseConsoleInput(MetricQuerySchema, {
        ...query,
        context: observationContextToWire(query.context),
      });
      const value = await transport.send(
        {
          ...METRICS_ENDPOINT,
          accept: (wire) => validMetricBundle(metricBundleFromWire(wire), query),
        },
        {
          signal,
          query: parseConsoleInput(MetricParametersSchema, {
            ...observationContextParameters(query.context),
            metrics: query.metrics.join(","),
            stepMs: query.stepMs,
          }),
        },
      );
      return metricBundleFromWire(value);
    },
  } satisfies RealtimePort);
}
