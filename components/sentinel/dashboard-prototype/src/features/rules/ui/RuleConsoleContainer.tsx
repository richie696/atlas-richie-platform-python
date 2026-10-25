import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { SESSION_CAPABILITY, useCan, useSession } from "../../../core/session";
import { useQueryResource } from "../../../shared/state/useQueryResource";
import { useOwnedDisposal } from "../../../shared/state/useOwnedDisposal";
import type { QueryAccessObserver } from "../../../shared/state/ownedQueryResource";
import type { DashboardPageProps } from "../../../shared/types/dashboard";
import { ALL_APPLICATIONS, ROUTE } from "../../../shared/types/navigation";
import { ObservationQueryView } from "../../../shared/ui/observation/ObservationQueryView";
import { Intro } from "../../../shared/ui/Intro";
import { TextField } from "../../../shared/ui/TextField";
import { Select, type SelectOption } from "../../../shared/ui/Select";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { FormGrid } from "../../../shared/ui/FormGrid";
import { Panel } from "../../../shared/ui/Panel";
import styles from "./RuleSetWorkspace.module.scss";
import type { RuleSetPort } from "../api/ruleSetPort";
import type { RuleBindingScopePort } from "../api/ruleBindingScopePort";
import type { RuleObservationPort } from "../api/ruleObservationPort";
import type { RuleSourceCatalogPort } from "../model/ruleBindingRegistration";
import {
  createRuleBindingRegistrationCommand,
  createRuleBindingRegistrationReceiptResource,
  createRuleSourceCatalogResource,
} from "../application/ruleBindingRegistration";
import {
  createRuleBindingDirectory,
  createRuleCatalogDirectory,
  createRuleBindingSnapshot,
  createStoredDraftDirectory,
} from "../application/ruleDirectoryResources";
import {
  createRuleCatalogUsageResource,
  createRuleBindingStatesResource,
  createRuleLoadObservationResource,
  createRuleLoadObservationHistoryResource,
} from "../application/ruleObservationResources";
import { createRuleBindingScopeResource } from "../application/ruleBindingScopeResource";
import { createRuleOperation } from "../application/ruleOperation";
import { createRuleDraftWorkflow } from "../application/ruleDraftWorkflow";
import { createRuleDeploymentWorkflow } from "../application/ruleDeploymentWorkflow";
import type { BindingQuery, RuleCatalogQuery } from "../model/ruleDirectory";
import type { RuleBindingStatesQuery } from "../model/ruleObservations";
import { resolveRuleKindFilter, RULE_KIND, RULE_KIND_ALL } from "../model/ruleKinds";
import { RuleBindingDirectory } from "./RuleBindingDirectory";
import { RuleCatalogDirectory } from "./RuleCatalogDirectory";
import { RuleRuntimeObservationPanel } from "./RuleRuntimeObservationPanel";
import { RuleQueryView } from "./RuleQueryView";
import { RuleSetWorkbenchPage } from "./RuleSetWorkbenchPage";
import { RuleDeploymentPanel } from "./RuleDeploymentPanel";
import { RuleBindingRegistrationDialog } from "./RuleBindingRegistrationDialog";
import { StoredDraftCatalog } from "./StoredDraftCatalog";
import { RulePageNavigation } from "./RulePageNavigation";
import {
  RULE_PAGE_SECTION,
  resolveRulePageSection,
  type RulePageSection,
} from "../model/rulePageSection";

type PageContext = DashboardPageProps & {
  readonly scopePort: RuleBindingScopePort;
  readonly ruleSetPort: RuleSetPort;
  readonly observationPort: RuleObservationPort;
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
  scopePort,
  ruleSetPort,
  observationPort,
  sourceCatalogPort,
  ...page
}: PageContext) {
  const { t } = useTranslation();
  const scopeResource = useMemo(() => createRuleBindingScopeResource(scopePort), [scopePort]);
  const scopeSnapshot = useQueryResource(scopeResource, undefined);
  const scopeCatalog = "data" in scopeSnapshot ? scopeSnapshot.data : null;
  const [scopeEnvironment, setScopeEnvironment] = useState(page.environmentId ?? "");
  const [scopeApplication, setScopeApplication] = useState(
    page.appId === ALL_APPLICATIONS ? "" : (page.appId ?? ""),
  );
  const matchingApps = scopeCatalog?.applications.filter((item) => item.id === page.appId) ?? [];
  const inferredEnvironment = matchingApps.length === 1 ? matchingApps[0].environmentId : null;
  const environmentId = page.environmentId ?? inferredEnvironment;
  const validEnvironment =
    page.environmentId !== undefined ||
    (scopeCatalog?.environments.some((item) => item.id === environmentId) ?? false);
  const appId = page.appId === ALL_APPLICATIONS ? null : page.appId;
  const [catalogRefreshing, setCatalogRefreshing] = useState(false);
  const [catalogRefreshFailed, setCatalogRefreshFailed] = useState(false);
  const [catalogRefreshRevision, setCatalogRefreshRevision] = useState(0);
  const catalogRefreshController = useRef<AbortController | null>(null);
  const refreshCatalog = useCallback(() => {
    if (!validEnvironment || !environmentId || catalogRefreshController.current) return;
    const controller = new AbortController();
    catalogRefreshController.current = controller;
    setCatalogRefreshing(true);
    setCatalogRefreshFailed(false);
    void ruleSetPort
      .refreshRuleCatalog(environmentId, appId, controller.signal)
      .then(() => {
        if (!controller.signal.aborted) setCatalogRefreshRevision((revision) => revision + 1);
      })
      .catch(() => {
        if (!controller.signal.aborted) setCatalogRefreshFailed(true);
      })
      .finally(() => {
        if (catalogRefreshController.current === controller) {
          catalogRefreshController.current = null;
          setCatalogRefreshing(false);
        }
      });
  }, [appId, environmentId, ruleSetPort, validEnvironment]);

  useEffect(() => () => scopeResource.cancel(), [scopeResource]);
  useEffect(() => {
    refreshCatalog();
    return () => {
      const controller = catalogRefreshController.current;
      if (controller) {
        controller.abort();
        catalogRefreshController.current = null;
      }
    };
  }, [refreshCatalog]);

  if (!environmentId || !validEnvironment) {
    const continueToSelectedScope = () =>
      page.navigate(ROUTE.Rules, {
        environmentId: scopeEnvironment.trim(),
        appId: scopeApplication.trim() || ALL_APPLICATIONS,
        range: page.range,
        from: page.from,
        to: page.to,
        bindingId: "",
        publicationId: "",
      });
    const scopeSelection = (
      <RuleScopeSelection
        environmentId={scopeEnvironment}
        applicationId={scopeApplication}
        environments={scopeCatalog?.environments ?? []}
        applications={scopeCatalog?.applications ?? []}
        onEnvironmentChange={setScopeEnvironment}
        onApplicationChange={(value) => setScopeApplication(value)}
        onContinue={continueToSelectedScope}
      />
    );
    return (
      <>
        <Intro
          eyebrow={t("rules.eyebrow")}
          title={t("rules.title")}
          description={t("rules.workspace.description")}
        />
        <ObservationQueryView
          snapshot={scopeSnapshot}
          onRetry={() => void scopeResource.load(undefined).catch(() => undefined)}
          title={t("rules.catalog.directoryTitle")}
          descriptions={{
            empty: t("rules.catalog.emptyBody"),
            error: t("rules.catalog.readFailed"),
          }}
          unavailableContent={scopeSelection}
        >
          {() => scopeSelection}
        </ObservationQueryView>
      </>
    );
  }

  const applications =
    scopeCatalog?.applications
      .filter((application) => application.environmentId === environmentId)
      .map(({ id, name }) => ({ id, name })) ?? [];
  const availableApplications =
    applications.length > 0 || !appId ? applications : [{ id: appId, name: appId }];
  return (
    <>
      {scopeSnapshot.status === "error" && (
        <ObservationQueryView
          snapshot={scopeSnapshot}
          onRetry={() => void scopeResource.load(undefined).catch(() => undefined)}
          title={t("rules.catalog.directoryTitle")}
          descriptions={{ error: t("rules.catalog.readFailedWithSelection") }}
        >
          {() => null}
        </ObservationQueryView>
      )}
      <RuleBindingOwner
        key={`${environmentId}:${page.appId}:${page.view}:${page.bindingId ?? "unselected"}`}
        page={page}
        ruleSetPort={ruleSetPort}
        observationPort={observationPort}
        sourceCatalogPort={sourceCatalogPort}
        environmentId={environmentId}
        environments={scopeCatalog?.environments ?? [{ id: environmentId, name: environmentId }]}
        applications={availableApplications}
        catalogRefreshRevision={catalogRefreshRevision}
        catalogRefreshFailed={catalogRefreshFailed}
        catalogRefreshing={catalogRefreshing}
        onRefreshCatalog={refreshCatalog}
        appId={appId}
      />
    </>
  );
}

function RuleScopeSelection({
  environmentId,
  applicationId,
  environments,
  applications,
  onEnvironmentChange,
  onApplicationChange,
  onContinue,
}: {
  readonly environmentId: string;
  readonly applicationId: string;
  readonly environments: readonly { readonly id: string; readonly name: string }[];
  readonly applications: readonly {
    readonly id: string;
    readonly environmentId: string;
    readonly name: string;
  }[];
  readonly onEnvironmentChange: (value: string) => void;
  readonly onApplicationChange: (value: string) => void;
  readonly onContinue: () => void;
}) {
  const { t } = useTranslation();
  const environmentOptions: readonly SelectOption<string>[] = environments.map(({ id, name }) => ({
    value: id,
    label: name,
  }));
  const scopedApplications = applications.filter(
    (application) => application.environmentId === environmentId,
  );
  const applicationOptions: readonly SelectOption<string>[] = [
    { value: ALL_APPLICATIONS, label: t("rules.directory.allApplications") },
    ...scopedApplications.map(({ id, name }) => ({ value: id, label: name })),
  ];
  return (
    <Panel
      title={t("rules.scopeSelection.title")}
      subtitle={t("rules.scopeSelection.description")}
      action={
        <ActionButton variant="primary" disabled={!environmentId.trim()} onClick={onContinue}>
          {t("rules.scopeSelection.continue")}
        </ActionButton>
      }
    >
      <FormGrid>
        {environmentOptions.length > 0 ? (
          <Select
            label={t("rules.registration.environment")}
            value={environmentId}
            options={environmentOptions}
            onChange={(value) => {
              onEnvironmentChange(value);
              onApplicationChange(ALL_APPLICATIONS);
            }}
          />
        ) : (
          <TextField
            label={t("rules.registration.environment")}
            value={environmentId}
            onChange={onEnvironmentChange}
          />
        )}
        {scopedApplications.length > 0 ? (
          <Select
            label={t("rules.registration.application")}
            value={applicationId || ALL_APPLICATIONS}
            options={applicationOptions}
            onChange={onApplicationChange}
          />
        ) : (
          <TextField
            label={t("rules.registration.application")}
            value={applicationId === ALL_APPLICATIONS ? "" : applicationId}
            onChange={onApplicationChange}
          />
        )}
      </FormGrid>
    </Panel>
  );
}

function RuleBindingOwner({
  page,
  ruleSetPort,
  observationPort,
  sourceCatalogPort,
  environmentId,
  environments,
  applications,
  appId,
  catalogRefreshRevision,
  catalogRefreshFailed,
  catalogRefreshing,
  onRefreshCatalog,
}: {
  readonly page: Omit<
    PageContext,
    "scopePort" | "ruleSetPort" | "observationPort" | "sourceCatalogPort"
  >;
  readonly ruleSetPort: RuleSetPort;
  readonly observationPort: RuleObservationPort;
  readonly sourceCatalogPort: RuleSourceCatalogPort;
  readonly environmentId: string;
  readonly environments: readonly { readonly id: string; readonly name: string }[];
  readonly applications: readonly { readonly id: string; readonly name: string }[];
  readonly appId: string | null;
  readonly catalogRefreshRevision: number;
  readonly catalogRefreshFailed: boolean;
  readonly catalogRefreshing: boolean;
  readonly onRefreshCatalog: () => void;
}) {
  const { t } = useTranslation();
  const session = useSession();
  const canRead = useCan(SESSION_CAPABILITY.MetricsView);
  const canWrite = useCan(SESSION_CAPABILITY.RulesWrite);
  const ownerKey = `demo-session-${session.roleId}`;
  const readAccess = useMemo(() => accessObserver(ownerKey, canRead), [ownerKey, canRead]);
  const writeAccess = useMemo(() => accessObserver(ownerKey, canWrite), [ownerKey, canWrite]);
  const port = ruleSetPort;
  const directory = useMemo(() => createRuleBindingDirectory(port, readAccess), [port, readAccess]);
  const catalogDirectory = useMemo(
    () => createRuleCatalogDirectory(port, readAccess),
    [port, readAccess],
  );
  const bindingStatesResource = useMemo(
    () => createRuleBindingStatesResource(observationPort, readAccess),
    [observationPort, readAccess],
  );
  const loadObservationsResource = useMemo(
    () => createRuleLoadObservationResource(observationPort, readAccess),
    [observationPort, readAccess],
  );
  const loadObservationHistoryResource = useMemo(
    () => createRuleLoadObservationHistoryResource(observationPort, readAccess),
    [observationPort, readAccess],
  );
  const catalogUsageResource = useMemo(
    () => createRuleCatalogUsageResource(observationPort, readAccess),
    [observationPort, readAccess],
  );
  const catalogInstanceResource = useMemo(
    () => createRuleLoadObservationResource(observationPort, readAccess),
    [observationPort, readAccess],
  );
  const sourceCatalog = useMemo(
    () => createRuleSourceCatalogResource(sourceCatalogPort, writeAccess),
    [sourceCatalogPort, writeAccess],
  );
  const bindingRegistration = useMemo(
    () => createRuleBindingRegistrationCommand(port, writeAccess),
    [port, writeAccess],
  );
  const bindingRegistrationReceipt = useMemo(
    () => createRuleBindingRegistrationReceiptResource(port, writeAccess),
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
  useEffect(() => () => bindingStatesResource.cancel(), [bindingStatesResource]);
  useEffect(() => () => loadObservationsResource.cancel(), [loadObservationsResource]);
  useEffect(() => () => loadObservationHistoryResource.cancel(), [loadObservationHistoryResource]);
  useEffect(() => () => catalogInstanceResource.cancel(), [catalogInstanceResource]);
  useEffect(
    () => () => {
      catalogDirectory.cancel();
    },
    [catalogDirectory],
  );
  useOwnedDisposal(sourceCatalog);
  useOwnedDisposal(bindingRegistration);
  useOwnedDisposal(bindingRegistrationReceipt);
  useEffect(() => () => bindingSnapshot.cancel(), [bindingSnapshot]);

  const selectedId = page.bindingId ?? null;
  const selectedQuery = useMemo(
    () => ({ ...query, environmentId, appId }),
    [query, environmentId, appId],
  );
  const catalogQuery: RuleCatalogQuery = selectedQuery;
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
  const observationQuery: RuleBindingStatesQuery = {
    environmentId,
    appId,
    kind: selectedQuery.kind,
    page: 1,
    pageSize: 100,
  };
  const activeSection = resolveRulePageSection(
    page.section,
    page.bindingId,
    page.publicationId,
    page.versionId,
  );
  const sectionDescriptions: Readonly<Record<RulePageSection, string>> = {
    [RULE_PAGE_SECTION.Catalog]: t("rules.sections.catalogDescription"),
    [RULE_PAGE_SECTION.Runtime]: t("rules.sections.runtimeDescription"),
    [RULE_PAGE_SECTION.Bindings]: t("rules.sections.bindingsDescription"),
    [RULE_PAGE_SECTION.Drafts]: t("rules.sections.draftsDescription"),
    [RULE_PAGE_SECTION.Editor]: t("rules.sections.editorDescription"),
    [RULE_PAGE_SECTION.Publications]: t("rules.sections.publicationsDescription"),
    [RULE_PAGE_SECTION.Recovery]: t("rules.sections.recoveryDescription"),
  };

  return (
    <>
      <Intro
        eyebrow={t("rules.eyebrow")}
        title={t("rules.title")}
        description={sectionDescriptions[activeSection]}
      />
      <RulePageNavigation
        section={activeSection}
        onSelect={(section) => {
          setRegistrationOpen(false);
          page.navigate(ROUTE.Rules, { section });
        }}
      />
      {activeSection === RULE_PAGE_SECTION.Runtime && (
        <RuleRuntimeObservationPanel
          bindingStates={bindingStatesResource}
          loadObservations={loadObservationsResource}
          loadObservationHistory={loadObservationHistoryResource}
          query={observationQuery}
          refreshRevision={catalogRefreshRevision}
          selectedBinding={selectedBinding}
          locked={!canRead}
          onSelectBinding={(binding) => {
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
              section: RULE_PAGE_SECTION.Runtime,
            });
          }}
        />
      )}
      {activeSection === RULE_PAGE_SECTION.Catalog && (
        <RuleCatalogDirectory
          resource={catalogDirectory}
          usageResource={catalogUsageResource}
          instanceResource={catalogInstanceResource}
          ruleSetPort={ruleSetPort}
          readAccess={readAccess}
          query={catalogQuery}
          refreshRevision={catalogRefreshRevision}
          environments={environments.map(({ id, name }) => ({ value: id, label: name }))}
          applications={applications.map(({ id, name }) => ({ value: id, label: name }))}
          locked={!canRead}
          refreshing={catalogRefreshing}
          refreshFailed={catalogRefreshFailed}
          onRefresh={onRefreshCatalog}
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
          onSelectBinding={(binding) => {
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
              section: RULE_PAGE_SECTION.Editor,
            });
          }}
        />
      )}
      {activeSection === RULE_PAGE_SECTION.Bindings && (
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
              section: RULE_PAGE_SECTION.Editor,
            });
          }}
        />
      )}
      {activeSection === RULE_PAGE_SECTION.Bindings && registrationOpen && (
        <RuleBindingRegistrationDialog
          environmentId={environmentId}
          applications={applications}
          defaultKind={query.kind ?? RULE_KIND.Flow}
          sourceResource={sourceCatalog}
          command={bindingRegistration}
          receiptResource={bindingRegistrationReceipt}
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
              section: RULE_PAGE_SECTION.Editor,
            });
            void directory.load(selectedQuery).catch(() => undefined);
          }}
        />
      )}
      {selectedId && selectedBinding && (
        <RuleWorkspaceOwner
          binding={selectedBinding}
          section={activeSection}
          onDraftOpened={() => page.navigate(ROUTE.Rules, { section: RULE_PAGE_SECTION.Editor })}
          port={port}
          readAccess={readAccess}
          writeAccess={writeAccess}
          publicationId={page.publicationId}
          versionId={page.versionId}
        />
      )}
      {selectedId &&
        !selectedBinding &&
        activeSection !== RULE_PAGE_SECTION.Catalog &&
        activeSection !== RULE_PAGE_SECTION.Runtime &&
        activeSection !== RULE_PAGE_SECTION.Bindings && (
          <RuleQueryView
            snapshot={bindingSnapshotState}
            onRetry={() => void bindingSnapshot.load(selectedId).catch(() => undefined)}
          >
            {() => null}
          </RuleQueryView>
        )}
      {!selectedId &&
        activeSection !== RULE_PAGE_SECTION.Catalog &&
        activeSection !== RULE_PAGE_SECTION.Runtime &&
        activeSection !== RULE_PAGE_SECTION.Bindings && (
          <Panel
            title={t("rules.sections.bindingRequiredTitle")}
            subtitle={t("rules.sections.bindingRequiredDescription")}
            action={
              <ActionButton
                variant="primary"
                onClick={() => page.navigate(ROUTE.Rules, { section: RULE_PAGE_SECTION.Bindings })}
              >
                {t("rules.sections.openBindings")}
              </ActionButton>
            }
          >
            <div className={styles.content}>
              <p>{t("rules.sections.bindingRequiredDescription")}</p>
            </div>
          </Panel>
        )}
    </>
  );
}

function RuleWorkspaceOwner({
  binding,
  section,
  onDraftOpened,
  port,
  readAccess,
  writeAccess,
  publicationId,
  versionId,
}: {
  readonly binding: import("../model/ruleSet").RuleBinding;
  readonly section: RulePageSection;
  readonly onDraftOpened: () => void;
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
  const storedDrafts = useMemo(
    () => createStoredDraftDirectory(binding, port, writeAccess, operation),
    [binding, operation, port, writeAccess],
  );
  useOwnedDisposal(storedDrafts);
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
      {section === RULE_PAGE_SECTION.Drafts && (
        <StoredDraftCatalog
          bindingId={binding.id}
          resource={storedDrafts}
          workflow={draft}
          onOpened={onDraftOpened}
        />
      )}
      {section === RULE_PAGE_SECTION.Editor && (
        <RuleSetWorkbenchPage
          workflow={draft}
          binding={binding}
          newFormKey={() => crypto.randomUUID()}
        />
      )}
      {(section === RULE_PAGE_SECTION.Publications || section === RULE_PAGE_SECTION.Recovery) && (
        <RuleDeploymentPanel
          bindingId={binding.id}
          workflow={deployment}
          view={section}
          initialPublicationId={publicationId}
          initialVersionId={versionId}
        />
      )}
    </>
  );
}
