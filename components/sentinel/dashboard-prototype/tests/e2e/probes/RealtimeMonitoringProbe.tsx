import { useState } from "react";
import { AppError, AppErrorKind, StateStore } from "@richie696/react-framework";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import { AstryxProvider } from "../../../src/app/providers/AstryxProvider";
import {
  createRealtimeMonitor,
  LiveMonitoringPage,
  type RealtimeSelection,
} from "../../../src/features/realtime/monitoring";
import {
  metricQueryKey,
  type MetricBundle,
  type MetricQuery,
} from "../../../src/shared/model/observation";
import type { QueryAccess } from "../../../src/shared/state/ownedQueryResource";
import { bundleFor, query, toMs } from "../../fixtures/observations";
const selection: RealtimeSelection = {
  context: query.context,
  metrics: bundleFor().query.metrics,
  stepMs: query.stepMs,
  windowMode: "rolling",
};
function responseFor(input: MetricQuery): MetricBundle {
  const bundle = bundleFor(input.context, input.stepMs);
  return {
    ...bundle,
    query: input,
    summary: bundle.summary.filter((item) => input.metrics.includes(item.metric)),
    series: bundle.series.filter((item) => input.metrics.includes(item.metric)),
  };
}
/** Test effect setup is outside React render; timer/cancel/data behavior comes from the real monitor. */
export function createRealtimeProbeTopology() {
  const access = new StateStore<QueryAccess>({ ownerKey: "monitor-test-owner", allowed: true });
  const counts = new StateStore({
    reads: 0,
    active: 0,
    maxActive: 0,
    aborts: 0,
    lastWindowTo: 0,
    lastKey: "",
  });
  let nowMs = toMs,
    mode: "success" | "offline" | "held" | "wrong" = "success",
    release: (() => void) | undefined;
  const monitor = createRealtimeMonitor(
    {
      async readMetrics(input, signal) {
        const before = counts.getSnapshot();
        counts.set({
          ...before,
          reads: before.reads + 1,
          active: before.active + 1,
          maxActive: Math.max(before.maxActive, before.active + 1),
          lastWindowTo: input.context.window.toMs,
          lastKey: metricQueryKey(input),
        });
        try {
          if (mode === "offline") throw new AppError(AppErrorKind.NETWORK, "PRIVATE-MONITOR-ERROR");
          if (mode === "wrong") return bundleFor();
          if (mode === "held")
            return await new Promise<MetricBundle>((resolve, reject) => {
              const aborted = () => {
                counts.set({ ...counts.getSnapshot(), aborts: counts.getSnapshot().aborts + 1 });
                reject(new AppError(AppErrorKind.CANCELLED, "Synthetic cancelled"));
              };
              signal.addEventListener("abort", aborted, { once: true });
              release = () => {
                signal.removeEventListener("abort", aborted);
                resolve(responseFor(input));
              };
            });
          return responseFor(input);
        } finally {
          counts.set({ ...counts.getSnapshot(), active: counts.getSnapshot().active - 1 });
        }
      },
    },
    { read: access.getSnapshot, subscribe: access.subscribe },
    // Match the product polling cadence so an offline->online test can assert
    // the explicit retry path before an automatic refresh races the UI action.
    { intervalMs: 5_000, clock: () => nowMs },
  );
  return {
    monitor,
    access,
    counts,
    clock: () => nowMs,
    setMode: (value: typeof mode) => {
      mode = value;
    },
    advance: () => {
      nowMs += 60_000;
    },
    release: () => release?.(),
    dispose: () => {
      monitor.dispose();
      access.complete();
      counts.complete();
    },
  };
}
/** Real read-only monitoring page under the real skin and StrictMode; synthetic Port, not HTTP. */
export function RealtimeMonitoringProbe({
  topology,
}: {
  readonly topology: ReturnType<typeof createRealtimeProbeTopology>;
}) {
  const [selected, setSelected] = useState(selection);
  const counts = useExternalSnapshot(topology.counts),
    snapshot = useExternalSnapshot(topology.monitor);
  return (
    <AstryxProvider>
      <div data-test-effects>
        {(["success", "offline", "held", "wrong"] as const).map((mode) => (
          <button
            type="button"
            key={mode}
            data-monitor-mode={mode}
            onClick={() => topology.setMode(mode)}
          >
            {mode}
          </button>
        ))}
        <button type="button" data-monitor-advance onClick={topology.advance}>
          Advance
        </button>
        <button type="button" data-monitor-release onClick={topology.release}>
          Release
        </button>
        <button
          type="button"
          data-monitor-revoke
          onClick={() => topology.access.set({ ownerKey: "monitor-test-owner", allowed: false })}
        >
          Revoke
        </button>
        <button
          type="button"
          data-monitor-invalid
          onClick={() => setSelected({ ...selected, stepMs: 0 })}
        >
          Invalid query
        </button>
      </div>
      <LiveMonitoringPage
        monitor={topology.monitor}
        selection={selected}
        onSelectionChange={setSelected}
        environments={[{ id: "test-env", name: "Test environment" }]}
        applications={[
          { id: "app-one", name: "app-one" },
          { id: "app-two", name: "app-two" },
        ]}
        instances={[]}
        instanceHint={undefined}
        selectedInstanceId={null}
        instanceCatalogLoading={false}
        queryReady={true}
        instanceTargetMissing={false}
        instanceTargetUnsupported={false}
        clock={topology.clock}
      />
      <output
        data-monitor-probe-summary
        style={{ display: "block", whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
      >
        {JSON.stringify({
          ...counts,
          mode: snapshot.mode,
          status: snapshot.observation.status,
          window:
            "data" in snapshot.observation ? snapshot.observation.data.query.context.window : null,
          selected,
        })}
      </output>
    </AstryxProvider>
  );
}
