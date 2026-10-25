import { http, HttpResponse } from "msw";
import { CONSOLE_HEADER } from "../../../core/api/protocol/common";
import type { ObservationContext } from "../../../shared/model/observation";
import {
  InstanceCatalogParametersSchema,
  InstanceDetailParametersSchema,
} from "../api/instanceWire";
import {
  catalogFor,
  detailFor,
  type InstanceObservationScenario,
} from "./instanceObservationFixtures";

const instant = (value: number) => new Date(value).toISOString();
const response = (body: unknown, requestId: string | null, status = 200) => {
  const headers = new Headers({ "Content-Type": "application/json" });
  if (requestId) headers.set(CONSOLE_HEADER.RequestId, requestId);
  return new HttpResponse(JSON.stringify(body), { status, headers });
};
const contextToWire = (context: ObservationContext) => ({
  ...context,
  window: { from: instant(context.window.fromMs), to: instant(context.window.toMs) },
});
const readingToWire = (
  reading: ReturnType<typeof catalogFor>["items"][number]["processMetrics"][number],
) => ({
  ...reading,
  sampledAt: reading.sampledAtMs === null ? null : instant(reading.sampledAtMs),
  sampledAtMs: undefined,
});
function instanceToWire(instance: ReturnType<typeof catalogFor>["items"][number]) {
  const { lastReportAtMs, processMetrics, ruleReceipt, ...identity } = instance;
  const { receivedAtMs, ...receipt } = ruleReceipt;
  return {
    ...identity,
    lastReportAt: lastReportAtMs === null ? null : instant(lastReportAtMs),
    processMetrics: processMetrics.map(readingToWire),
    ruleReceipt: {
      ...receipt,
      receivedAt: receivedAtMs === null ? null : instant(receivedAtMs),
    },
  };
}
function catalogToWire(value: ReturnType<typeof catalogFor>) {
  return {
    query: { ...value.query, context: contextToWire(value.query.context) },
    asOf: instant(value.asOfMs),
    coverage: value.coverage,
    totalInstances: value.totalInstances,
    attentionInstances: value.attentionInstances,
    filteredTotal: value.filteredTotal,
    items: value.items.map(instanceToWire),
  };
}
function detailToWire(value: ReturnType<typeof detailFor>) {
  const bundle = value.metrics;
  return {
    query: {
      ...value.query,
      context: contextToWire(value.query.context),
    },
    asOf: instant(value.asOfMs),
    instance: instanceToWire(value.instance),
    metrics:
      bundle === null
        ? null
        : {
            query: {
              ...bundle.query,
              context: contextToWire(bundle.query.context),
            },
            asOf: instant(bundle.asOfMs),
            summary: bundle.summary.map(readingToWire),
            series: bundle.series.map(({ samples, ...series }) => ({
              ...series,
              samples: samples.map(({ atMs, value: sampleValue }) => ({
                at: instant(atMs),
                value: sampleValue,
              })),
            })),
            annotations: bundle.annotations.map(({ atMs, ...annotation }) => ({
              ...annotation,
              at: instant(atMs),
            })),
          },
  };
}
function parseParameters(url: URL) {
  const input: Record<string, string | number | boolean> = {};
  for (const [key, value] of url.searchParams) {
    if (["page", "pageSize", "stepMs"].includes(key)) {
      if (!/^[1-9]\d*$/.test(value)) return null;
      input[key] = Number(value);
    } else if (key === "attentionOnly") {
      if (value !== "true" && value !== "false") return null;
      input[key] = value === "true";
    } else input[key] = value;
  }
  return input;
}

/** Demo handler set. Synthetic observations are reachable only in explicit mock mode. */
export function createApplicationsMockHandlers(
  scenario: InstanceObservationScenario,
  now: () => number = Date.now,
) {
  return Object.freeze([
    http.get("*/api/v1/observation/catalog", ({ request }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      return response(
        {
          asOf: instant(now()),
          environments: [{ id: scenario.environment.id, name: scenario.environment.name }],
          applications: scenario.applications.map(({ id, name }) => ({
            id,
            environmentId: scenario.environment.id,
            name,
          })),
        },
        requestId,
      );
    }),
    http.get("*/api/v1/instances", ({ request }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      const parsed = InstanceCatalogParametersSchema.safeParse(
        parseParameters(new URL(request.url)),
      );
      if (!parsed.success)
        return response({ error: { code: "invalid_request", requestId } }, requestId, 400);
      const { from, to, environmentId, appId, scope, ...filters } = parsed.data;
      if (environmentId !== scenario.environment.id)
        return response({ error: { code: "not_found", requestId } }, requestId, 404);
      const context = {
        environmentId,
        appId: appId ?? null,
        instanceId: null,
        resource: null,
        scope,
        window: { fromMs: Date.parse(from), toMs: Date.parse(to) },
      } as const;
      const value = catalogFor({ context, ...filters }, scenario);
      return response(catalogToWire(value), requestId);
    }),
    http.get("*/api/v1/instances/:instanceId", ({ request, params }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      const parsed = InstanceDetailParametersSchema.safeParse(
        parseParameters(new URL(request.url)),
      );
      if (!parsed.success)
        return response({ error: { code: "invalid_request", requestId } }, requestId, 400);
      const { from, to, environmentId, appId, scope, processEpoch, stepMs } = parsed.data;
      const context = {
        environmentId,
        appId,
        instanceId: String(params.instanceId),
        resource: null,
        scope: scope as "host" | "container" | "process",
        window: { fromMs: Date.parse(from), toMs: Date.parse(to) },
      } as const;
      if (!scenario.instances.some((instance) => instance.id === params.instanceId))
        return response({ error: { code: "not_found", requestId } }, requestId, 404);
      const value = detailFor({ context, processEpoch, stepMs }, scenario);
      if (value.instance.instanceId !== params.instanceId)
        return response({ error: { code: "not_found", requestId } }, requestId, 404);
      if (value.instance.processEpoch !== processEpoch)
        return response({ error: { code: "target_retired", requestId } }, requestId, 410);
      return response(detailToWire(value), requestId);
    }),
  ]);
}
