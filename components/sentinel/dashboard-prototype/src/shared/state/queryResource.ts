import { AppError, AppErrorKind, ObservableResource, StateStore } from "@richie696/react-framework";

/** Product presentation states; wire DTOs and HTTP status codes do not belong here. */
export const QUERY_STATUS = Object.freeze({
  Idle: "idle",
  Loading: "loading",
  Refreshing: "refreshing",
  Ready: "ready",
  Empty: "empty",
  FilteredEmpty: "filtered-empty",
  Denied: "denied",
  Error: "error",
  Stale: "stale",
  Partial: "partial",
} as const);
export type QueryDataStatus = "ready" | "empty" | "filtered-empty" | "partial";
/** A read must not keep the feature pending indefinitely, even with a nonresponsive Port. */
export const DEFAULT_QUERY_TIMEOUT_MS = 10_000;
const AUTHORITATIVE_ABSENCE_STATUSES: ReadonlySet<number> = new Set([404, 410]);

/** Locally received value. receivedAt is NOT the remote metric's sample time. */
export interface QueryValue<T> {
  readonly key: string;
  readonly data: T;
  readonly receivedAt: number;
}

/** Discriminated lifecycle: denied has no data; refreshing/stale require a trusted same-key value. */
export type QuerySnapshot<T> =
  | { readonly status: "idle" }
  | { readonly status: "loading"; readonly key: string }
  | (QueryValue<T> & { readonly status: QueryDataStatus })
  | (QueryValue<T> & { readonly status: "refreshing" })
  | (QueryValue<T> & { readonly status: "stale"; readonly error: AppError })
  | { readonly status: "denied" | "error"; readonly key: string; readonly error: AppError };

/** Framework-neutral lifecycle owner. One instance belongs to one feature resource, never the whole app. */
export interface QueryResource<Query, Value> {
  /** Pure, complete ownership key; contains no credential or secret form value. */
  readonly keyOf: (query: Query) => string;
  readonly getSnapshot: () => QuerySnapshot<Value>;
  readonly subscribe: (listener: () => void) => () => void;
  /** A key must include session/env/app/instance/window and every parameter used by this resource. */
  readonly load: (query: Query) => Promise<Value>;
  /** Abort pending work, restoring only a trusted value for the same key. */
  readonly cancel: () => void;
  /** Clear previous identity/data on logout or owner change. Late responses cannot repopulate it. */
  readonly reset: () => void;
  /** Permanent owner disposal. React's StrictMode cleanup should cancel, not permanently dispose. */
  readonly dispose: () => void;
}

export interface QueryResourceOptions<Query, Value> {
  readonly keyOf: (query: Query) => string;
  readonly read: (query: Query, signal: AbortSignal) => Promise<Value>;
  /** Feature-owned pure projection; empty/filter/coverage meanings are not inferred from arbitrary DTOs. */
  readonly classify: (value: Value) => QueryDataStatus;
  readonly timeoutMs?: number;
  readonly clock?: () => number;
  /** Pure, non-throwing feature policy for authoritative invalidation beyond standard not-found/gone. */
  readonly invalidatesValue?: (error: AppError) => boolean;
}

/**
 * Compose the installed ObservableResource cancellation/generation guard with
 * product-specific stale/denied/empty semantics. No network or fixture implementation.
 * Retain at most ONE last-known-good value, and only reuse it for the exact query key.
 */
export function createQueryResource<Query, Value>(
  options: QueryResourceOptions<Query, Value>,
): QueryResource<Query, Value> {
  const request = new ObservableResource<Value>();
  const idle = Object.freeze({ status: QUERY_STATUS.Idle });
  const state = new StateStore<QuerySnapshot<Value>>(idle);
  let generation = 0,
    currentKey: string | undefined,
    disposed = false;
  let lastGood: (QueryValue<Value> & { readonly status: QueryDataStatus }) | undefined;
  const clock = options.clock ?? Date.now;
  const cancel = () => {
    generation++;
    request.cancel();
    state.set(lastGood && lastGood.key === currentKey ? lastGood : idle);
  };
  const reset = () => {
    generation++;
    request.reset();
    lastGood = undefined;
    currentKey = undefined;
    state.set(idle);
  };
  return Object.freeze({
    keyOf: options.keyOf,
    getSnapshot: state.getSnapshot,
    subscribe: state.subscribe,
    async load(query: Query) {
      if (disposed) throw new AppError(AppErrorKind.CANCELLED, "Resource owner disposed");
      const key = options.keyOf(query);
      const ticket = ++generation;
      currentKey = key;
      if (lastGood?.key !== key) lastGood = undefined;
      state.set(
        lastGood
          ? { ...lastGood, status: QUERY_STATUS.Refreshing }
          : { status: QUERY_STATUS.Loading, key },
      );
      try {
        const data = await request.load((signal) => options.read(query, signal), {
          timeoutMs: options.timeoutMs ?? DEFAULT_QUERY_TIMEOUT_MS,
        });
        if (ticket !== generation)
          throw new AppError(AppErrorKind.CANCELLED, "Superseded resource load");
        lastGood = Object.freeze({
          status: options.classify(data),
          key,
          data,
          receivedAt: clock(),
        });
        state.set(lastGood);
        return data;
      } catch (cause) {
        const error = AppError.fromUnknown(cause);
        if (ticket === generation) {
          // ObservableResource bounds observation but does not abort its loader on
          // timeout. Reuse its cancellation API without changing this query's outcome.
          if (error.kind === AppErrorKind.TIMEOUT) request.cancel();
          if (error.kind === AppErrorKind.UNAUTHORIZED || error.kind === AppErrorKind.FORBIDDEN) {
            lastGood = undefined;
            state.set({ status: QUERY_STATUS.Denied, key, error });
          } else if (
            (error.status !== undefined && AUTHORITATIVE_ABSENCE_STATUSES.has(error.status)) ||
            options.invalidatesValue?.(error)
          ) {
            // An authoritative missing/replaced target is not an offline sample.
            // Clear the cache too: subsequent cancel/unmount must not resurrect it.
            lastGood = undefined;
            state.set({ status: QUERY_STATUS.Error, key, error });
          } else if (error.kind === AppErrorKind.CANCELLED) {
            state.set(lastGood ?? idle);
          } else {
            state.set(
              lastGood
                ? { ...lastGood, status: QUERY_STATUS.Stale, error }
                : { status: QUERY_STATUS.Error, key, error },
            );
          }
        }
        throw error;
      }
    },
    cancel,
    reset,
    dispose() {
      if (disposed) return;
      reset();
      disposed = true;
      request.complete();
      state.complete();
    },
  });
}
