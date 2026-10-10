import { AppError, AppErrorKind, StateStore } from "@richie696/react-framework";
import { createCommandResource, type CommandSnapshot } from "../../../shared/state/commandResource";
import {
  createOwnedQueryResource,
  type QueryAccessObserver,
} from "../../../shared/state/ownedQueryResource";
import type { RuleSetPort } from "../api/ruleSetPort";
import { validRuleOperationObservation } from "../model/ruleOperationPolicy";
import {
  RULE_REJECTION,
  type RuleMutationInput,
  type RuleMutation,
  type RuleMutationResult,
  type RuleOperationObservation,
} from "../model/ruleSetOperations";

export const RULE_OPERATION_TIMEOUT_MS = 10_000;
/** Public safe lookup identity, never the rule body, draft form, credential or original error text. */
export interface RuleOperationIdentity {
  readonly requestKey: string;
  readonly bindingId: string;
  readonly kind: RuleMutation["kind"];
}
export interface RuleOperationSnapshot {
  readonly authorized: boolean;
  readonly command: CommandSnapshot<RuleMutationResult>;
  readonly operation: RuleOperationIdentity | null;
  readonly inspecting: boolean;
}
/** Consumers mask mutation facts when either their read scope or write capability is lost. */
export const HIDDEN_RULE_OPERATION: RuleOperationSnapshot = Object.freeze({
  authorized: false,
  command: Object.freeze({ status: "idle" as const }),
  operation: null,
  inspecting: false,
});
export type RuleOperation = ReturnType<typeof createRuleOperation>;
const REJECTION_STATUS = Object.freeze({
  validation: 422,
  conflict: 409,
  not_found: 404,
  unsupported: 422,
  unavailable: 503,
});
const invalidReceipt = () =>
  new AppError(AppErrorKind.SERVER, "Unconfirmed rule operation receipt", {
    status: 502,
    code: "rule_receipt_invalid",
  });
function rejectedObservation(value: RuleOperationObservation): AppError {
  const reason = value.status === "rejected" ? value.reason : RULE_REJECTION.Unavailable;
  // A durable rejection is terminal even when its reason is unavailable; do not reinterpret it as a write timeout.
  return new AppError(AppErrorKind.PROTOCOL, "Rule operation rejected", {
    status: REJECTION_STATUS[reason],
    code: reason,
  });
}
const SAFE_ERROR_CODES: ReadonlySet<string> = new Set([
  ...Object.values(RULE_REJECTION),
  "rule_receipt_invalid",
  "rule_operation_pending",
]);
function safeError(cause: unknown): AppError {
  const error = AppError.fromUnknown(cause);
  return new AppError(error.kind, "Rule operation failed", {
    status: error.status,
    code: error.code && SAFE_ERROR_CODES.has(error.code) ? error.code : undefined,
  });
}
function safeSnapshot(
  snapshot: CommandSnapshot<RuleMutationResult>,
): CommandSnapshot<RuleMutationResult> {
  return "error" in snapshot
    ? {
        ...snapshot,
        error: safeError(snapshot.error),
      }
    : snapshot;
}

/**
 * One binding/session-bound command observer, reused by draft/version/publication/plan use cases.
 * Compose foundation command/query mechanics; never replay a write to recover its outcome.
 * Durable acceptance only confirms the command result, not application loading or scheduler execution.
 */
export function createRuleOperation(
  bindingId: string,
  port: Pick<RuleSetPort, "mutateRuleSet" | "readRuleOperation">,
  access: QueryAccessObserver,
  newRequestKey: () => string,
  options: { readonly timeoutMs?: number } = {},
) {
  const timeoutMs = options.timeoutMs ?? RULE_OPERATION_TIMEOUT_MS;
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0 || !bindingId.trim())
    throw new Error("Invalid rule operation configuration");
  const ownerKey = access.read().ownerKey;
  let disposed = false,
    running = false,
    expected: RuleMutation | null = null,
    inspecting = false;
  let confirmed: CommandSnapshot<RuleMutationResult> | null = null;
  const allowed = () => !disposed && access.read().allowed && access.read().ownerKey === ownerKey;
  function assertOwner() {
    if (!allowed())
      throw new AppError(AppErrorKind.FORBIDDEN, "Rule operation access unavailable", {
        status: 403,
      });
  }
  const command = createCommandResource<RuleMutation, RuleMutationResult>(
    async (mutation, signal) => {
      assertOwner();
      const value = await port.mutateRuleSet(mutation, signal);
      assertOwner();
      if (signal.aborted) throw new AppError(AppErrorKind.CANCELLED, "Rule observation cancelled");
      if (!validRuleOperationObservation(value, mutation, false)) throw invalidReceipt();
      if (value.status === "rejected") throw rejectedObservation(value);
      if (value.status !== "completed")
        throw new AppError(AppErrorKind.SERVER, "Rule operation still pending", {
          status: 502,
          code: "rule_operation_pending",
        });
      return value.result;
    },
    { timeoutMs },
  );
  const inspection = createOwnedQueryResource<RuleMutation, RuleOperationObservation>(access, {
    keyOf: (mutation) => JSON.stringify([bindingId, mutation.requestKey]),
    timeoutMs,
    async read(mutation, signal) {
      assertOwner();
      const value = await port.readRuleOperation(bindingId, mutation.requestKey, signal);
      assertOwner();
      if (!validRuleOperationObservation(value, mutation, true)) throw invalidReceipt();
      return value;
    },
    classify: () => "ready",
  });
  const idle = Object.freeze({ status: "idle" } as const);
  function snapshot(): RuleOperationSnapshot {
    const authorized = allowed();
    return {
      authorized,
      command: authorized ? (confirmed ?? safeSnapshot(command.getSnapshot())) : idle,
      operation:
        authorized && expected !== null
          ? { requestKey: expected.requestKey, bindingId, kind: expected.kind }
          : null,
      inspecting: authorized && inspecting,
    };
  }
  const state = new StateStore(snapshot());
  const publish = () => state.set(snapshot());
  const unsubscribeCommand = command.subscribe(publish);
  const unsubscribeAccess = access.subscribe(() => {
    if (!allowed()) {
      // Same-session reauthorization may inspect the original private expectation.
      // No body is exposed while denied; a different session cannot inherit it.
      if (access.read().ownerKey !== ownerKey) expected = null;
      confirmed = null;
      command.cancel();
      if (!["pending", "result-unknown"].includes(command.getSnapshot().status)) {
        expected = null;
        command.reset();
      }
      inspection.reset();
    }
    publish();
  });
  return Object.freeze({
    getSnapshot: state.getSnapshot,
    subscribe: state.subscribe,
    async run(input: RuleMutationInput): Promise<RuleMutationResult> {
      assertOwner();
      if (
        running ||
        inspecting ||
        ["pending", "result-unknown"].includes(command.getSnapshot().status)
      )
        throw new AppError(AppErrorKind.DUPLICATE, "Rule operation unresolved");
      if (
        ("candidate" in input && input.candidate.bindingId !== bindingId) ||
        ("schedule" in input && input.schedule.bindingId !== bindingId)
      )
        throw new AppError(AppErrorKind.PROTOCOL, "Wrong binding", { status: 400 });
      const requestKey = newRequestKey();
      if (!requestKey.trim() || requestKey === expected?.requestKey)
        throw new AppError(AppErrorKind.PROTOCOL, "Invalid new request identity", { status: 400 });
      expected = { ...structuredClone(input), bindingId, requestKey };
      confirmed = null;
      running = true;
      try {
        const result = await command.run(expected);
        assertOwner();
        return result;
      } catch (cause) {
        throw safeError(cause);
      } finally {
        running = false;
        publish();
      }
    },
    async inspect(): Promise<RuleOperationObservation> {
      assertOwner();
      if (running || inspecting || !expected || command.getSnapshot().status !== "result-unknown")
        throw new AppError(AppErrorKind.DUPLICATE, "No unresolved rule operation to inspect");
      const mutation = expected;
      inspecting = true;
      publish();
      try {
        const value = await inspection.load(mutation);
        assertOwner();
        if (expected !== mutation) throw new AppError(AppErrorKind.CANCELLED, "Rule owner changed");
        if (value.status === "completed") confirmed = { status: "success", result: value.result };
        else if (value.status === "rejected") {
          const error = rejectedObservation(value);
          confirmed = { status: error.status === 409 ? "conflict" : "error", error };
        }
        if (confirmed) command.reset();
        return value;
      } catch (cause) {
        throw safeError(cause);
      } finally {
        inspecting = false;
        publish();
      }
    },
    cancel() {
      command.cancel();
      inspection.cancel();
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      expected = null;
      confirmed = null;
      unsubscribeCommand();
      unsubscribeAccess();
      command.dispose();
      inspection.dispose();
      state.set(snapshot());
      state.complete();
    },
  });
}
