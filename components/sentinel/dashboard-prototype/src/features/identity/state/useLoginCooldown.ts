import { useEffect, useState } from "react";
import type {
  AuthenticationSnapshot,
  AuthenticationWorkflow,
} from "../application/authenticationWorkflow";
import { loginRetryDelayMs } from "../model/loginRetry";

const MILLISECONDS_PER_SECOND = 1_000;
const COOLDOWN_UPDATE_INTERVAL_MS = 250;

/** Keeps a server-advised login cooldown local to the mounted login route. */
export function useLoginCooldown(
  workflow: AuthenticationWorkflow,
  loginSnapshot: AuthenticationSnapshot["login"],
): {
  readonly retryAfterSeconds: number;
  readonly recordRateLimit: (error: unknown) => void;
} {
  const [retryAfterSeconds, setRetryAfterSeconds] = useState(() =>
    Math.ceil(workflow.getLoginRetryAfterMs() / MILLISECONDS_PER_SECOND),
  );
  const cooling = retryAfterSeconds > 0;

  useEffect(() => {
    const update = () => {
      const seconds = Math.ceil(workflow.getLoginRetryAfterMs() / MILLISECONDS_PER_SECOND);
      setRetryAfterSeconds(seconds);
    };
    update();
    if (workflow.getLoginRetryAfterMs() === 0) return;
    const timer = window.setInterval(update, COOLDOWN_UPDATE_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [cooling, loginSnapshot, workflow]);

  return {
    retryAfterSeconds,
    recordRateLimit(error) {
      const delayMs = loginRetryDelayMs(error);
      if (delayMs === null) return;
      setRetryAfterSeconds(
        Math.ceil(Math.max(delayMs, workflow.getLoginRetryAfterMs()) / MILLISECONDS_PER_SECOND),
      );
    },
  };
}
