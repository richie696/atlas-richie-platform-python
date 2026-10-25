import { AppError } from "@richie696/react-framework";
import { CONSOLE_ERROR_STATUS, CONSOLE_WIRE_LIMIT } from "../../../core/api/protocol/common";

/** Return only a valid, bounded server delay for the known login rate-limit response. */
export function loginRetryDelayMs(error: unknown): number | null {
  if (
    !(error instanceof AppError) ||
    error.status !== CONSOLE_ERROR_STATUS.rate_limited ||
    error.code !== "rate_limited"
  )
    return null;
  const delay = error.retryAfterMs;
  if (!Number.isSafeInteger(delay) || delay === undefined || delay <= 0) return null;
  return Math.min(delay, CONSOLE_WIRE_LIMIT.RetryAfterMs);
}
