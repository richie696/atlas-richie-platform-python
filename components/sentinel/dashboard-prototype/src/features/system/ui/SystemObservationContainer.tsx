import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { QueryAccessObserver } from "../../../shared/state/ownedQueryResource";
import { useOwnedDisposal } from "../../../shared/state/useOwnedDisposal";
import type { DashboardPageProps } from "../../../shared/types/dashboard";
import { createSourceRegistrationWorkflow } from "../application/sourceRegistrationWorkflow";
import { createSystemObservationResources } from "../application/systemObservationResources";
import type { SystemObservationPorts } from "../api/systemObservationPort";
import type { SourceRegistrationPort } from "../api/sourceRegistrationPort";
import type { MonitoringSourcePort } from "../api/monitoringSourcePort";
import { createMonitoringSourceWorkflow } from "../application/monitoringSourceWorkflow";
import type { AuditQuery } from "../model/systemObservation";
import type { ControlPlaneAccessState } from "../../identity";
import { SystemPage } from "./SystemPage";
import type { SystemSettingsPort } from "../api/systemSettingsPort";

type PageContext = DashboardPageProps & {
  readonly observationPorts: SystemObservationPorts;
  readonly sourceRegistrationPort: SourceRegistrationPort;
  readonly systemSettingsPort: SystemSettingsPort;
  readonly monitoringSourcePort: MonitoringSourcePort;
  readonly accountId?: string;
  readonly principal: { readonly roleId: "admin" | "view"; readonly sessionEpoch: string };
  readonly access: ControlPlaneAccessState;
  readonly demoMode: boolean;
  readonly identityPanels: { readonly accounts: ReactNode; readonly roles: ReactNode };
};

function accessObserver(ownerKey: string, allowed: boolean): QueryAccessObserver {
  const value = Object.freeze({ ownerKey, allowed });
  return Object.freeze({ read: () => value, subscribe: () => () => {} });
}

/** Owns system read resources, session projection and the independent audit time window. */
export function SystemObservationContainer({
  observationPorts,
  sourceRegistrationPort,
  systemSettingsPort,
  monitoringSourcePort,
  principal,
  access: sessionAccess,
  demoMode,
  ...page
}: PageContext) {
  const identityRole = principal.roleId;
  const identitySessionEpoch = principal.sessionEpoch;
  const access = useMemo(
    () => ({
      system: accessObserver(`session-${identitySessionEpoch ?? "unavailable"}`, true),
      audit: accessObserver(
        `session-${identitySessionEpoch ?? "unavailable"}`,
        identityRole === "admin",
      ),
      sources: accessObserver(
        `session-${identitySessionEpoch ?? "unavailable"}`,
        identityRole === "admin",
      ),
    }),
    [identityRole, identitySessionEpoch],
  );
  const resources = useMemo(
    () => createSystemObservationResources(observationPorts, access),
    [access, observationPorts],
  );
  const sourceWorkflow = useMemo(
    () =>
      createSourceRegistrationWorkflow(sourceRegistrationPort, access.sources, () =>
        crypto.randomUUID(),
      ),
    [access.sources, sourceRegistrationPort],
  );
  useOwnedDisposal(sourceWorkflow);
  const monitoringSourceWorkflow = useMemo(
    () =>
      createMonitoringSourceWorkflow(monitoringSourcePort, access.system, () =>
        crypto.randomUUID(),
      ),
    [access.system, monitoringSourcePort],
  );
  useOwnedDisposal(monitoringSourceWorkflow);
  const [auditQuery, setAuditQuery] = useState<AuditQuery>(() => {
    const endMs = Date.now();
    return {
      startMs: endMs - 24 * 60 * 60 * 1000,
      endMs,
      actorId: "",
      action: null,
      result: null,
      page: 1,
      pageSize: 20,
    };
  });

  useEffect(
    () => () => {
      resources.connections.cancel();
      resources.deploymentGuides.cancel();
      resources.protocols.cancel();
      resources.agentReporting.cancel();
      resources.incidentEvents.cancel();
      resources.audit.cancel();
    },
    [resources],
  );

  return (
    <SystemPage
      navigate={page.navigate}
      locale={page.locale}
      view={page.view}
      accountId={page.accountId}
      identityPanels={page.identityPanels}
      access={sessionAccess}
      demoMode={demoMode}
      observations={resources}
      sourceRegistration={sourceWorkflow}
      monitoringSources={monitoringSourceWorkflow}
      canManageMonitoringSources={identityRole === "admin"}
      auditQuery={auditQuery}
      onAuditQueryChange={setAuditQuery}
      systemSettings={systemSettingsPort}
    />
  );
}
