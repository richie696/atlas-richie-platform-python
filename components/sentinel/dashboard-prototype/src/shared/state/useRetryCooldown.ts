import { useEffect, useMemo, useState } from "react";
import type { AppError } from "@richie696/react-framework";

/**
 * Disable a user-triggered retry for the duration of a normalized server hint.
 * This hook never starts or replays a request; the caller still owns the action.
 */
export function useRetryCooldown(error: AppError | undefined, retryUntilMs?: number): boolean {
  const retryAfterMs = error?.retryAfterMs;
  const hasRetryCooldown =
    retryAfterMs !== undefined && Number.isSafeInteger(retryAfterMs) && retryAfterMs > 0;
  const hasDeadline =
    retryUntilMs !== undefined && Number.isFinite(retryUntilMs) && retryUntilMs > 0;
  const deadlineToken = useMemo(
    () =>
      hasDeadline && retryUntilMs !== undefined
        ? Object.freeze({ deadline: retryUntilMs })
        : undefined,
    [hasDeadline, retryUntilMs],
  );
  const errorToken = useMemo(
    () =>
      hasRetryCooldown && error !== undefined && retryAfterMs !== undefined
        ? Object.freeze({})
        : undefined,
    [error, hasRetryCooldown, retryAfterMs],
  );
  const cooldownToken = deadlineToken ?? errorToken;
  const [expiredToken, setExpiredToken] = useState<object>();

  useEffect(() => {
    if (!cooldownToken) return;
    const delayMs =
      deadlineToken && retryUntilMs !== undefined
        ? Math.max(0, retryUntilMs - globalThis.performance.now())
        : retryAfterMs;
    if (delayMs === undefined) return;
    const timer = globalThis.setTimeout(() => setExpiredToken(cooldownToken), delayMs);
    return () => globalThis.clearTimeout(timer);
  }, [cooldownToken, deadlineToken, retryAfterMs, retryUntilMs]);

  return cooldownToken !== undefined && expiredToken !== cooldownToken;
}
