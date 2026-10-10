import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { IncidentPort } from "../api/incidentPort";
import type { QueryAccessObserver } from "../../../shared/state/ownedQueryResource";
import { useQueryResource } from "../../../shared/state/useQueryResource";
import { OBSERVATION_SCOPE } from "../../../shared/model/observation";
import { observationWindowFromRoute } from "../../../shared/presentation/observation";
import type { DashboardPageProps } from "../../../shared/types/dashboard";
import { ALL_APPLICATIONS, ROUTE } from "../../../shared/types/navigation";
import { ObservationQueryView } from "../../../shared/ui/observation/ObservationQueryView";
import { Select } from "../../../shared/ui/Select";
import { createObservationCatalogResource, createInstanceResources } from "../../applications";
import type { InstancePort, ObservationCatalogPort } from "../../applications";
import type { InstanceCatalogQuery, ObservedInstance } from "../../applications";
import { createIncidentResources } from "../application/incidentResources";
import { incidentQueryFromRoute } from "../model/incidentObservation";
import type { IncidentQuery } from "../model/incidentObservation";
import { IncidentObservationPage } from "./IncidentObservationPage";

type PageContext = DashboardPageProps & {
  readonly catalogPort: ObservationCatalogPort;
  readonly incidentPort: IncidentPort;
  readonly instancePort: InstancePort;
  readonly instanceId?: string;
  readonly environmentId?: string;
  readonly eventId?: string;
  readonly incidentSeverity?: string;
  readonly incidentCategory?: string;
  readonly incidentCursor?: string;
  readonly from?: string;
  readonly to?: string;
};

const PAGE_SIZE = 20;

/**
 * Route owner for the incidents read model. It only chooses identities returned
 * by the authorized observation catalog; facts and evidence remain server-owned.
 */
export function IncidentObservationContainer({
  catalogPort,
  incidentPort,
  instancePort,
  ...page
}: PageContext) {
  const { t } = useTranslation();
  const catalogResource = useMemo(
    () => createObservationCatalogResource(catalogPort),
    [catalogPort],
  );
  const access = useMemo<QueryAccessObserver>(
    () => ({
      read: () => ({ ownerKey: "console-http-session", allowed: true }),
      subscribe: () => () => {},
    }),
    [],
  );
  const resources = useMemo(
    () => createIncidentResources(incidentPort, access),
    [access, incidentPort],
  );
  const instanceResources = useMemo(() => createInstanceResources(instancePort), [instancePort]);
  const catalogSnapshot = useQueryResource(catalogResource, undefined);
  const catalog = "data" in catalogSnapshot ? catalogSnapshot.data : null;
  const [environmentChoice, setEnvironmentChoice] = useState(page.environmentId ?? "");
  const appId = page.appId === ALL_APPLICATIONS ? null : page.appId;
  const appMatches = catalog?.applications.filter((app) => app.id === appId) ?? [];
  const inferredEnvironment = appMatches.length === 1 ? appMatches[0].environmentId : null;
  const validRouteEnvironment = catalog?.environments.some(
    (environment) => environment.id === page.environmentId,
  );
  const environmentId = page.environmentId
    ? validRouteEnvironment
      ? page.environmentId
      : null
    : (inferredEnvironment ??
      (catalog?.environments.length === 1 ? catalog.environments[0].id : null));

  useEffect(
    () => () => {
      catalogResource.cancel();
      resources.timeline.cancel();
      resources.evidence.cancel();
      instanceResources.catalog.cancel();
      instanceResources.detail.cancel();
    },
    [catalogResource, instanceResources, resources],
  );

  if (!catalog || !environmentId) {
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
                catalog?.environments.some((item) => item.id === environmentChoice)
                  ? environmentChoice
                  : ""
              }
              options={
                catalog?.environments.map((item) => ({ value: item.id, label: item.name })) ?? []
              }
              onChange={(id) => {
                setEnvironmentChoice(id);
                page.navigate(ROUTE.Faults, {
                  environmentId: id,
                  appId: appId ?? ALL_APPLICATIONS,
                });
              }}
            />
          </section>
        )}
      </ObservationQueryView>
    );
  }

  if (page.environmentId && !validRouteEnvironment) {
    return (
      <section className="fleet-environment-prompt">
        <Select
          label={t("observation.environment")}
          value={
            catalog.environments.some((item) => item.id === environmentChoice)
              ? environmentChoice
              : ""
          }
          options={catalog.environments.map((item) => ({ value: item.id, label: item.name }))}
          onChange={(id) => {
            setEnvironmentChoice(id);
            page.navigate(ROUTE.Faults, { environmentId: id, appId: appId ?? ALL_APPLICATIONS });
          }}
        />
      </section>
    );
  }

  return (
    <IncidentObservationOwner
      page={page}
      resources={resources}
      instanceResource={instanceResources.catalog}
      instanceId={page.instanceId}
      environmentId={environmentId}
      applications={catalog.applications
        .filter((application) => application.environmentId === environmentId)
        .map(({ id, name }) => ({ id, name }))}
      environments={catalog.environments}
    />
  );
}

function IncidentObservationOwner({
  page,
  resources,
  instanceResource,
  instanceId,
  environmentId,
  environments,
  applications,
}: {
  readonly page: Omit<PageContext, "catalogPort" | "incidentPort" | "instancePort">;
  readonly resources: ReturnType<typeof createIncidentResources>;
  readonly instanceResource: ReturnType<typeof createInstanceResources>["catalog"];
  readonly instanceId?: string;
  readonly environmentId: string;
  readonly environments: readonly { readonly id: string; readonly name: string }[];
  readonly applications: readonly { readonly id: string; readonly name: string }[];
}) {
  const [windowAnchorMs] = useState(() => Date.now());
  const appId = page.appId === ALL_APPLICATIONS ? null : page.appId;
  const window = useMemo(() => {
    return observationWindowFromRoute(page.from, page.to, page.range, windowAnchorMs);
  }, [page.from, page.range, page.to, windowAnchorMs]);
  const baseQuery = useMemo<IncidentQuery>(
    () => ({
      context: {
        environmentId,
        appId,
        instanceId: null,
        resource: null,
        scope: appId === null ? OBSERVATION_SCOPE.Fleet : OBSERVATION_SCOPE.Application,
        window,
      },
      severity: null,
      category: null,
      cursor: null,
      pageSize: PAGE_SIZE,
    }),
    [appId, environmentId, window],
  );
  const instanceCatalogQuery = useMemo<InstanceCatalogQuery>(
    () => ({
      context: baseQuery.context,
      page: 1,
      pageSize: 100,
      search: "",
      attentionOnly: false,
    }),
    [baseQuery.context],
  );
  const instanceSnapshot = useQueryResource(instanceResource, instanceCatalogQuery);
  const instances = "data" in instanceSnapshot ? instanceSnapshot.data.items : [];
  const selectedInstance = instances.find(
    (instance) => instance.instanceId === instanceId && instance.appId === appId,
  );
  const selectedQuery = useMemo<IncidentQuery>(
    () =>
      selectedInstance
        ? {
            ...baseQuery,
            context: {
              ...baseQuery.context,
              appId: selectedInstance.appId,
              instanceId: selectedInstance.instanceId,
              scope: OBSERVATION_SCOPE.Process,
            },
          }
        : baseQuery,
    [baseQuery, selectedInstance],
  );
  const query = useMemo(
    () =>
      incidentQueryFromRoute(selectedQuery, {
        severity: page.incidentSeverity,
        category: page.incidentCategory,
        cursor: page.incidentCursor,
      }),
    [page.incidentCategory, page.incidentCursor, page.incidentSeverity, selectedQuery],
  );

  const navigateContext = (next: typeof query, eventId: string | null) => {
    page.navigate(
      ROUTE.Faults,
      {
        environmentId: next.context.environmentId,
        appId: next.context.appId ?? ALL_APPLICATIONS,
        instanceId: next.context.instanceId ?? undefined,
        metricScope: next.context.instanceId ? OBSERVATION_SCOPE.Process : undefined,
        incidentSeverity: next.severity ?? undefined,
        incidentCategory: next.category ?? undefined,
        incidentCursor: next.cursor ?? undefined,
        range: page.range,
        from: new Date(next.context.window.fromMs).toISOString(),
        to: new Date(next.context.window.toMs).toISOString(),
        eventId: eventId ?? undefined,
      },
      { history: "push" },
    );
  };

  return (
    <IncidentObservationPage
      resources={resources}
      instanceSnapshot={instanceSnapshot}
      instances={instances}
      selectedInstance={selectedInstance ?? null}
      instanceTotal={
        "data" in instanceSnapshot ? instanceSnapshot.data.filteredTotal : instances.length
      }
      query={query}
      selectedEventId={page.eventId ?? null}
      environments={environments}
      applications={applications}
      navigate={page.navigate}
      onQueryChange={(next) => {
        const cursorOnly =
          JSON.stringify([next.context, next.severity, next.category, next.pageSize]) ===
            JSON.stringify([query.context, query.severity, query.category, query.pageSize]) &&
          next.cursor !== query.cursor;
        navigateContext(next, cursorOnly ? (page.eventId ?? null) : null);
      }}
      onSelect={(id) => navigateContext(query, id)}
      onInstanceChange={(instance) => {
        if (instance) {
          page.navigate(
            ROUTE.Faults,
            {
              environmentId,
              appId: instance.appId,
              instanceId: instance.instanceId,
              metricScope: OBSERVATION_SCOPE.Process,
              range: page.range,
              from: new Date(query.context.window.fromMs).toISOString(),
              to: new Date(query.context.window.toMs).toISOString(),
              incidentSeverity: page.incidentSeverity,
              incidentCategory: page.incidentCategory,
              incidentCursor: undefined,
              eventId: undefined,
            },
            { history: "push" },
          );
          return;
        }
        page.navigate(
          ROUTE.Faults,
          {
            environmentId,
            appId: appId ?? ALL_APPLICATIONS,
            instanceId: undefined,
            metricScope: undefined,
            eventId: undefined,
            range: page.range,
            from: new Date(query.context.window.fromMs).toISOString(),
            to: new Date(query.context.window.toMs).toISOString(),
            incidentSeverity: page.incidentSeverity,
            incidentCategory: page.incidentCategory,
            incidentCursor: undefined,
          },
          { history: "push" },
        );
      }}
    />
  );
}
