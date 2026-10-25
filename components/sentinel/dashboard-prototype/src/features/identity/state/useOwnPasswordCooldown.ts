import { useEffect, useState } from "react";
import type { OwnPasswordWorkflow } from "../application/ownPasswordWorkflow";
import type { OwnPasswordReceipt } from "../api/ownPasswordPort";
import type { CommandSnapshot } from "../../../shared/state/commandResource";

const MILLISECONDS_PER_SECOND = 1_000;
const COOLDOWN_UPDATE_INTERVAL_MS = 250;

/** Project a session-local server cooldown into an accessible retry countdown. */
export function useOwnPasswordCooldown(
  workflow: OwnPasswordWorkflow,
  snapshot: CommandSnapshot<OwnPasswordReceipt>,
): number {
  const [retryAfterSeconds, setRetryAfterSeconds] = useState(() =>
    Math.ceil(workflow.getRetryAfterMs() / MILLISECONDS_PER_SECOND),
  );
  const cooling = retryAfterSeconds > 0;

  useEffect(() => {
    const update = () =>
      setRetryAfterSeconds(Math.ceil(workflow.getRetryAfterMs() / MILLISECONDS_PER_SECOND));
    update();
    if (workflow.getRetryAfterMs() === 0) return;
    const timer = window.setInterval(update, COOLDOWN_UPDATE_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [cooling, snapshot, workflow]);

  return retryAfterSeconds;
}
