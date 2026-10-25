import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import {
  ROUTE,
  ALL_APPLICATIONS,
  TIME_RANGE,
  TIME_RANGE_MS,
} from "../../../shared/types/navigation";
import { OBSERVATION_SCOPE } from "../../../shared/model/observation";
import { observationWindowFromRoute } from "../../../shared/presentation/observation";
import type { DashboardPageProps } from "../../../shared/types/dashboard";
import { ObservationCatalogNotice } from "../../../shared/ui/observation/ObservationCatalogNotice";
import type { FleetQuery } from "../model/fleet";
import type { FleetPort } from "../api/fleetPort";
import { createFleetResource } from "../application/fleetResource";
import { createObservationCatalogResource } from "../../applications";
import type { ObservationCatalogPort } from "../../applications";
import { useQueryResource } from "../../../shared/state/useQueryResource";
import { FleetOverviewPage } from "./FleetOverviewPage";
import { FleetOverviewUnavailable } from "./FleetOverviewUnavailable";

/** Route owner: selects the authorized catalog, URL context and resources for the fleet page. */
export function FleetOverviewContainer({
  fleetPort,
  catalogPort,
  hostMonitoringSummary,
  ...page
}: DashboardPageProps & {
  readonly fleetPort: FleetPort;
  readonly catalogPort: ObservationCatalogPort;
  readonly hostMonitoringSummary?: ReactNode;
  readonly environmentId?: string;
  readonly from?: string;
  readonly to?: string;
}) {
  const { t } = useTranslation();
  const catalogResource = useMemo(
    () => createObservationCatalogResource(catalogPort),
    [catalogPort],
  );
  const catalog = useQueryResource(catalogResource, undefined);
  const fleetResource = useMemo(() => createFleetResource(fleetPort), [fleetPort]);
  const [queryDraft, setQueryDraft] = useState<FleetQuery | null>(null);
  const environmentChoice = page.environmentId ?? "";
  const [windowAnchorMs] = useState(() => Date.now());
  const observationWindow = useMemo(
    () => observationWindowFromRoute(page.from, page.to, page.range, windowAnchorMs),
    [page.from, page.range, page.to, windowAnchorMs],
  );
  const catalogValue = "data" in catalog ? catalog.data : null;
  const validChosenEnvironment = catalogValue?.environments.some(
    (environment) => environment.id === environmentChoice,
  );
  const appEnvironments =
    catalogValue?.applications.filter((application) => application.id === page.appId) ?? [];
  const inferredEnvironment =
    appEnvironments.length === 1 ? appEnvironments[0].environmentId : null;
  const environmentId = page.environmentId
    ? page.environmentId
    : validChosenEnvironment
      ? environmentChoice
      : (inferredEnvironment ??
        (catalogValue?.environments.length === 1 ? catalogValue.environments[0].id : null));
  const appId = page.appId === ALL_APPLICATIONS ? null : page.appId;
  const baseQuery = useMemo<FleetQuery | null>(() => {
    if (!environmentId) return null;
    return {
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
      search: "",
      stepMs: 60_000,
    };
  }, [appId, environmentId, observationWindow]);
  const query =
    baseQuery &&
    queryDraft &&
    queryDraft.context.environmentId === baseQuery.context.environmentId &&
    queryDraft.context.appId === baseQuery.context.appId &&
    queryDraft.context.window.fromMs === baseQuery.context.window.fromMs &&
    queryDraft.context.window.toMs === baseQuery.context.window.toMs
      ? queryDraft
      : baseQuery;

  useEffect(
    () => () => {
      catalogResource.cancel();
      fleetResource.cancel();
    },
    [catalogResource, fleetResource],
  );

  if (!query) {
    return (
      <FleetOverviewUnavailable>
        <ObservationCatalogNotice
          snapshot={catalog}
          onRetry={() => void catalogResource.load(undefined).catch(() => undefined)}
          readErrorDescription={t("observation.catalog.readFailed")}
          title={t("observation.catalog.directoryTitle")}
        />
      </FleetOverviewUnavailable>
    );
  }

  const environmentOptions = catalogValue?.environments.map(({ id, name }) => ({ id, name })) ?? [];
  const applicationOptions =
    catalogValue?.applications
      .filter((application) => application.environmentId === query.context.environmentId)
      .map(({ id, name }) => ({ id, name })) ?? [];

  return (
    <>
      {!catalogValue && (
        <ObservationCatalogNotice
          snapshot={catalog}
          onRetry={() => void catalogResource.load(undefined).catch(() => undefined)}
          readErrorDescription={t("observation.catalog.readFailed")}
          title={t("observation.catalog.directoryTitle")}
        />
      )}
      <FleetOverviewPage
        resource={fleetResource}
        query={query}
        environments={environmentOptions}
        applications={applicationOptions}
        catalogUnavailable={!catalogValue}
        hostMonitoringSummary={hostMonitoringSummary}
        navigate={page.navigate}
        onQueryChange={(next) => {
          setQueryDraft(next);
          const duration = next.context.window.toMs - next.context.window.fromMs;
          const range =
            duration === TIME_RANGE_MS[TIME_RANGE.Last15Minutes]
              ? TIME_RANGE.Last15Minutes
              : TIME_RANGE.Last1Hour;
          page.navigate(
            ROUTE.Overview,
            {
              environmentId: next.context.environmentId,
              appId: next.context.appId ?? ALL_APPLICATIONS,
              range,
              from: new Date(next.context.window.fromMs).toISOString(),
              to: new Date(next.context.window.toMs).toISOString(),
            },
            { history: "replace" },
          );
        }}
      />
    </>
  );
}
