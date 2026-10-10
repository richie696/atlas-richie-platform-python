import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { RealtimePort } from "../api/metricsPort";
import { OBSERVATION_SCOPE, OPERATIONAL_METRICS } from "../../../shared/model/observation";
import { observationWindowFromRoute } from "../../../shared/presentation/observation";
import { useQueryResource } from "../../../shared/state/useQueryResource";
import { useOwnedDisposal } from "../../../shared/state/useOwnedDisposal";
import type { DashboardPageProps } from "../../../shared/types/dashboard";
import { ALL_APPLICATIONS, ROUTE, TIME_RANGE } from "../../../shared/types/navigation";
import { ObservationQueryView } from "../../../shared/ui/observation/ObservationQueryView";
import { Select } from "../../../shared/ui/Select";
import { createInstanceResources, createObservationCatalogResource } from "../../applications";
import type {
  InstanceCatalogQuery,
  InstancePort,
  ObservationCatalogPort,
} from "../../applications";
import { INSTANCE_LAYER, isInstanceLayer } from "../../applications";
import { createRealtimeMonitor } from "../application/realtimeMonitor";
import { WINDOW_MODE, type RealtimeSelection } from "../model/monitoring";
import { LiveMonitoringPage } from "./LiveMonitoringPage";

type PageContext = DashboardPageProps & {
  readonly catalogPort: ObservationCatalogPort;
  readonly instancePort: InstancePort;
  readonly metricsPort: RealtimePort;
  readonly instanceId?: string;
  readonly metricScope?: string;
  readonly environmentId?: string;
  readonly from?: string;
  readonly to?: string;
  /** Incident drill-down is a historical comparison, not a rolling live window. */
  readonly eventId?: string;
};

/** Route owner joining authorized selectors, URL scope and the single polling monitor. */
export function RealtimeObservationContainer({
  catalogPort,
  instancePort,
  metricsPort,
  ...page
}: PageContext) {
  const { t } = useTranslation();
  const catalogResource = useMemo(
    () => createObservationCatalogResource(catalogPort),
    [catalogPort],
  );
  const monitor = useMemo(() => createRealtimeMonitor(metricsPort), [metricsPort]);
  const instanceResources = useMemo(() => createInstanceResources(instancePort), [instancePort]);
  useOwnedDisposal(monitor);
  useOwnedDisposal(instanceResources);
  const catalogSnapshot = useQueryResource(catalogResource, undefined);
  const [environmentChoice, setEnvironmentChoice] = useState(page.environmentId ?? "");
  const catalog = "data" in catalogSnapshot ? catalogSnapshot.data : null;
  const appId = page.appId === ALL_APPLICATIONS ? null : page.appId;
  const appEnvironments = catalog?.applications.filter((app) => app.id === appId) ?? [];
  const inferredEnvironment =
    appEnvironments.length === 1 ? appEnvironments[0].environmentId : null;
  const routeEnvironmentValid = catalog?.environments.some(
    (environment) => environment.id === page.environmentId,
  );
  const chosenEnvironmentValid = catalog?.environments.some(
    (environment) => environment.id === environmentChoice,
  );
  const environmentId = page.environmentId
    ? routeEnvironmentValid
      ? page.environmentId
      : null
    : (inferredEnvironment ??
      (catalog?.environments.length === 1 ? catalog.environments[0].id : null));

  useEffect(
    () => () => {
      catalogResource.cancel();
      monitor.cancel();
      instanceResources.catalog.cancel();
      instanceResources.detail.cancel();
    },
    [catalogResource, instanceResources, monitor],
  );

  const chooseEnvironment = (id: string) => {
    setEnvironmentChoice(id);
    page.navigate(ROUTE.Realtime, {
      environmentId: id,
      appId: appId ?? ALL_APPLICATIONS,
    });
  };

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
              value={chosenEnvironmentValid ? environmentChoice : ""}
              options={
                catalog?.environments.map((item) => ({ value: item.id, label: item.name })) ?? []
              }
              onChange={chooseEnvironment}
            />
          </section>
        )}
      </ObservationQueryView>
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

  return (
    <RealtimeObservationOwner
      page={page}
      monitor={monitor}
      instanceResource={instanceResources.catalog}
      environmentId={environmentId}
      environments={catalog.environments}
      applications={catalog.applications
        .filter((application) => application.environmentId === environmentId)
        .map(({ id, name }) => ({ id, name }))}
    />
  );
}

function RealtimeObservationOwner({
  page,
  monitor,
  instanceResource,
  environmentId,
  environments,
  applications,
}: {
  readonly page: Omit<PageContext, "catalogPort" | "instancePort" | "metricsPort">;
  readonly monitor: ReturnType<typeof createRealtimeMonitor>;
  readonly instanceResource: ReturnType<typeof createInstanceResources>["catalog"];
  readonly environmentId: string;
  readonly environments: readonly { readonly id: string; readonly name: string }[];
  readonly applications: readonly { readonly id: string; readonly name: string }[];
}) {
  const { t } = useTranslation();
  const [windowAnchorMs] = useState(() => Date.now());
  const [override, setOverride] = useState<RealtimeSelection | null>(null);
  const appId = page.appId === ALL_APPLICATIONS ? null : page.appId;
  const observationWindow = useMemo(() => {
    return observationWindowFromRoute(page.from, page.to, page.range, windowAnchorMs);
  }, [page.from, page.range, page.to, windowAnchorMs]);
  const instanceCatalogQuery = useMemo<InstanceCatalogQuery>(
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
      pageSize: 100,
      search: page.instanceId ?? "",
      attentionOnly: false,
    }),
    [appId, environmentId, observationWindow, page.instanceId],
  );
  const instanceSnapshot = useQueryResource(instanceResource, instanceCatalogQuery);
  const instanceCatalog = "data" in instanceSnapshot ? instanceSnapshot.data : null;
  const instanceHint =
    instanceSnapshot.status === "denied"
      ? t("observation.read.denied")
      : instanceSnapshot.status === "error" || instanceSnapshot.status === "stale"
        ? t("observation.read.error")
        : instanceCatalog && instanceCatalog.filteredTotal > instanceCatalog.items.length
          ? t("observation.monitor.instanceLimit", {
              shown: instanceCatalog.items.length,
              total: instanceCatalog.filteredTotal,
            })
          : instanceCatalog && instanceCatalog.filteredTotal === 0
            ? t(
                instanceCatalog.totalInstances === 0
                  ? "observation.read.empty"
                  : "observation.read.filteredEmpty",
              )
            : undefined;
  const selectedInstance =
    instanceCatalog?.items.find((instance) => instance.instanceId === page.instanceId) ?? null;
  const selectedAppId = selectedInstance?.appId ?? appId;
  const requestedScope = isInstanceLayer(page.metricScope) ? page.metricScope : null;
  const instanceScope = selectedInstance
    ? requestedScope && selectedInstance.supportedScopes.includes(requestedScope)
      ? requestedScope
      : selectedInstance.supportedScopes[0]
    : null;
  const baseSelection = useMemo<RealtimeSelection>(
    () => ({
      context: {
        environmentId,
        appId: selectedAppId,
        instanceId: page.instanceId ?? null,
        resource: null,
        scope:
          instanceScope ??
          (selectedAppId === null ? OBSERVATION_SCOPE.Fleet : OBSERVATION_SCOPE.Application),
        window: observationWindow,
      },
      metrics: OPERATIONAL_METRICS,
      stepMs: 60_000,
      windowMode: page.eventId ? WINDOW_MODE.Fixed : WINDOW_MODE.Rolling,
    }),
    [environmentId, instanceScope, observationWindow, page.eventId, page.instanceId, selectedAppId],
  );
  const selection = useMemo(
    () =>
      override &&
      override.context.environmentId === baseSelection.context.environmentId &&
      override.context.appId === baseSelection.context.appId &&
      override.context.instanceId === baseSelection.context.instanceId &&
      override.context.scope === baseSelection.context.scope &&
      override.context.window.fromMs === baseSelection.context.window.fromMs &&
      override.context.window.toMs === baseSelection.context.window.toMs
        ? override
        : baseSelection,
    [baseSelection, override],
  );

  return (
    <LiveMonitoringPage
      monitor={monitor}
      selection={selection}
      environments={environments}
      applications={applications}
      instances={instanceCatalog?.items ?? []}
      instanceHint={instanceHint}
      selectedInstanceId={selectedInstance?.instanceId ?? null}
      instanceCatalogLoading={
        instanceSnapshot.status === "loading" || instanceSnapshot.status === "refreshing"
      }
      queryReady={
        !page.instanceId ||
        (selectedInstance !== null &&
          selectedInstance.supportedScopes.length > 0 &&
          instanceScope !== null)
      }
      instanceTargetMissing={
        !!page.instanceId &&
        !selectedInstance &&
        instanceSnapshot.status !== "loading" &&
        instanceSnapshot.status !== "refreshing"
      }
      instanceTargetUnsupported={!!page.instanceId && selectedInstance !== null && !instanceScope}
      onSelectionChange={(next) => {
        setOverride(next);
        page.navigate(
          ROUTE.Realtime,
          {
            environmentId: next.context.environmentId,
            appId: next.context.appId ?? ALL_APPLICATIONS,
            instanceId: next.context.instanceId ?? undefined,
            metricScope: next.context.scope,
            range: page.range,
            from: new Date(next.context.window.fromMs).toISOString(),
            to: new Date(next.context.window.toMs).toISOString(),
          },
          { history: "replace" },
        );
      }}
    />
  );
}
