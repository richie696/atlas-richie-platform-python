import type { z } from "zod";
import { instantToMilliseconds, millisecondsToInstant } from "../../../core/api/protocol/common";
import type {
  AuditPage,
  AuditQuery,
  SystemConnections,
  SystemProtocols,
} from "../model/systemObservation";
import type {
  AuditPageSchema,
  AuditQueryParametersSchema,
  SystemConnectionsSchema,
  SystemProtocolsSchema,
} from "./systemObservationWire";

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
