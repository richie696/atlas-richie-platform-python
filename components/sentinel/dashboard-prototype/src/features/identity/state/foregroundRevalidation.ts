import type { AuthenticationWorkflow } from "../application/authenticationWorkflow";

interface EventSource {
  addEventListener(type: string, listener: () => void): void;
  removeEventListener(type: string, listener: () => void): void;
}

interface VisibilitySource extends EventSource {
  readonly visibilityState: string;
}

/** Revalidate the shared identity owner when the app returns to the foreground. */
export function observeAuthenticationForeground(
  workflow: Pick<AuthenticationWorkflow, "revalidateAccess">,
  windowTarget: EventSource,
  documentTarget: VisibilitySource,
): () => void {
  const revalidate = () => {
    if (documentTarget.visibilityState !== "visible") return;
    void workflow.revalidateAccess().catch(() => {
      // The workflow publishes an unavailable/stale read state for explicit recovery.
    });
  };
  windowTarget.addEventListener("focus", revalidate);
  documentTarget.addEventListener("visibilitychange", revalidate);
  return () => {
    windowTarget.removeEventListener("focus", revalidate);
    documentTarget.removeEventListener("visibilitychange", revalidate);
  };
}
