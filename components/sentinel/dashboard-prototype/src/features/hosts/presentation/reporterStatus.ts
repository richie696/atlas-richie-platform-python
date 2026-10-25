import type { HostAssociation } from "../application/hostAssociationPort";

export const REPORTER_STALE_AFTER_MS = 90_000;
const FUTURE_CLOCK_TOLERANCE_MS = 5_000;

export type ReporterFreshness = "active" | "stale" | "unknown" | "unavailable";

/** Classify only from the authenticated collector heartbeat; never infer health from enrollment alone. */
export function reporterFreshness(
  association: Pick<HostAssociation, "reporterActive" | "lastReceivedAt">,
  asOfMs: number,
): ReporterFreshness {
  if (!association.reporterActive) return "unavailable";
  if (!Number.isFinite(asOfMs) || association.lastReceivedAt === null) return "unknown";
  const receivedAtMs = Date.parse(association.lastReceivedAt);
  if (!Number.isFinite(receivedAtMs) || receivedAtMs > asOfMs + FUTURE_CLOCK_TOLERANCE_MS) {
    return "unknown";
  }
  return asOfMs - receivedAtMs > REPORTER_STALE_AFTER_MS ? "stale" : "active";
}
