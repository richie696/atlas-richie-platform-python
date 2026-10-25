import { AppError, AppErrorKind, PollingStore, StateStore } from "@richie696/react-framework";
import {
  createOwnedQueryResource,
  type QueryAccessObserver,
} from "../../../shared/state/ownedQueryResource";
import type { QuerySnapshot } from "../../../shared/state/queryResource";
import {
  OBSERVATION_QUALITY,
  validMetricBundle,
  type MetricBundle,
} from "../../../shared/model/observation";
import type { RealtimePort } from "../api/metricsPort";
import {
  DEFAULT_POLL_INTERVAL_MS,
  MIN_POLL_INTERVAL_MS,
  MAX_POLL_INTERVAL_MS,
  MONITOR_MODE,
  realtimeSelectionKey,
  resolveRealtimeQuery,
  validRealtimeSelection,
  type MonitorMode,
  type RealtimeSelection,
} from "../model/monitoring";

export interface RealtimeMonitorSnapshot {
  readonly mode: MonitorMode;
  readonly selection: RealtimeSelection | null;
  readonly observation: QuerySnapshot<MetricBundle>;
  readonly intervalMs: number;
}
export interface RealtimeMonitor {
  readonly getSnapshot: () => RealtimeMonitorSnapshot;
  readonly subscribe: (listener: () => void) => () => void;
  readonly start: (selection: RealtimeSelection) => void;
  /** Stops only browser reads; never sends a pause command to collectors or the Sentinel engine. */
  readonly pause: () => void;
  /** Requeries the current window immediately. Does not replay old frame buffers. */
  readonly resume: () => void;
  /** React cleanup/selection replacement; reusable under StrictMode. */
  readonly cancel: () => void;
  readonly dispose: () => void;
}

/**
 * One polling effect owner per visible monitor. Installed PollingStore exhaustMap
 * prevents overlapping ticks; bounded QueryResource aborts timed-out attempts.
 * No hidden retries/stream copies or ever-growing append buffer: replace at most
 * one validated, capacity-bounded window bundle. A rolling scope's last good
 * response retains its own exact window/asOf, not a fake new timestamp.
 */
export function createRealtimeMonitor(
  port: RealtimePort,
  access?: QueryAccessObserver,
  options: {
    readonly intervalMs?: number;
    readonly timeoutMs?: number;
    readonly clock?: () => number;
  } = {},
): RealtimeMonitor {
  // Without a client-side session projection, the server remains authoritative
  // for metrics:view. HTTP 401/403 still clears data through QueryResource.
  const accessObserver: QueryAccessObserver = access ?? {
    read: () => ({ ownerKey: "console-http-session", allowed: true }),
    subscribe: () => () => {},
  };
  const intervalMs = options.intervalMs ?? DEFAULT_POLL_INTERVAL_MS,
    clock = options.clock ?? Date.now;
  if (
    !Number.isSafeInteger(intervalMs) ||
    intervalMs < MIN_POLL_INTERVAL_MS ||
    intervalMs > MAX_POLL_INTERVAL_MS
  )
    throw new RangeError("Invalid polling interval");
  let mode: MonitorMode = MONITOR_MODE.Idle,
    selection: RealtimeSelection | null = null,
    disposed = false;
  let ownerKey = accessObserver.read().ownerKey;
  let retryNotBeforeMs = 0;
  const query = createOwnedQueryResource<RealtimeSelection, MetricBundle>(accessObserver, {
    keyOf: realtimeSelectionKey,
    timeoutMs: options.timeoutMs,
    async read(selected, signal) {
      const actual = resolveRealtimeQuery(selected, clock());
      const value = await port.readMetrics(actual, signal);
      if (!validMetricBundle(value, actual))
        throw new AppError(AppErrorKind.PROTOCOL, "Inconsistent metric observation", {
          status: 502,
          code: "invalid_observation",
        });
      return value;
    },
    classify: (value) =>
      value.summary.some((item) => item.quality !== OBSERVATION_QUALITY.Available)
        ? "partial"
        : "ready",
  });
  // Scheduling owns no second sample cache. QueryResource is the sole data owner.
  const polling = new PollingStore<void>();
  const state = new StateStore<RealtimeMonitorSnapshot>({
    mode,
    selection,
    observation: query.getSnapshot(),
    intervalMs,
  });
  const publish = () =>
    state.set({ mode, selection, observation: query.getSnapshot(), intervalMs });
  const unsubscribeQuery = query.subscribe(publish);
  function stop(nextMode: MonitorMode) {
    // Set presentation mode before cancellation emits its restored trusted value.
    mode = nextMode;
    polling.reset();
    query.cancel();
    publish();
  }
  const unsubscribeAccess = accessObserver.subscribe(() => {
    const next = accessObserver.read();
    if (next.ownerKey !== ownerKey || !next.allowed) {
      selection = null;
      stop(MONITOR_MODE.Idle);
      query.reset();
      retryNotBeforeMs = 0;
      ownerKey = next.ownerKey;
      publish();
    }
  });
  const poll = async (selected: RealtimeSelection, signal: AbortSignal): Promise<void> => {
    if (signal.aborted || disposed) throw new AppError(AppErrorKind.CANCELLED, "Monitor cancelled");
    if (globalThis.performance.now() < retryNotBeforeMs) return;
    try {
      await query.load(selected);
    } catch (cause: unknown) {
      const error = AppError.fromUnknown(cause);
      if (
        !signal.aborted &&
        !disposed &&
        selection !== null &&
        realtimeSelectionKey(selection) === realtimeSelectionKey(selected) &&
        error.kind === AppErrorKind.RATE_LIMITED &&
        error.retryAfterMs !== undefined &&
        Number.isSafeInteger(error.retryAfterMs) &&
        error.retryAfterMs >= 0
      )
        retryNotBeforeMs = Math.max(
          retryNotBeforeMs,
          globalThis.performance.now() + error.retryAfterMs,
        );
      throw cause;
    }
  };
  function start(selected: RealtimeSelection) {
    if (disposed) throw new AppError(AppErrorKind.CANCELLED, "Monitor owner disposed");
    if (!accessObserver.read().allowed)
      throw new AppError(AppErrorKind.FORBIDDEN, "Observation access unavailable", { status: 403 });
    if (!validRealtimeSelection(selected))
      throw new AppError(AppErrorKind.PROTOCOL, "Invalid realtime query", {
        status: 400,
        code: "invalid_observation_query",
      });
    if (
      mode === MONITOR_MODE.Polling &&
      selection !== null &&
      realtimeSelectionKey(selection) === realtimeSelectionKey(selected)
    )
      return;
    stop(MONITOR_MODE.Stopped);
    if (selection === null || realtimeSelectionKey(selection) !== realtimeSelectionKey(selected)) {
      query.reset();
      retryNotBeforeMs = 0;
    }
    selection = selected;
    mode = MONITOR_MODE.Polling;
    publish();
    polling.start((signal) => poll(selected, signal), {
      intervalMs,
      immediate: true,
      retryCount: 0,
    });
  }
  return Object.freeze({
    getSnapshot: state.getSnapshot,
    subscribe: state.subscribe,
    start,
    pause() {
      if (mode === MONITOR_MODE.Polling) stop(MONITOR_MODE.Paused);
    },
    resume() {
      if (selection === null)
        throw new AppError(AppErrorKind.PROTOCOL, "No monitor selection", { status: 400 });
      start(selection);
    },
    cancel() {
      if (!disposed) stop(MONITOR_MODE.Stopped);
    },
    dispose() {
      if (disposed) return;
      stop(MONITOR_MODE.Idle);
      selection = null;
      disposed = true;
      unsubscribeAccess();
      unsubscribeQuery();
      polling.complete();
      query.dispose();
      state.set({
        mode: MONITOR_MODE.Idle,
        selection: null,
        observation: { status: "idle" },
        intervalMs,
      });
      state.complete();
    },
  });
}
