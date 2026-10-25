import { AppError, AppErrorKind, StateStore } from "@richie696/react-framework";

export const COMMAND_STATUS = Object.freeze({
  Idle: "idle",
  Pending: "pending",
  Success: "success",
  Error: "error",
  Conflict: "conflict",
  Unknown: "result-unknown",
} as const);
export const DEFAULT_COMMAND_TIMEOUT_MS = 10_000;
/** A cancelled/timed-out write is not proof that the server rolled it back. */
export type CommandSnapshot<Result> =
  | { readonly status: "idle" | "pending" }
  | { readonly status: "success"; readonly result: Result }
  | { readonly status: "error" | "conflict" | "result-unknown"; readonly error: AppError };

export interface CommandResource<Input, Result> {
  readonly getSnapshot: () => CommandSnapshot<Result>;
  readonly subscribe: (listener: () => void) => () => void;
  /** Explicit execution only. Pending/unknown outcomes cannot be automatically replayed. */
  readonly run: (input: Input) => Promise<Result>;
  readonly cancel: () => void;
  /** Explicit acknowledgement after outcome investigation; never automatic retry or form destruction. */
  readonly reset: () => void;
  readonly dispose: () => void;
}

/**
 * Own one mutation lifecycle and its duplicate guard. Form values stay with the
 * feature and are never copied here, logged, persisted or cleared on failure.
 * Transport/server idempotency and operation lookup remain separate contracts.
 */
export function createCommandResource<Input, Result>(
  execute: (input: Input, signal: AbortSignal) => Promise<Result>,
  options: { readonly timeoutMs?: number } = {},
): CommandResource<Input, Result> {
  const timeoutMs = options.timeoutMs ?? DEFAULT_COMMAND_TIMEOUT_MS;
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) throw new Error("Invalid command timeout");
  const idle = Object.freeze({ status: COMMAND_STATUS.Idle });
  const state = new StateStore<CommandSnapshot<Result>>(idle);
  let controller: AbortController | undefined,
    disposed = false,
    generation = 0;
  return Object.freeze({
    getSnapshot: state.getSnapshot,
    subscribe: state.subscribe,
    async run(input: Input) {
      if (disposed) throw new AppError(AppErrorKind.CANCELLED, "Command owner disposed");
      if (controller || state.getSnapshot().status === COMMAND_STATUS.Unknown)
        throw new AppError(AppErrorKind.DUPLICATE, "Pending or unconfirmed command");
      const ticket = ++generation,
        current = new AbortController();
      controller = current;
      state.set({ status: COMMAND_STATUS.Pending });
      let dispatched = false;
      let onAbort: () => void = () => {};
      const aborted = new Promise<never>((_, reject) => {
        onAbort = () =>
          reject(
            current.signal.reason instanceof AppError
              ? current.signal.reason
              : new AppError(AppErrorKind.CANCELLED, "Command observation cancelled"),
          );
        current.signal.addEventListener("abort", onAbort, { once: true });
      });
      const timer = setTimeout(
        () => current.abort(new AppError(AppErrorKind.TIMEOUT, "Command observation timed out")),
        timeoutMs,
      );
      try {
        const result = await Promise.race([
          Promise.resolve().then(() => {
            if (current.signal.aborted)
              throw new AppError(AppErrorKind.CANCELLED, "Command observation cancelled");
            dispatched = true;
            return execute(input, current.signal);
          }),
          aborted,
        ]);
        if (ticket === generation) state.set({ status: COMMAND_STATUS.Success, result });
        return result;
      } catch (cause) {
        const error = AppError.fromUnknown(cause);
        if (ticket === generation) {
          const uncertain =
            [AppErrorKind.NETWORK, AppErrorKind.TIMEOUT, AppErrorKind.CANCELLED].includes(
              error.kind,
            ) ||
            (error.kind === AppErrorKind.SERVER && (error.status ?? 0) >= 500);
          state.set(
            !dispatched && error.kind === AppErrorKind.CANCELLED
              ? idle
              : {
                  status: uncertain
                    ? COMMAND_STATUS.Unknown
                    : error.status === 409
                      ? COMMAND_STATUS.Conflict
                      : COMMAND_STATUS.Error,
                  error,
                },
          );
        }
        throw error;
      } finally {
        clearTimeout(timer);
        current.signal.removeEventListener("abort", onAbort);
        if (ticket === generation) controller = undefined;
      }
    },
    cancel() {
      controller?.abort();
    },
    reset() {
      if (controller) throw new AppError(AppErrorKind.DUPLICATE, "Cannot reset a pending command");
      state.set(idle);
    },
    dispose() {
      if (disposed) return;
      generation++;
      controller?.abort();
      controller = undefined;
      disposed = true;
      state.complete();
    },
  });
}
