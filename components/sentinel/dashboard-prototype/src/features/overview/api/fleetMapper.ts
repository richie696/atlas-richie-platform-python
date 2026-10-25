import type { z } from "zod";
import { instantToMilliseconds } from "../../../core/api/protocol/common";
import {
  observationContextFromWire,
  metricBundleFromWire,
  metricReadingFromWire,
} from "../../../shared/api/observationMapper";
import type { FleetSnapshot } from "../model/fleet";
import type { FleetSnapshotSchema } from "./fleetWire";

export function fleetSnapshotFromWire(value: z.infer<typeof FleetSnapshotSchema>): FleetSnapshot {
  return {
    query: { ...value.query, context: observationContextFromWire(value.query.context) },
    asOfMs: instantToMilliseconds(value.asOf),
    coverage: value.coverage,
    totalApplications: value.totalApplications,
    attentionApplications: value.attentionApplications,
    attentionTargets: value.attentionTargets,
    applications: {
      ...value.applications,
      items: value.applications.items.map((application) => ({
        ...application,
        metrics: application.metrics.map(metricReadingFromWire),
      })),
    },
    metrics: metricBundleFromWire(value.metrics),
    connections: value.connections.map(({ checkedAt, ...connection }) => ({
      ...connection,
      checkedAtMs: checkedAt === null ? null : instantToMilliseconds(checkedAt),
    })),
  };
}
