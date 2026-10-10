import { useState } from "react";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import { AppError, AppErrorKind, StateStore } from "@richie696/react-framework";
import { AstryxProvider } from "../../../src/app/providers/AstryxProvider";
import {
  createFleetResource,
  FleetOverviewPage,
  type FleetQuery,
  type FleetSnapshot,
} from "../../../src/features/overview/observation";
import type { QueryAccess } from "../../../src/shared/state/ownedQueryResource";
import { query as initialQuery, snapshotFor, toMs } from "../../fixtures/observations";
import type { NavigationContext, RouteId } from "../../../src/shared/types/navigation";

/** Create test effects outside React render; StrictMode exercises the real page's cancellation lifetime. */
export function createFleetProbeTopology() {
  const access = new StateStore<QueryAccess>({ ownerKey: "fleet-test-session", allowed: true });
  const counts = new StateStore({ reads: 0, aborts: 0 });
  let mode: "success" | "offline" | "wrong" | "held" = "success",
    release: (() => void) | undefined;
  let inventoryUnknown = false;
  function snapshot(query: FleetQuery): FleetSnapshot {
    const value = snapshotFor(query);
    if (!inventoryUnknown) return value;
    const coverage = { expected: null, inventorySource: null };
    const summary = value.metrics.summary.map((reading) => ({
      ...reading,
      coverage: { ...reading.coverage, ...coverage },
    }));
    return {
      ...value,
      coverage: { ...value.coverage, ...coverage },
      applications: {
        ...value.applications,
        items: value.applications.items.map((row) => ({
          ...row,
          instanceCoverage: { ...row.instanceCoverage, ...coverage },
          ruleCoverage: { ...row.ruleCoverage, ...coverage },
          metrics: row.metrics.map((reading) => ({
            ...reading,
            coverage: { ...reading.coverage, ...coverage },
          })),
        })),
      },
      metrics: {
        ...value.metrics,
        summary,
        series: value.metrics.series.map((series) => ({
          ...series,
          coverage: { ...series.coverage, ...coverage },
        })),
      },
    };
  }
  const resource = createFleetResource(
    {
      async readFleet(query, signal) {
        counts.set({ ...counts.getSnapshot(), reads: counts.getSnapshot().reads + 1 });
        if (mode === "offline") throw new AppError(AppErrorKind.NETWORK, "PRIVATE-FLEET-ERROR");
        if (mode === "wrong") return snapshotFor(initialQuery);
        if (mode === "held")
          return new Promise<FleetSnapshot>((resolve, reject) => {
            const aborted = () => {
              counts.set({ ...counts.getSnapshot(), aborts: counts.getSnapshot().aborts + 1 });
              reject(new AppError(AppErrorKind.CANCELLED, "Synthetic cancelled"));
            };
            signal.addEventListener("abort", aborted, { once: true });
            release = () => {
              signal.removeEventListener("abort", aborted);
              resolve(snapshot(query));
            };
          });
        return snapshot(query);
      },
    },
    { read: access.getSnapshot, subscribe: access.subscribe },
  );
  return {
    resource,
    access,
    counts,
    setMode: (value: typeof mode) => {
      mode = value;
    },
    release: () => release?.(),
    setInventoryUnknown: () => {
      inventoryUnknown = true;
    },
    dispose: () => {
      resource.dispose();
      access.complete();
      counts.complete();
    },
  };
}

/** Actual formal container/charts/controls under the real Astryx skin; this is not HTTP acceptance. */
export function FleetObservationProbe({
  topology,
}: {
  readonly topology: ReturnType<typeof createFleetProbeTopology>;
}) {
  const [query, setQuery] = useState<FleetQuery>(initialQuery);
  const [navigation, setNavigation] = useState<{
    route: RouteId;
    context?: NavigationContext;
  } | null>(null);
  const counts = useExternalSnapshot(topology.counts),
    snapshot = useExternalSnapshot(topology.resource);
  return (
    <AstryxProvider>
      <div data-test-effects>
        {(["success", "offline", "wrong", "held"] as const).map((mode) => (
          <button
            type="button"
            key={mode}
            data-fleet-mode={mode}
            onClick={() => topology.setMode(mode)}
          >
            {mode}
          </button>
        ))}
        <button type="button" data-fleet-release onClick={topology.release}>
          Release
        </button>
        <button type="button" data-fleet-inventory-unknown onClick={topology.setInventoryUnknown}>
          Unknown inventory
        </button>
        <button
          type="button"
          data-fleet-revoke
          onClick={() => topology.access.set({ ownerKey: "fleet-test-session", allowed: false })}
        >
          Revoke
        </button>
        <button
          type="button"
          data-fleet-missing
          onClick={() =>
            setQuery({
              ...query,
              context: { ...query.context, appId: "missing", scope: "application" },
            })
          }
        >
          Missing
        </button>
        <button
          type="button"
          data-fleet-env
          onClick={() =>
            setQuery({ ...query, context: { ...query.context, environmentId: "other-env" } })
          }
        >
          Change environment
        </button>
      </div>
      <FleetOverviewPage
        resource={topology.resource}
        query={query}
        onQueryChange={setQuery}
        environments={[
          { id: "test-env", name: "Test environment" },
          { id: "other-env", name: "Other environment" },
        ]}
        applications={[
          { id: "app-one", name: "app-one" },
          { id: "app-two", name: "app-two" },
          { id: "app-three", name: "app-three" },
        ]}
        clock={() => toMs}
        navigate={(route, context) => setNavigation({ route, context })}
      />
      <output
        data-fleet-probe-summary
        style={{ display: "block", overflowWrap: "anywhere", whiteSpace: "pre-wrap" }}
      >
        {JSON.stringify({
          ...counts,
          status: snapshot.status,
          key: "key" in snapshot ? snapshot.key : null,
          query,
          navigation,
        })}
      </output>
    </AstryxProvider>
  );
}
