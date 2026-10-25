import {
  OBSERVATION_SCOPE,
  metricQueryKey,
  validMetricQuery,
  validObservationWindow,
  type MetricQuery,
  type ObservationScope,
} from "../../../shared/model/observation";

export const MONITOR_MODE = Object.freeze({
  Idle: "idle",
  Polling: "polling",
  Paused: "paused",
  Stopped: "stopped",
} as const);
export type MonitorMode = (typeof MONITOR_MODE)[keyof typeof MONITOR_MODE];
export const WINDOW_MODE = Object.freeze({ Fixed: "fixed", Rolling: "rolling" } as const);
/** Original exact anchor plus a deliberate rolling policy; not a simulated frame cursor. */
export interface RealtimeSelection extends MetricQuery {
  readonly windowMode: (typeof WINDOW_MODE)[keyof typeof WINDOW_MODE];
}
/** Directory-owned capability projection accepted by the realtime selector. */
export interface RealtimeInstanceTarget {
  readonly appId: string;
  readonly instanceId: string;
  readonly supportedScopes: readonly ObservationScope[];
}
/** Apply only an explicitly advertised instance scope; clearing returns to app/fleet aggregate. */
export function selectRealtimeInstance(
  selection: RealtimeSelection,
  instance: RealtimeInstanceTarget | null,
): RealtimeSelection | null {
  if (instance === null) {
    return {
      ...selection,
      context: {
        ...selection.context,
        instanceId: null,
        resource: null,
        scope:
          selection.context.appId === null
            ? OBSERVATION_SCOPE.Fleet
            : OBSERVATION_SCOPE.Application,
      },
    };
  }
  const scope = instance.supportedScopes.includes(selection.context.scope)
    ? selection.context.scope
    : instance.supportedScopes[0];
  if (!scope) return null;
  return {
    ...selection,
    context: {
      ...selection.context,
      appId: instance.appId,
      instanceId: instance.instanceId,
      resource: null,
      scope,
    },
  };
}
export const DEFAULT_POLL_INTERVAL_MS = 5000;
export const MIN_POLL_INTERVAL_MS = 100;
export const MAX_POLL_INTERVAL_MS = 60_000;
export function realtimeSelectionKey(selection: RealtimeSelection): string {
  return JSON.stringify([metricQueryKey(selection), selection.windowMode]);
}
export function validRealtimeSelection(selection: RealtimeSelection): boolean {
  return validMetricQuery(selection) && Object.values(WINDOW_MODE).includes(selection.windowMode);
}
/** Each rolling attempt has its own exact UTC request identity; retained data keeps its old window visibly. */
export function resolveRealtimeQuery(selection: RealtimeSelection, nowMs: number): MetricQuery {
  const duration = selection.context.window.toMs - selection.context.window.fromMs;
  const context =
    selection.windowMode === WINDOW_MODE.Fixed
      ? selection.context
      : { ...selection.context, window: { fromMs: nowMs - duration, toMs: nowMs } };
  if (!validObservationWindow(context.window))
    throw new RangeError("Invalid observation clock/window");
  return { context, metrics: selection.metrics, stepMs: selection.stepMs };
}
