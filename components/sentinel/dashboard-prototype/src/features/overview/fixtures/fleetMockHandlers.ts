import { http, HttpResponse } from "msw";
import { CONSOLE_ERROR_STATUS, CONSOLE_HEADER } from "../../../core/api/protocol/common";
import { FleetParametersSchema } from "../api/fleetWire";
import { snapshotFor, type FleetObservationScenario } from "./observationFixtures";

const instant = (value: number) => new Date(value).toISOString();
const queryValues = (url: URL) => {
  const values: Record<string, string | number> = {};
  for (const [key, value] of url.searchParams) {
    if (key === "page" || key === "pageSize" || key === "stepMs") {
      if (!/^[1-9]\d*$/.test(value)) return null;
      values[key] = Number(value);
    } else values[key] = value;
  }
  return FleetParametersSchema.safeParse(values);
};

function response(body: unknown, requestId: string | null, status = 200) {
  const headers = new Headers({ "Content-Type": "application/json" });
  if (requestId) headers.set(CONSOLE_HEADER.RequestId, requestId);
  return new HttpResponse(JSON.stringify(body), {
    status,
    headers,
  });
}

function bundleToWire(bundle: ReturnType<typeof snapshotFor>["metrics"]) {
  return {
    query: {
      ...bundle.query,
      context: {
        ...bundle.query.context,
        window: {
          from: instant(bundle.query.context.window.fromMs),
          to: instant(bundle.query.context.window.toMs),
        },
      },
    },
    asOf: instant(bundle.asOfMs),
    summary: bundle.summary.map(({ sampledAtMs, ...reading }) => ({
      ...reading,
      sampledAt: sampledAtMs === null ? null : instant(sampledAtMs),
    })),
    series: bundle.series.map(({ samples, ...series }) => ({
      ...series,
      samples: samples.map(({ atMs, value }) => ({ at: instant(atMs), value })),
    })),
    annotations: bundle.annotations.map(({ atMs, ...annotation }) => ({
      ...annotation,
      at: instant(atMs),
    })),
  };
}

/** Browser mock endpoints for the formal fleet page; they exercise the same HTTP adapter as live mode. */
export function createFleetMockHandlers(scenario: FleetObservationScenario) {
  const scenarioReads = new Map<string, number>();
  return Object.freeze([
    http.get("*/api/v1/fleet/overview", ({ request }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      const parsed = queryValues(new URL(request.url));
      if (!parsed?.success)
        return response(
          { error: { code: "invalid_request", requestId: requestId ?? "mock-invalid-request" } },
          requestId,
          400,
        );
      const { from, to, environmentId, appId, scope, page, pageSize, search, stepMs } = parsed.data;
      if (environmentId !== scenario.environment.id)
        return response(
          { error: { code: "not_found", requestId: requestId ?? "mock-not-found" } },
          requestId,
          404,
        );
      if (appId === scenario.readScenarios.forbiddenApplicationId)
        return response({ error: { code: "forbidden", requestId } }, requestId, 403);
      const failurePlan = scenario.readScenarios.fleetFailure;
      if (appId === failurePlan.applicationId) {
        const readNumber = (scenarioReads.get(failurePlan.applicationId) ?? 0) + 1;
        scenarioReads.set(failurePlan.applicationId, readNumber);
        if (readNumber === failurePlan.failOnRead)
          return response(
            { error: { code: failurePlan.errorCode, requestId } },
            requestId,
            CONSOLE_ERROR_STATUS[failurePlan.errorCode],
          );
      }
      const context = {
        environmentId,
        appId: appId ?? null,
        instanceId: null,
        resource: null,
        scope,
        window: { fromMs: Date.parse(from), toMs: Date.parse(to) },
      } as const;
      const value = snapshotFor({ context, page, pageSize, search, stepMs }, scenario);
      return response(
        {
          query: {
            ...value.query,
            context: {
              ...context,
              window: { from, to },
            },
          },
          asOf: instant(value.asOfMs),
          coverage: value.coverage,
          totalApplications: value.totalApplications,
          attentionApplications: value.attentionApplications,
          attentionTargets: value.attentionTargets,
          applications: {
            ...value.applications,
            items: value.applications.items.map((application) => ({
              ...application,
              metrics: application.metrics.map(({ sampledAtMs, ...reading }) => ({
                ...reading,
                sampledAt: sampledAtMs === null ? null : instant(sampledAtMs),
              })),
            })),
          },
          metrics: bundleToWire(value.metrics),
          connections: value.connections.map(({ checkedAtMs, ...connection }) => ({
            ...connection,
            checkedAt: checkedAtMs === null ? null : instant(checkedAtMs),
          })),
        },
        requestId,
      );
    }),
  ]);
}
