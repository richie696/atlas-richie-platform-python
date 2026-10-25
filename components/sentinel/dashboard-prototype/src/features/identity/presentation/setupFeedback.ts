import type {
  InitializationSnapshot,
  InitializationState,
} from "../application/initializationWorkflow";
import type { TranslationKey } from "../../../shared/types/translation";

type InitializationRejectionReason = Extract<
  InitializationState,
  { readonly status: "rejected" }
>["reason"];

const REJECTION_COPY = Object.freeze({
  validation: "setup.workflow.rejected.validation",
  "setup-closed": "setup.workflow.rejected.setupClosed",
  dependency: "setup.workflow.rejected.dependency",
} satisfies Record<InitializationRejectionReason, TranslationKey>);

const STATUS_COPY = Object.freeze({
  idle: "setup.workflow.idle",
  closed: "setup.workflow.closed",
  submitting: "setup.workflow.submitting",
  checking: "setup.workflow.checking",
  pending: "setup.workflow.pending",
  "result-unknown": "setup.workflow.unknown",
  ready: "setup.workflow.ready",
  error: "setup.workflow.error",
  conflict: "setup.workflow.conflict",
} satisfies Record<Exclude<InitializationState["status"], "rejected">, TranslationKey>);

/** Projects an initialization outcome into safe, reason-specific localized feedback. */
export function initializationFeedbackKey(state: InitializationState): TranslationKey {
  return state.status === "rejected" ? REJECTION_COPY[state.reason] : STATUS_COPY[state.status];
}

/**
 * Identifies authoritative setup closure without racing this page's own command.
 * A confirmed successful initialization remains a completion, not an external close.
 */
export function isSetupAuthorityClosed(snapshot: InitializationSnapshot): boolean {
  const status = snapshot.initialization.status;
  if (
    status === "closed" ||
    (status === "rejected" && snapshot.initialization.reason === "setup-closed")
  )
    return true;

  const bootstrap = snapshot.bootstrap;
  const bootstrapClosed =
    bootstrap.status === "ready" && (bootstrap.data.initialized || !bootstrap.data.setupAvailable);
  const ownCommandInFlight = ["submitting", "checking", "pending"].includes(status);
  return bootstrapClosed && !ownCommandInFlight && status !== "ready";
}
