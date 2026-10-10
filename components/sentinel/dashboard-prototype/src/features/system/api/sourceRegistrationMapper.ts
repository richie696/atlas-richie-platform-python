import { instantToMilliseconds } from "../../../core/api/protocol/common";
import type { z } from "zod";
import type {
  SourceCheckResult,
  SourceOperationObservation,
  SourceRegistrySnapshot,
} from "../model/sourceRegistration";
import type {
  SourceCheckResultSchema,
  SourceOperationObservationSchema,
  SourceRegistrySchema,
} from "./sourceRegistrationWire";

export function sourceRegistryFromWire(
  value: z.infer<typeof SourceRegistrySchema>,
): SourceRegistrySnapshot {
  return { asOfMs: instantToMilliseconds(value.asOf), items: value.items };
}
export function sourceCheckFromWire(
  value: z.infer<typeof SourceCheckResultSchema>,
): SourceCheckResult {
  const timestamps = {
    checkedAtMs: instantToMilliseconds(value.checkedAt),
    expiresAtMs: instantToMilliseconds(value.expiresAt),
  };
  return value.status === "reachable"
    ? { ...timestamps, status: value.status, capabilities: value.capabilities }
    : { ...timestamps, status: value.status, reason: value.reason };
}
export function sourceOperationFromWire(
  value: z.infer<typeof SourceOperationObservationSchema>,
): SourceOperationObservation {
  if (value.status === "completed") return value;
  if (value.status === "rejected")
    return { ...value, reason: value.reason === "not_found" ? "not-found" : value.reason };
  return { ...value, status: value.status === "not_found" ? "not-found" : value.status };
}
