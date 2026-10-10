import type { z } from "zod";
import { instantToMilliseconds, millisecondsToInstant } from "../../core/api/protocol/common";
import { parseConsoleInput } from "../../core/api/protocol/parseInput";
import type {
  MetricBundle,
  MetricQuery,
  MetricReading,
  ObservationContext,
} from "../model/observation";
import {
  ObservationContextParametersSchema,
  type MetricReadingSchema,
  type ObservationContextWire,
  type MetricQueryWire,
  type MetricBundleWire,
} from "./observationWire";

export function observationContextFromWire(value: ObservationContextWire): ObservationContext {
  return {
    ...value,
    window: {
      fromMs: instantToMilliseconds(value.window.from),
      toMs: instantToMilliseconds(value.window.to),
    },
  };
}
export function observationContextToWire(value: ObservationContext): ObservationContextWire {
  return {
    ...value,
    window: {
      from: millisecondsToInstant(value.window.fromMs),
      to: millisecondsToInstant(value.window.toMs),
    },
  };
}
/** Only the documented instant fields are mapped. stepMs and metric units remain domain values. */
export function metricQueryFromWire(value: MetricQueryWire): MetricQuery {
  return { ...value, context: observationContextFromWire(value.context) };
}
export function metricReadingFromWire(value: z.infer<typeof MetricReadingSchema>): MetricReading {
  const { sampledAt, ...fact } = value;
  return { ...fact, sampledAtMs: sampledAt === null ? null : instantToMilliseconds(sampledAt) };
}
export function metricBundleFromWire(value: MetricBundleWire): MetricBundle {
  return {
    query: metricQueryFromWire(value.query),
    asOfMs: instantToMilliseconds(value.asOf),
    summary: value.summary.map(metricReadingFromWire),
    series: value.series.map((series) => ({
      ...series,
      samples: series.samples.map(({ at, value: sampleValue }) => ({
        atMs: instantToMilliseconds(at),
        value: sampleValue,
      })),
    })),
    annotations: value.annotations.map(({ at, ...annotation }) => ({
      ...annotation,
      atMs: instantToMilliseconds(at),
    })),
  };
}
export function observationContextParameters(value: ObservationContext) {
  return parseConsoleInput(ObservationContextParametersSchema, {
    environmentId: value.environmentId,
    appId: value.appId ?? undefined,
    instanceId: value.instanceId ?? undefined,
    resource: value.resource ?? undefined,
    scope: value.scope,
    from: millisecondsToInstant(value.window.fromMs),
    to: millisecondsToInstant(value.window.toMs),
  });
}
