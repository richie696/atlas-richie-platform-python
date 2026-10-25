import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import { OBSERVATION_SCOPE } from "../../../shared/model/observation";
import { observationWindowFromRoute } from "../../../shared/presentation/observation";
import { useQueryResource } from "../../../shared/state/useQueryResource";
import type { DashboardPageProps } from "../../../shared/types/dashboard";
import {
  ALL_APPLICATIONS,
  ROUTE,
  TIME_RANGE,
  TIME_RANGE_MS,
} from "../../../shared/types/navigation";
import { ObservationQueryView } from "../../../shared/ui/observation/ObservationQueryView";
import { ObservationContextFallback } from "../../../shared/ui/observation/ObservationContextFallback";
import { ObservationCatalogNotice } from "../../../shared/ui/observation/ObservationCatalogNotice";
import { Intro } from "../../../shared/ui/Intro";
import { Select } from "../../../shared/ui/Select";
import { createObservationCatalogResource } from "../application/catalogResource";
import { createInstanceResources } from "../application/instanceResources";
import type { ObservationCatalogPort } from "../api/catalogPort";
import type { InstancePort } from "../api/instancePort";
import { applicationForEnvironment, resolveEnvironmentId } from "../model/observationCatalog";
import { withoutInstanceSelection } from "../model/instanceNavigation";
import {
  INSTANCE_LAYER,
  instanceSelection,
  isInstanceLayer,
  type InstanceCatalogQuery,
  type InstanceDetailQuery,
} from "../model/instanceObservation";
import { InstanceObservationPage } from "./InstanceObservationPage";
import { MissingApplicationState } from "./MissingApplicationState";

type RoutePage = DashboardPageProps & {
  readonly environmentId?: string;
  readonly instanceId?: string;
  readonly metricScope?: string;
  readonly from?: string;
  readonly to?: string;
  readonly search?: string;
  readonly onShowHosts?: () => void;
};
type PageContext = RoutePage & {
  readonly catalogPort: ObservationCatalogPort;
  readonly instancePort: InstancePort;
};

/** Route owner for the authorized instance catalog, explicit selection and shared HTTP transport. */
export function ApplicationsObservationContainer({
  catalogPort,
  instancePort,
  ...page
}: PageContext) {
  const { t } = useTranslation();
  const catalogResource = useMemo(
    () => createObservationCatalogResource(catalogPort),
    [catalogPort],
  );
  const instances = useMemo(() => createInstanceResources(instancePort), [instancePort]);
  const catalogSnapshot = useQueryResource(catalogResource, undefined);
  const [environmentChoice, setEnvironmentChoice] = useState(page.environmentId ?? "");
  const catalog = "data" in catalogSnapshot ? catalogSnapshot.data : null;
  const appId = page.appId === ALL_APPLICATIONS ? null : page.appId;
  const routeEnvironmentValid =
    catalog === null ||
    catalog.environments.some((environment) => environment.id === page.environmentId);
  const chosenEnvironmentValid = catalog?.environments.some(
    (environment) => environment.id === environmentChoice,
  );
  const environmentId = resolveEnvironmentId(catalog, page.environmentId, appId);

  useEffect(
    () => () => {
      catalogResource.cancel();
      // React StrictMode replays mount effects in development. Cancel pending
      // work here; disposing this owner would make the replay permanently inert.
      instances.catalog.cancel();
      instances.detail.cancel();
    },
    [catalogResource, instances],
  );

  const chooseEnvironment = (id: string) => {
    setEnvironmentChoice(id);
    const currentAppId = page.appId === ALL_APPLICATIONS ? null : page.appId;
    const appId =
      applicationForEnvironment(catalog?.applications ?? [], id, currentAppId) ??
      catalog?.applications.find((application) => application.environmentId === id)?.id ??
      ALL_APPLICATIONS;
    page.navigate(ROUTE.Applications, {
      environmentId: id,
      appId,
    });
  };

  if ((!catalog && !page.environmentId) || !environmentId) {
    const intro = (
      <Intro
        eyebrow="APPLICATIONS / INSTANCES"
        title={t("applications.intro.title")}
        description={t("applications.intro.description")}
      />
    );

    if (!catalog && catalogSnapshot.status === "error") {
      return (
        <ObservationContextFallback
          snapshot={catalogSnapshot}
          onRetry={() => void catalogResource.load(undefined).catch(() => undefined)}
          header={intro}
          emptyTitle={t("applications.directory.title")}
          emptyDescription={t("applications.directory.unavailable")}
          readTitle={t("observation.catalog.directoryTitle")}
          readErrorDescription={t("observation.catalog.readFailed")}
        >
          {() => null}
        </ObservationContextFallback>
      );
    }

    if (catalog && catalog.environments.length === 0) {
      return (
        <>
          {intro}
          <section className="fleet-environment-prompt" role="status" data-applications-empty>
            <p>{t("applications.empty.directory")}</p>
          </section>
        </>
      );
    }

    return (
      <>
        {intro}
        <ObservationQueryView
          snapshot={catalogSnapshot}
          onRetry={() => void catalogResource.load(undefined).catch(() => undefined)}
        >
          {() => (
            <section className="fleet-environment-prompt">
              <Select
                label={t("observation.environment")}
                value={chosenEnvironmentValid ? environmentChoice : ""}
                options={
                  catalog?.environments.map((item) => ({ value: item.id, label: item.name })) ?? []
                }
                onChange={chooseEnvironment}
              />
            </section>
          )}
        </ObservationQueryView>
      </>
    );
  }

  if (page.environmentId && !routeEnvironmentValid) {
    return (
      <section className="fleet-environment-prompt">
        <Select
          label={t("observation.environment")}
          value={chosenEnvironmentValid ? environmentChoice : ""}
          options={catalog.environments.map((item) => ({ value: item.id, label: item.name }))}
          onChange={chooseEnvironment}
        />
      </section>
    );
  }

  const requestedAppId = page.appId === ALL_APPLICATIONS ? null : page.appId;
  const environmentApplications =
    catalog?.applications.filter((application) => application.environmentId === environmentId) ??
    [];
  if (
    requestedAppId &&
    catalog &&
    !environmentApplications.some((application) => application.id === requestedAppId)
  ) {
    return (
      <MissingApplicationState
        page={page}
        environmentId={environmentId}
        environments={catalog?.environments.map(({ id, name }) => ({ id, name })) ?? []}
        applications={environmentApplications.map(({ id, name }) => ({ id, name }))}
      />
    );
  }

  return (
    <>
      {!catalog && (
        <ObservationCatalogNotice
          snapshot={catalogSnapshot}
          onRetry={() => void catalogResource.load(undefined).catch(() => undefined)}
          readErrorDescription={t("observation.catalog.readFailed")}
          title={t("observation.catalog.directoryTitle")}
        />
      )}
      <InstanceObservationOwner
        page={page}
        resources={instances}
        environmentId={environmentId}
        catalogAvailable={catalog !== null}
        applications={
          catalog?.applications
            .filter((application) => application.environmentId === environmentId)
            .map(({ id, name }) => ({ id, name })) ?? []
        }
        environments={catalog?.environments ?? []}
      />
    </>
  );
}

function InstanceObservationOwner({
  page,
  resources,
  environmentId,
  catalogAvailable,
  environments,
  applications,
}: {
  readonly page: RoutePage;
  readonly resources: ReturnType<typeof createInstanceResources>;
  readonly environmentId: string;
  readonly catalogAvailable: boolean;
  readonly environments: readonly { readonly id: string; readonly name: string }[];
  readonly applications: readonly { readonly id: string; readonly name: string }[];
}) {
  const [windowAnchorMs] = useState(() => Date.now());
  const [queryDraft, setQueryDraft] = useState<InstanceCatalogQuery | null>(null);
  const [retainedSelection, setRetainedSelection] = useState<InstanceDetailQuery | null>(null);
  const requestedAppId = page.appId === ALL_APPLICATIONS ? null : page.appId;
  const appId =
    (requestedAppId &&
    (!catalogAvailable || applications.some((application) => application.id === requestedAppId))
      ? requestedAppId
      : null) ??
    applications[0]?.id ??
    null;
  const routeAppId = page.appId;
  const navigate = page.navigate;
  useEffect(() => {
    if (!appId || routeAppId === appId) return;
    // A single-application route must not leave an unresolved fleet selection
    // in the URL. Resolve from the authorized environment catalog and replace
    // the URL so refresh/share restore the same concrete app scope.
    navigate(ROUTE.Applications, { environmentId, appId }, { history: "replace" });
  }, [appId, environmentId, navigate, routeAppId]);
  const observationWindow = useMemo(() => {
    return observationWindowFromRoute(page.from, page.to, page.range, windowAnchorMs);
  }, [page.from, page.range, page.to, windowAnchorMs]);
  const baseQuery = useMemo<InstanceCatalogQuery>(
    () => ({
      context: {
        environmentId,
        appId,
        instanceId: null,
        resource: null,
        scope: appId === null ? OBSERVATION_SCOPE.Fleet : OBSERVATION_SCOPE.Application,
        window: observationWindow,
      },
      page: 1,
      pageSize: 20,
      search: page.search ?? "",
      attentionOnly: false,
    }),
    [appId, environmentId, observationWindow, page.search],
  );
  const query = useMemo(() => {
    if (
      queryDraft &&
      queryDraft.context.environmentId === baseQuery.context.environmentId &&
      queryDraft.context.appId === baseQuery.context.appId &&
      queryDraft.context.window.fromMs === baseQuery.context.window.fromMs &&
      queryDraft.context.window.toMs === baseQuery.context.window.toMs
    )
      return { ...queryDraft, search: page.search ?? queryDraft.search };
    return baseQuery;
  }, [baseQuery, page.search, queryDraft]);
  // The page owns the one load effect; this parent only observes the catalog to
  // resolve a deep-linked instance to its authoritative process incarnation.
  const snapshot = useExternalSnapshot(resources.catalog);
  const catalog = "data" in snapshot ? snapshot.data : null;
  const selected =
    catalog?.items.find((instance) => instance.instanceId === page.instanceId) ?? null;
  const scope = isInstanceLayer(page.metricScope) ? page.metricScope : INSTANCE_LAYER.Process;
  const retainedSelectionMatches =
    retainedSelection !== null &&
    retainedSelection.context.environmentId === query.context.environmentId &&
    retainedSelection.context.appId === query.context.appId &&
    retainedSelection.context.window.fromMs === query.context.window.fromMs &&
    retainedSelection.context.window.toMs === query.context.window.toMs &&
    retainedSelection.context.instanceId === page.instanceId;
  const selection = retainedSelectionMatches
    ? { ...retainedSelection, context: { ...retainedSelection.context, scope } }
    : selected
      ? instanceSelection(selected, query.context, scope)
      : null;

  return (
    <InstanceObservationPage
      resources={resources}
      query={query}
      selection={selection}
      requestedInstanceId={page.instanceId}
      environments={environments}
      applications={applications}
      navigate={page.navigate}
      onShowHosts={page.onShowHosts}
      onQueryChange={(next) => {
        setQueryDraft(next);
        const duration = next.context.window.toMs - next.context.window.fromMs;
        const range =
          duration === TIME_RANGE_MS[TIME_RANGE.Last15Minutes]
            ? TIME_RANGE.Last15Minutes
            : TIME_RANGE.Last1Hour;
        const contextChanged =
          next.context.environmentId !== query.context.environmentId ||
          next.context.appId !== query.context.appId ||
          next.context.window.fromMs !== query.context.window.fromMs ||
          next.context.window.toMs !== query.context.window.toMs;
        if (contextChanged) setRetainedSelection(null);
        else if (page.instanceId && selection) setRetainedSelection(selection);
        const routeContext = {
          environmentId: next.context.environmentId,
          appId: next.context.appId ?? ALL_APPLICATIONS,
          range,
          from: new Date(next.context.window.fromMs).toISOString(),
          to: new Date(next.context.window.toMs).toISOString(),
          search: next.search,
        };
        page.navigate(
          ROUTE.Applications,
          contextChanged
            ? withoutInstanceSelection(routeContext)
            : { ...routeContext, ...(page.instanceId ? { instanceId: page.instanceId } : {}) },
          { history: "replace" },
        );
      }}
      onSelectionChange={(next) => {
        setRetainedSelection(next);
        const base = {
          environmentId: query.context.environmentId,
          appId: query.context.appId ?? ALL_APPLICATIONS,
          range: page.range,
          from: new Date(query.context.window.fromMs).toISOString(),
          to: new Date(query.context.window.toMs).toISOString(),
          search: query.search,
        };
        page.navigate(
          ROUTE.Applications,
          next
            ? {
                ...base,
                instanceId: next.context.instanceId ?? undefined,
                metricScope: next.context.scope,
              }
            : withoutInstanceSelection(base),
          { history: "replace" },
        );
      }}
    />
  );
}
