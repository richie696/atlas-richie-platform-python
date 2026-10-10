import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { SESSION_CAPABILITY, useCan, useSession } from "../../../core/session";
import { createObservationCatalogResource } from "../../applications";
import type { ObservationCatalogPort } from "../../applications";
import { useQueryResource } from "../../../shared/state/useQueryResource";
import type { QueryAccessObserver } from "../../../shared/state/ownedQueryResource";
import type { DashboardPageProps } from "../../../shared/types/dashboard";
import { ALL_APPLICATIONS, ROUTE } from "../../../shared/types/navigation";
import { ObservationQueryView } from "../../../shared/ui/observation/ObservationQueryView";
import { Select } from "../../../shared/ui/Select";
import type { RuleSetPort } from "../api/ruleSetPort";
import type { RuleSourceCatalogPort } from "../model/ruleBindingRegistration";
import {
  createRuleBindingRegistrationCommand,
  createRuleSourceCatalogResource,
} from "../application/ruleBindingRegistration";
import {
  createRuleBindingDirectory,
  createRuleBindingSnapshot,
} from "../application/ruleDirectoryResources";
import { createRuleOperation } from "../application/ruleOperation";
import { createRuleDraftWorkflow } from "../application/ruleDraftWorkflow";
import { createRuleDeploymentWorkflow } from "../application/ruleDeploymentWorkflow";
import type { BindingQuery } from "../model/ruleDirectory";
import { resolveRuleKindFilter, RULE_KIND, RULE_KIND_ALL } from "../model/ruleKinds";
import { RuleBindingDirectory } from "./RuleBindingDirectory";
import { RuleQueryView } from "./RuleQueryView";
import { RuleSetWorkbenchPage } from "./RuleSetWorkbenchPage";
import { RuleDeploymentPanel } from "./RuleDeploymentPanel";
import { RuleBindingRegistrationDialog } from "./RuleBindingRegistrationDialog";

type PageContext = DashboardPageProps & {
  readonly catalogPort: ObservationCatalogPort;
  readonly ruleSetPort: RuleSetPort;
  readonly sourceCatalogPort: RuleSourceCatalogPort;
  readonly environmentId?: string;
  readonly bindingId?: string;
  readonly publicationId?: string;
  readonly versionId?: string;
  readonly from?: string;
  readonly to?: string;
};

const PAGE_SIZE = 20;

function accessObserver(ownerKey: string, allowed: boolean): QueryAccessObserver {
  const value = Object.freeze({ ownerKey, allowed });
  return Object.freeze({ read: () => value, subscribe: () => () => {} });
}

/** Rule route composition. URL owns the exact binding; the backend owns all rule facts and commands. */
export function RuleConsoleContainer({
  catalogPort,
  ruleSetPort,
  sourceCatalogPort,
  ...page
}: PageContext) {
  const { t } = useTranslation();
  const catalogResource = useMemo(
    () => createObservationCatalogResource(catalogPort),
    [catalogPort],
  );
  const catalogSnapshot = useQueryResource(catalogResource, undefined);
  const catalog = "data" in catalogSnapshot ? catalogSnapshot.data : null;
  const matchingApps = catalog?.applications.filter((item) => item.id === page.appId) ?? [];
  const inferredEnvironment = matchingApps.length === 1 ? matchingApps[0].environmentId : null;
  const environmentId = page.environmentId ?? inferredEnvironment;
  const validEnvironment = catalog?.environments.some((item) => item.id === environmentId) ?? false;

  useEffect(() => () => catalogResource.cancel(), [catalogResource]);

  if (!catalog || !validEnvironment) {
    return (
      <ObservationQueryView
        snapshot={catalogSnapshot}
        onRetry={() => void catalogResource.load(undefined).catch(() => undefined)}
      >
        {() => (
          <section className="fleet-environment-prompt">
            <Select
              label={t("observation.environment")}
              value={
                catalog?.environments.some((item) => item.id === page.environmentId)
                  ? (page.environmentId ?? "")
                  : ""
              }
              options={
                catalog?.environments.map(({ id, name }) => ({ value: id, label: name })) ?? []
              }
              onChange={(id) =>
                page.navigate(ROUTE.Rules, {
                  environmentId: id,
                  appId: ALL_APPLICATIONS,
                  range: page.range,
                  from: page.from,
                  to: page.to,
                  bindingId: "",
                  publicationId: "",
                })
              }
            />
          </section>
        )}
      </ObservationQueryView>
    );
  }

  const applications = catalog.applications
    .filter((application) => application.environmentId === environmentId)
    .map(({ id, name }) => ({ id, name }));
  const appId = page.appId === ALL_APPLICATIONS ? null : page.appId;
  return (
    <RuleBindingOwner
      key={`${environmentId}:${page.appId}:${page.view}:${page.bindingId ?? "unselected"}`}
      page={page}
      ruleSetPort={ruleSetPort}
      sourceCatalogPort={sourceCatalogPort}
      environmentId={environmentId!}
      environments={catalog.environments}
      applications={applications}
      appId={appId}
    />
  );
}

function RuleBindingOwner({
  page,
  ruleSetPort,
  sourceCatalogPort,
  environmentId,
  environments,
  applications,
  appId,
}: {
  readonly page: Omit<PageContext, "catalogPort" | "ruleSetPort" | "sourceCatalogPort">;
  readonly ruleSetPort: RuleSetPort;
  readonly sourceCatalogPort: RuleSourceCatalogPort;
  readonly environmentId: string;
  readonly environments: readonly { readonly id: string; readonly name: string }[];
  readonly applications: readonly { readonly id: string; readonly name: string }[];
  readonly appId: string | null;
}) {
  const session = useSession();
  const canRead = useCan(SESSION_CAPABILITY.MetricsView);
  const canWrite = useCan(SESSION_CAPABILITY.RulesWrite);
  const ownerKey = `demo-session-${session.roleId}`;
  const readAccess = useMemo(() => accessObserver(ownerKey, canRead), [ownerKey, canRead]);
  const writeAccess = useMemo(() => accessObserver(ownerKey, canWrite), [ownerKey, canWrite]);
  const port = ruleSetPort;
  const directory = useMemo(() => createRuleBindingDirectory(port, readAccess), [port, readAccess]);
  const sourceCatalog = useMemo(
    () => createRuleSourceCatalogResource(sourceCatalogPort, writeAccess),
    [sourceCatalogPort, writeAccess],
  );
  const bindingRegistration = useMemo(
    () => createRuleBindingRegistrationCommand(port, writeAccess),
    [port, writeAccess],
  );
  const bindingSnapshot = useMemo(
    () => createRuleBindingSnapshot(port, readAccess),
    [port, readAccess],
  );
  const [query, setQuery] = useState<BindingQuery>(() => ({
    environmentId,
    appId,
    kind: (() => {
      const filter = resolveRuleKindFilter(page.view);
      return filter === RULE_KIND_ALL ? null : filter;
    })(),
    search: "",
    page: 1,
    pageSize: PAGE_SIZE,
  }));
  const [registrationOpen, setRegistrationOpen] = useState(false);
  useEffect(() => () => directory.cancel(), [directory]);
  useEffect(() => () => sourceCatalog.dispose(), [sourceCatalog]);
  useEffect(() => () => bindingRegistration.dispose(), [bindingRegistration]);
  useEffect(() => () => bindingSnapshot.cancel(), [bindingSnapshot]);

  const selectedId = page.bindingId ?? null;
  const selectedQuery = useMemo(
    () => ({ ...query, environmentId, appId }),
    [query, environmentId, appId],
  );
  const [bindingRead, setBindingRead] = useState<{
    readonly id: string;
    readonly binding: import("../model/ruleSet").RuleBinding;
  } | null>(null);
  const bindingSnapshotQuery = bindingRead?.id === selectedId ? null : selectedId;
  const bindingSnapshotState = useQueryResource(bindingSnapshot, bindingSnapshotQuery);
  const selectedBinding =
    bindingRead?.id === selectedId
      ? bindingRead.binding
      : "data" in bindingSnapshotState
        ? (bindingSnapshotState.data?.binding ?? null)
        : null;

  return (
    <>
      <RuleBindingDirectory
        resource={directory}
        query={selectedQuery}
        environments={environments.map(({ id, name }) => ({ value: id, label: name }))}
        applications={applications.map(({ id, name }) => ({ value: id, label: name }))}
        selectedId={selectedId}
        locked={!canRead}
        canRegister={canWrite}
        onRegister={() => setRegistrationOpen(true)}
        onQueryChange={(next) => {
          setQuery(next);
          if (
            next.environmentId !== environmentId ||
            next.appId !== appId ||
            next.kind !== query.kind
          )
            page.navigate(
              ROUTE.Rules,
              {
                environmentId: next.environmentId,
                appId: next.appId ?? ALL_APPLICATIONS,
                range: page.range,
                from: page.from,
                to: page.to,
                view: next.kind ?? RULE_KIND_ALL,
                bindingId: "",
                publicationId: "",
              },
              { history: "replace" },
            );
        }}
        onSelect={(binding) => {
          setBindingRead({ id: binding.id, binding });
          page.navigate(ROUTE.Rules, {
            environmentId: binding.environmentId,
            appId: binding.appId,
            range: page.range,
            from: page.from,
            to: page.to,
            view: page.view,
            bindingId: binding.id,
            publicationId: "",
          });
        }}
      />
      {registrationOpen && (
        <RuleBindingRegistrationDialog
          environmentId={environmentId}
          environments={environments}
          applications={applications}
          defaultKind={query.kind ?? RULE_KIND.Flow}
          sourceResource={sourceCatalog}
          command={bindingRegistration}
          onClose={() => setRegistrationOpen(false)}
          onCreated={(binding) => {
            setRegistrationOpen(false);
            setBindingRead({ id: binding.id, binding });
            page.navigate(ROUTE.Rules, {
              environmentId: binding.environmentId,
              appId: binding.appId,
              range: page.range,
              from: page.from,
              to: page.to,
              view: binding.kind,
              bindingId: binding.id,
              publicationId: "",
            });
            void directory.load(selectedQuery).catch(() => undefined);
          }}
        />
      )}
      {selectedId && selectedBinding && (
        <RuleWorkspaceOwner
          binding={selectedBinding}
          port={port}
          readAccess={readAccess}
          writeAccess={writeAccess}
          publicationId={page.publicationId}
          versionId={page.versionId}
        />
      )}
      {selectedId && !selectedBinding && (
        <RuleQueryView
          snapshot={bindingSnapshotState}
          onRetry={() => void bindingSnapshot.load(selectedId).catch(() => undefined)}
        >
          {() => null}
        </RuleQueryView>
      )}
    </>
  );
}

function RuleWorkspaceOwner({
  binding,
  port,
  readAccess,
  writeAccess,
  publicationId,
  versionId,
}: {
  readonly binding: import("../model/ruleSet").RuleBinding;
  readonly port: RuleSetPort;
  readonly readAccess: QueryAccessObserver;
  readonly writeAccess: QueryAccessObserver;
  readonly publicationId?: string;
  readonly versionId?: string;
}) {
  const operation = useMemo(
    () => createRuleOperation(binding.id, port, writeAccess, () => crypto.randomUUID()),
    [binding.id, port, writeAccess],
  );
  const draft = useMemo(
    () => createRuleDraftWorkflow(binding, port, readAccess, writeAccess, operation),
    [binding, operation, port, readAccess, writeAccess],
  );
  const source = useMemo(
    () => ({ getSnapshot: () => draft.getSnapshot().source, subscribe: draft.subscribe }),
    [draft],
  );
  const deployment = useMemo(
    () =>
      createRuleDeploymentWorkflow(
        binding,
        port,
        readAccess,
        writeAccess,
        operation,
        source,
        Date.now,
      ),
    [binding, operation, port, readAccess, source, writeAccess],
  );
  useEffect(
    () => () => {
      // StrictMode intentionally mounts/cleans effects twice; cancel is safe to repeat,
      // while permanently disposing an external store here would poison its second mount.
      draft.cancel();
      deployment.cancel();
    },
    [deployment, draft, operation],
  );
  return (
    <>
      <RuleSetWorkbenchPage
        workflow={draft}
        binding={binding}
        newFormKey={() => crypto.randomUUID()}
      />
      <RuleDeploymentPanel
        bindingId={binding.id}
        workflow={deployment}
        initialPublicationId={publicationId}
        initialVersionId={versionId}
      />
    </>
  );
}
