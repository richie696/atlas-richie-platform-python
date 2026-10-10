import type { z } from "zod";
import { instantToMilliseconds } from "../../../core/api/protocol/common";
import {
  observationContextFromWire,
  metricReadingFromWire,
  metricBundleFromWire,
} from "../../../shared/api/observationMapper";
import type {
  InstanceCatalog,
  InstanceObservation,
  ObservedInstance,
} from "../model/instanceObservation";
import type {
  InstanceCatalogSchema,
  InstanceObservationSchema,
  ObservedInstanceSchema,
} from "./instanceWire";

export function observedInstanceFromWire(
  value: z.infer<typeof ObservedInstanceSchema>,
): ObservedInstance {
  const { lastReportAt, processMetrics, ruleReceipt: wireReceipt, ...identity } = value;
  const { receivedAt, ...ruleReceipt } = wireReceipt;
  return {
    ...identity,
    lastReportAtMs: lastReportAt === null ? null : instantToMilliseconds(lastReportAt),
    processMetrics: processMetrics.map(metricReadingFromWire),
    ruleReceipt: {
      ...ruleReceipt,
      receivedAtMs: receivedAt === null ? null : instantToMilliseconds(receivedAt),
    },
  };
}
export function instanceCatalogFromWire(
  value: z.infer<typeof InstanceCatalogSchema>,
): InstanceCatalog {
  return {
    query: { ...value.query, context: observationContextFromWire(value.query.context) },
    asOfMs: instantToMilliseconds(value.asOf),
    coverage: value.coverage,
    totalInstances: value.totalInstances,
    attentionInstances: value.attentionInstances,
    filteredTotal: value.filteredTotal,
    items: value.items.map(observedInstanceFromWire),
  };
}
export function instanceObservationFromWire(
  value: z.infer<typeof InstanceObservationSchema>,
): InstanceObservation {
  return {
    query: { ...value.query, context: observationContextFromWire(value.query.context) },
    asOfMs: instantToMilliseconds(value.asOf),
    instance: observedInstanceFromWire(value.instance),
    metrics: value.metrics === null ? null : metricBundleFromWire(value.metrics),
  };
}
