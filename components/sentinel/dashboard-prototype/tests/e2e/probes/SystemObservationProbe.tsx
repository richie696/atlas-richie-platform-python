import { useState } from "react";
import { StateStore, AppError, AppErrorKind } from "@richie696/react-framework";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import { AstryxProvider } from "../../../src/app/providers/AstryxProvider";
import {
  createSystemObservationResources,
  ObservedConnectionsPanel,
  ObservedProtocolsPanel,
  ObservedAuditPanel,
  ObservedPermissionsPanel,
} from "../../../src/features/system/observation";
import type { ControlPlaneAccessState } from "../../../src/features/identity/authentication";
import type {
  AuditQuery,
  AuditRecord,
  SystemProtocols,
} from "../../../src/features/system/model/systemObservation";
import {
  systemConnections,
  systemProtocols,
  auditQuery,
  auditPage,
} from "../../fixtures/systemObservations";
/** Diagnostic effect controls are test-only. Formal consumers have no fixture/provider branches. */
export function createSystemObservationTopology() {
  const session = new StateStore<ControlPlaneAccessState>({
    phase: "resolved",
    facts: {
      kind: "authenticated",
      identity: {
        accountId: "account-system-test",
        username: "system-admin",
        roleId: "admin",
        capabilities: ["metrics:view", "rules:write"],
        sessionEpoch: "system-test-session",
      },
    },
  });
  const system = new StateStore({ ownerKey: "system-test-session", allowed: true }),
    audit = new StateStore({ ownerKey: "system-test-session", allowed: true });
  const counts = new StateStore({ connections: 0, protocols: 0, audit: 0, aborts: 0 });
  let offline = false,
    held = false,
    release: (() => void) | null = null;
  const count = (kind: "connections" | "protocols" | "audit" | "aborts") =>
    counts.set({ ...counts.getSnapshot(), [kind]: counts.getSnapshot()[kind] + 1 });
  const resources = createSystemObservationResources(
    {
      health: {
        async readConnections() {
          count("connections");
          if (offline) throw new AppError(AppErrorKind.NETWORK, "PRIVATE-CONNECTION-MESSAGE");
          return systemConnections;
        },
      },
      protocols: {
        async readProtocols(signal) {
          count("protocols");
          if (!held) return systemProtocols;
          return new Promise<SystemProtocols>((resolve) => {
            release = () => resolve(systemProtocols);
            signal.addEventListener("abort", () => count("aborts"), { once: true });
          });
        },
      },
      audit: {
        async readAudit(query) {
          count("audit");
          return auditPage(query);
        },
      },
    },
    {
      system: { read: system.getSnapshot, subscribe: system.subscribe },
      audit: { read: audit.getSnapshot, subscribe: audit.subscribe },
    },
  );
  return {
    session,
    system,
    audit,
    counts,
    resources,
    setOffline: (value: boolean) => {
      offline = value;
    },
    holdProtocols: () => {
      held = true;
    },
    release: () => release?.(),
    dispose() {
      resources.dispose();
      system.complete();
      audit.complete();
      counts.complete();
      session.complete();
    },
  };
}
export function SystemObservationProbe({
  topology,
}: {
  readonly topology: ReturnType<typeof createSystemObservationTopology>;
}) {
  const [query, setQuery] = useState<AuditQuery>(auditQuery),
    [selected, setSelected] = useState<AuditRecord | null>(null);
  const connections = useExternalSnapshot(topology.resources.connections),
    protocols = useExternalSnapshot(topology.resources.protocols),
    audit = useExternalSnapshot(topology.resources.audit),
    counts = useExternalSnapshot(topology.counts);
  const session = useExternalSnapshot(topology.session);
  return (
    <AstryxProvider>
      <div data-system-controls>
        <button data-session-expire onClick={() => topology.session.set({ phase: "expired" })}>
          Expire session
        </button>
        <button
          data-session-view
          onClick={() =>
            topology.session.set({
              phase: "resolved",
              facts: {
                kind: "authenticated",
                identity: {
                  accountId: "account-view-test",
                  username: "system-view",
                  roleId: "view",
                  capabilities: ["metrics:view"],
                  sessionEpoch: "system-view-session",
                },
              },
            })
          }
        >
          Viewer session
        </button>
        <button data-system-offline onClick={() => topology.setOffline(true)}>
          Disconnect probes
        </button>
        <button data-system-online onClick={() => topology.setOffline(false)}>
          Recover probes
        </button>
        <button data-system-hold onClick={topology.holdProtocols}>
          Hold protocol response
        </button>
        <button data-system-release onClick={topology.release}>
          Release response
        </button>
        <button
          data-system-deny-audit
          onClick={() => topology.audit.set({ ownerKey: "system-test-session", allowed: false })}
        >
          Revoke audit
        </button>
        <button
          data-system-deny
          onClick={() => topology.system.set({ ownerKey: "system-test-session", allowed: false })}
        >
          Revoke system reads
        </button>
      </div>
      <ObservedPermissionsPanel access={session} />
      <ObservedConnectionsPanel resource={topology.resources.connections} />
      <ObservedProtocolsPanel resource={topology.resources.protocols} />
      <ObservedAuditPanel
        resource={topology.resources.audit}
        query={query}
        onQueryChange={setQuery}
        onPublication={setSelected}
      />
      <output data-system-summary style={{ display: "block", overflowWrap: "anywhere" }}>
        {JSON.stringify({
          connections: connections.status,
          protocols: protocols.status,
          audit: audit.status,
          query,
          selected,
          counts,
        })}
      </output>
    </AstryxProvider>
  );
}
