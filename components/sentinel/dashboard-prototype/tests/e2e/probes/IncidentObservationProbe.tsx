import { useState } from "react";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import { AppError, AppErrorKind, StateStore } from "@richie696/react-framework";
import { AstryxProvider } from "../../../src/app/providers/AstryxProvider";
import {
  createIncidentResources,
  IncidentObservationPage,
  type IncidentQuery,
  type IncidentEvidence,
} from "../../../src/features/faults/observation";
import type { QueryAccess } from "../../../src/shared/state/ownedQueryResource";
import type { RouteId, NavigationContext } from "../../../src/shared/types/navigation";
import { incidentQuery, incidentPageFor, evidenceFor } from "../../fixtures/incidents";
import { toMs } from "../../fixtures/observations";
const MODES = ["success", "offline", "partial", "unavailable", "missing", "wrong", "held"] as const;

/** Test topology is outside render. Synthetic Port is not an HTTP gateway or a backend claim. */
export function createIncidentProbeTopology() {
  const access = new StateStore<QueryAccess>({ ownerKey: "incident-test-session", allowed: true });
  const counts = new StateStore({ listReads: 0, evidenceReads: 0, aborts: 0 });
  let mode: (typeof MODES)[number] = "success",
    release: (() => void) | undefined;
  const resources = createIncidentResources(
    {
      async readTimeline(query) {
        counts.set({ ...counts.getSnapshot(), listReads: counts.getSnapshot().listReads + 1 });
        return incidentPageFor(query);
      },
      async readEvidence(query, signal) {
        counts.set({
          ...counts.getSnapshot(),
          evidenceReads: counts.getSnapshot().evidenceReads + 1,
        });
        if (mode === "offline") throw new AppError(AppErrorKind.NETWORK, "PRIVATE-INCIDENT-ERROR");
        if (mode === "missing")
          throw new AppError(AppErrorKind.PROTOCOL, "PRIVATE-MISSING-INCIDENT", { status: 404 });
        const value = evidenceFor(query);
        if (mode === "wrong") return { ...value, event: { ...value.event, id: "wrong-event" } };
        if (mode === "partial" || mode === "unavailable")
          return { ...value, completeness: mode, facts: [] };
        if (mode === "held")
          return new Promise<IncidentEvidence>((resolve, reject) => {
            const abort = () => {
              counts.set({ ...counts.getSnapshot(), aborts: counts.getSnapshot().aborts + 1 });
              reject(new AppError(AppErrorKind.CANCELLED, "Test cancelled"));
            };
            signal.addEventListener("abort", abort, { once: true });
            release = () => {
              signal.removeEventListener("abort", abort);
              resolve(value);
            };
          });
        return value;
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

/** Real page/controls in StrictMode, with diagnostic controls isolated from production source. */
export function IncidentObservationProbe({
  topology,
}: {
  readonly topology: ReturnType<typeof createIncidentProbeTopology>;
}) {
  const [query, setQuery] = useState<IncidentQuery>(incidentQuery),
    [selection, setSelection] = useState<string | null>(null);
  const [navigation, setNavigation] = useState<{
    route: RouteId;
    context?: NavigationContext;
  } | null>(null);
  const timeline = useExternalSnapshot(topology.resources.timeline),
    evidence = useExternalSnapshot(topology.resources.evidence),
    counts = useExternalSnapshot(topology.counts);
  return (
    <AstryxProvider>
      <div data-test-effects>
        {MODES.map((value) => (
          <button key={value} data-incident-mode={value} onClick={() => topology.setMode(value)}>
            {value}
          </button>
        ))}
        <button data-incident-release onClick={topology.release}>
          Release
        </button>
        <button
          data-incident-revoke
          onClick={() => topology.access.set({ ownerKey: "incident-test-session", allowed: false })}
        >
          Revoke
        </button>
      </div>
      <IncidentObservationPage
        resources={topology.resources}
        instanceSnapshot={{ status: "idle" }}
        instances={[]}
        selectedInstance={null}
        instanceTotal={0}
        query={query}
        selectedEventId={selection}
        onQueryChange={(next) => {
          const filtersChanged =
            JSON.stringify([next.context, next.severity, next.category, next.pageSize]) !==
            JSON.stringify([query.context, query.severity, query.category, query.pageSize]);
          if (filtersChanged) setSelection(null);
          setQuery(next);
        }}
        onSelect={setSelection}
        onInstanceChange={() => {}}
        navigate={(route, context) => setNavigation({ route, context })}
        environments={[{ id: "test-env", name: "Test environment" }]}
        applications={[
          { id: "app-one", name: "app-one" },
          { id: "app-two", name: "app-two" },
        ]}
        clock={() => toMs}
      />
      <output
        data-incident-summary
        style={{ display: "block", whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
      >
        {JSON.stringify({
          ...counts,
          query,
          selection,
          navigation,
          timelineState: timeline.status,
          evidenceState: evidence.status,
        })}
      </output>
    </AstryxProvider>
  );
}
