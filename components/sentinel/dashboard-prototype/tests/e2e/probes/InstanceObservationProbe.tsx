import { useState } from "react";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import { AppError, AppErrorKind, StateStore } from "@richie696/react-framework";
import { AstryxProvider } from "../../../src/app/providers/AstryxProvider";
import {
  createInstanceResources,
  InstanceObservationPage,
  type InstanceCatalogQuery,
  type InstanceDetailQuery,
  type InstanceObservation,
} from "../../../src/features/applications/observation";
import type { QueryAccess } from "../../../src/shared/state/ownedQueryResource";
import type { RouteId, NavigationContext } from "../../../src/shared/types/navigation";
import { catalogFor, catalogQuery, detailFor } from "../../fixtures/instances";
import { toMs } from "../../fixtures/observations";

/** Stable effect topology created outside React; no production fixtures or ownership forks. */
export function createInstanceProbeTopology() {
  const access = new StateStore<QueryAccess>({ ownerKey: "instance-test-session", allowed: true });
  const counts = new StateStore({ catalogReads: 0, detailReads: 0, aborts: 0 });
  let mode: "success" | "offline" | "held" | "wrong" | "missing" | "replaced" = "success",
    release: (() => void) | undefined;
  const resources = createInstanceResources(
    {
      async readCatalog(query) {
        counts.set({
          ...counts.getSnapshot(),
          catalogReads: counts.getSnapshot().catalogReads + 1,
        });
        return catalogFor(query);
      },
      async readInstance(query, signal) {
        counts.set({ ...counts.getSnapshot(), detailReads: counts.getSnapshot().detailReads + 1 });
        if (mode === "offline") throw new AppError(AppErrorKind.NETWORK, "PRIVATE-INSTANCE-ERROR");
        if (mode === "missing")
          throw new AppError(AppErrorKind.PROTOCOL, "PRIVATE-MISSING-INSTANCE", { status: 404 });
        if (mode === "replaced")
          throw new AppError(AppErrorKind.SERVER, "PRIVATE-REPLACED-INSTANCE", {
            status: 409,
            code: "instance_incarnation_changed",
          });
        if (mode === "wrong") {
          const result = detailFor(query);
          return { ...result, instance: { ...result.instance, processEpoch: "old-incarnation" } };
        }
        if (mode === "held")
          return new Promise<InstanceObservation>((resolve, reject) => {
            const abort = () => {
              counts.set({ ...counts.getSnapshot(), aborts: counts.getSnapshot().aborts + 1 });
              reject(new AppError(AppErrorKind.CANCELLED, "Test cancelled"));
            };
            signal.addEventListener("abort", abort, { once: true });
            release = () => {
              signal.removeEventListener("abort", abort);
              resolve(detailFor(query));
            };
          });
        return detailFor(query);
      },
    },
    { read: access.getSnapshot, subscribe: access.subscribe },
  );
  return {
    access,
    counts,
    resources,
    setMode(value: typeof mode) {
      mode = value;
    },
    release: () => release?.(),
    dispose() {
      resources.dispose();
      access.complete();
      counts.complete();
    },
  };
}
/** Real feature pages in StrictMode; synthetic Port is explicitly not HTTP/backend acceptance. */
export function InstanceObservationProbe({
  topology,
}: {
  readonly topology: ReturnType<typeof createInstanceProbeTopology>;
}) {
  const [query, setQuery] = useState<InstanceCatalogQuery>(catalogQuery);
  const [selection, setSelection] = useState<InstanceDetailQuery | null>(null);
  const [navigation, setNavigation] = useState<{
    route: RouteId;
    context?: NavigationContext;
  } | null>(null);
  const catalog = useExternalSnapshot(topology.resources.catalog),
    detail = useExternalSnapshot(topology.resources.detail),
    counts = useExternalSnapshot(topology.counts);
  return (
    <AstryxProvider>
      <div data-test-effects>
        {(["success", "offline", "held", "wrong", "missing", "replaced"] as const).map((mode) => (
          <button key={mode} data-instance-mode={mode} onClick={() => topology.setMode(mode)}>
            {mode}
          </button>
        ))}
        <button data-instance-release onClick={topology.release}>
          Release
        </button>
        <button
          data-instance-revoke
          onClick={() => topology.access.set({ ownerKey: "instance-test-session", allowed: false })}
        >
          Revoke
        </button>
        <button
          data-instance-missing-app
          onClick={() =>
            setQuery({
              ...query,
              context: { ...query.context, appId: "missing", scope: "application" },
            })
          }
        >
          Missing application
        </button>
        <button
          data-instance-env
          onClick={() =>
            setQuery({ ...query, context: { ...query.context, environmentId: "other-env" } })
          }
        >
          Other environment
        </button>
      </div>
      <InstanceObservationPage
        resources={topology.resources}
        query={query}
        selection={selection}
        onQueryChange={setQuery}
        onSelectionChange={setSelection}
        environments={[
          { id: "test-env", name: "Test environment" },
          { id: "other-env", name: "Other environment" },
        ]}
        applications={[
          { id: "app-one", name: "app-one" },
          { id: "app-two", name: "app-two" },
        ]}
        clock={() => toMs}
        navigate={(route, context) => setNavigation({ route, context })}
      />
      <output
        data-instance-summary
        style={{ display: "block", whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
      >
        {JSON.stringify({
          ...counts,
          query,
          selection,
          navigation,
          catalogState: catalog.status,
          detailState: detail.status,
          detailKey: "key" in detail ? detail.key : null,
        })}
      </output>
    </AstryxProvider>
  );
}
