import { useEffect, useState } from "react";
import { loginRetryDelayMs } from "../presentation/loginFeedback";

const MILLISECONDS_PER_SECOND = 1_000;
const COOLDOWN_UPDATE_INTERVAL_MS = 250;

/** Keeps a server-advised login cooldown local to the mounted login route. */
export function useLoginCooldown(): {
  readonly retryAfterSeconds: number;
  readonly recordRateLimit: (error: unknown) => void;
} {
  const [deadline, setDeadline] = useState<number | null>(null);
  const [retryAfterSeconds, setRetryAfterSeconds] = useState(0);

  useEffect(() => {
    if (deadline === null) return;
    const update = () => {
      const seconds = Math.max(0, Math.ceil((deadline - Date.now()) / MILLISECONDS_PER_SECOND));
      setRetryAfterSeconds(seconds);
      if (seconds === 0) setDeadline(null);
    };
    const timer = window.setInterval(update, COOLDOWN_UPDATE_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [deadline]);

  return {
    retryAfterSeconds,
    recordRateLimit(error) {
      const delayMs = loginRetryDelayMs(error);
      if (delayMs === null) return;
      setRetryAfterSeconds(Math.ceil(delayMs / MILLISECONDS_PER_SECOND));
      setDeadline(Date.now() + delayMs);
    },
  };
}
