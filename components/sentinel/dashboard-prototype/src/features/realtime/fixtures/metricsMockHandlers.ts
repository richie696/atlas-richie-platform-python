import { http, HttpResponse } from "msw";
import { CONSOLE_ERROR_STATUS, CONSOLE_HEADER } from "../../../core/api/protocol/common";
import { METRIC_ID, type MetricId } from "../../../shared/model/observation";
import { MetricParametersSchema } from "../api/metricsHttp";
import { metricBundleFor, type RealtimeObservationScenario } from "./metricObservationFixtures";

const instant = (value: number) => new Date(value).toISOString();
const isMetricId = (value: string): value is MetricId =>
  Object.values(METRIC_ID).some((metric) => metric === value);
function response(body: unknown, requestId: string | null, status = 200) {
  const headers = new Headers({ "Content-Type": "application/json" });
  if (requestId) headers.set(CONSOLE_HEADER.RequestId, requestId);
  return new HttpResponse(JSON.stringify(body), { status, headers });
}
function parseParameters(url: URL) {
  const input: Record<string, string | number> = {};
  for (const [key, value] of url.searchParams) {
    if (key === "stepMs") {
      if (!/^[1-9]\d*$/.test(value)) return null;
      input[key] = Number(value);
    } else input[key] = value;
  }
  return MetricParametersSchema.safeParse(input);
}
function contextToWire(context: ReturnType<typeof metricBundleFor>["query"]["context"]) {
  return {
    ...context,
    window: { from: instant(context.window.fromMs), to: instant(context.window.toMs) },
  };
}
function readingToWire(reading: ReturnType<typeof metricBundleFor>["summary"][number]) {
  const { sampledAtMs, ...metadata } = reading;
  return { ...metadata, sampledAt: sampledAtMs === null ? null : instant(sampledAtMs) };
}
function bundleToWire(value: ReturnType<typeof metricBundleFor>) {
  return {
    query: { ...value.query, context: contextToWire(value.query.context) },
    asOf: instant(value.asOfMs),
    summary: value.summary.map(readingToWire),
    series: value.series.map(({ samples, ...series }) => ({
      ...series,
      samples: samples.map(({ atMs, value: sample }) => ({ at: instant(atMs), value: sample })),
    })),
    annotations: value.annotations.map(({ atMs, ...annotation }) => ({
      ...annotation,
      at: instant(atMs),
    })),
  };
}

/** Mock metrics remain behind HTTP and use the same strict decoder as live mode. */
export function createRealtimeMockHandlers(scenario: RealtimeObservationScenario) {
  const metricFailureReads = new Map<string, number>();
  const successfulMetricReads = new Map<string, number>();
  const networkFailureDelivered = new Set<string>();
  return Object.freeze([
    http.get("*/api/v1/metrics/query", ({ request }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      const parsed = parseParameters(new URL(request.url));
      if (!parsed?.success)
        return response({ error: { code: "invalid_request", requestId } }, requestId, 400);
      const { from, to, environmentId, appId, instanceId, resource, scope, metrics, stepMs } =
        parsed.data;
      if (environmentId !== scenario.environment.id)
        return response({ error: { code: "not_found", requestId } }, requestId, 404);
      const metricIds = metrics.split(",");
      if (
        metricIds.length === 0 ||
        new Set(metricIds).size !== metricIds.length ||
        !metricIds.every(isMetricId)
      )
        return response({ error: { code: "invalid_request", requestId } }, requestId, 400);
      const failurePlan = Object.entries(scenario.readScenarios.metricFailures).find(
        ([, plan]) => plan.applicationId === appId,
      );
      if (failurePlan) {
        const [scenarioName, plan] = failurePlan;
        const readNumber = (metricFailureReads.get(scenarioName) ?? 0) + 1;
        metricFailureReads.set(scenarioName, readNumber);
        if (readNumber === plan.failOnRead)
          return response(
            { error: { code: plan.errorCode, requestId } },
            requestId,
            CONSOLE_ERROR_STATUS[plan.errorCode],
          );
      }
      const networkFailure = scenario.readScenarios.networkFailure;
      if (
        networkFailure &&
        networkFailure.applicationId === appId &&
        !networkFailureDelivered.has(networkFailure.applicationId) &&
        (successfulMetricReads.get(networkFailure.applicationId) ?? 0) >=
          networkFailure.afterSuccessfulReads
      ) {
        networkFailureDelivered.add(networkFailure.applicationId);
        return HttpResponse.error();
      }
      const query = {
        context: {
          environmentId,
          appId: appId ?? null,
          instanceId: instanceId ?? null,
          resource: resource ?? null,
          scope,
          window: { fromMs: Date.parse(from), toMs: Date.parse(to) },
        },
        metrics: metricIds,
        stepMs,
      } as const;
      const value = metricBundleFor(query, scenario);
      if (networkFailure?.applicationId === appId)
        successfulMetricReads.set(
          networkFailure.applicationId,
          (successfulMetricReads.get(networkFailure.applicationId) ?? 0) + 1,
        );
      return response(bundleToWire(value), requestId);
    }),
  ]);
}
