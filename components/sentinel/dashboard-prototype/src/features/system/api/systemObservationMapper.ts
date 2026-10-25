import type { z } from "zod";
import { instantToMilliseconds, millisecondsToInstant } from "../../../core/api/protocol/common";
import type {
  AuditPage,
  AuditQuery,
  AgentReportingObservationPage,
  IncidentEventObservationPage,
  SystemConnections,
  SystemProtocols,
} from "../model/systemObservation";
import type { DeploymentGuidesSnapshot } from "../model/deploymentGuide";
import type {
  AuditPageSchema,
  AuditQueryParametersSchema,
  SystemConnectionsSchema,
  SystemProtocolsSchema,
  AgentReportingObservationPageSchema,
  IncidentEventObservationPageSchema,
  DeploymentGuidesSchema,
} from "./systemObservationWire";

export function deploymentGuidesFromWire(
  value: z.infer<typeof DeploymentGuidesSchema>,
): DeploymentGuidesSnapshot {
  return value;
}

export function systemConnectionsFromWire(
  value: z.infer<typeof SystemConnectionsSchema>,
): SystemConnections {
  return {
    asOfMs: instantToMilliseconds(value.asOf),
    items: value.items.map(({ checkedAt, expiresAt, ...item }) => ({
      ...item,
      checkedAtMs: checkedAt === null ? null : instantToMilliseconds(checkedAt),
      expiresAtMs: expiresAt === null ? null : instantToMilliseconds(expiresAt),
    })),
  };
}
export function systemProtocolsFromWire(
  value: z.infer<typeof SystemProtocolsSchema>,
): SystemProtocols {
  return {
    asOfMs: instantToMilliseconds(value.asOf),
    items: value.items.map(({ observedAt, ...item }) => ({
      ...item,
      observedAtMs: observedAt === null ? null : instantToMilliseconds(observedAt),
    })),
  };
}
export function agentReportingObservationsFromWire(
  value: z.infer<typeof AgentReportingObservationPageSchema>,
): AgentReportingObservationPage {
  return runtimeProtocolObservationsFromWire(value);
}
export function incidentEventObservationsFromWire(
  value: z.infer<typeof IncidentEventObservationPageSchema>,
): IncidentEventObservationPage {
  return runtimeProtocolObservationsFromWire(value);
}
function runtimeProtocolObservationsFromWire<
  Item extends { readonly observedAt: string | null },
>(value: {
  readonly asOf: string;
  readonly page: number;
  readonly pageSize: number;
  readonly total: number;
  readonly items: readonly Item[];
}): {
  readonly asOfMs: number;
  readonly page: number;
  readonly pageSize: number;
  readonly total: number;
  readonly items: readonly (Omit<Item, "observedAt"> & { readonly observedAtMs: number | null })[];
} {
  return {
    asOfMs: instantToMilliseconds(value.asOf),
    page: value.page,
    pageSize: value.pageSize,
    total: value.total,
    items: value.items.map((item) => {
      const { observedAt, ...rest } = item;
      return {
        ...rest,
        observedAtMs: observedAt === null ? null : instantToMilliseconds(observedAt),
      };
    }),
  };
}
export function auditQueryToWire(value: AuditQuery): z.infer<typeof AuditQueryParametersSchema> {
  return {
    start: millisecondsToInstant(value.startMs),
    end: millisecondsToInstant(value.endMs),
    ...(value.actorId ? { actorId: value.actorId } : {}),
    ...(value.action === null ? {} : { action: value.action }),
    ...(value.result === null ? {} : { result: value.result }),
    page: value.page,
    pageSize: value.pageSize,
  };
}
export function auditPageFromWire(value: z.infer<typeof AuditPageSchema>): AuditPage {
  const { start, end, ...query } = value.query;
  return {
    query: {
      ...query,
      startMs: instantToMilliseconds(start),
      endMs: instantToMilliseconds(end),
    },
    asOfMs: instantToMilliseconds(value.asOf),
    total: value.total,
    items: value.items.map(({ occurredAt, ...record }) => ({
      ...record,
      occurredAtMs: instantToMilliseconds(occurredAt),
    })),
  };
}
