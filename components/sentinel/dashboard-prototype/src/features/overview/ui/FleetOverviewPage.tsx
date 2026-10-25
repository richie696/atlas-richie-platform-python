import { useQueryResource } from "../../../shared/state/useQueryResource";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { QueryResource } from "../../../shared/state/queryResource";
import type { Navigate } from "../../../shared/types/navigation";
import { ObservationContextBar } from "../../../shared/ui/observation/ObservationContextBar";
import { ObservationQueryView } from "../../../shared/ui/observation/ObservationQueryView";
import { MetricCharts } from "../../../shared/ui/observation/MetricCharts";
import { MetricUnavailableView } from "../../../shared/ui/observation/MetricUnavailableView";
import { Intro } from "../../../shared/ui/Intro";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { fleetQueryKey, type FleetQuery, type FleetSnapshot } from "../model/fleet";
import { FleetSummary } from "./FleetSummary";
import { FleetConnections } from "./FleetConnections";
import { FleetDirectory } from "./FleetDirectory";
import { FleetQueryEditor, type ObservationOption } from "./FleetQueryEditor";

/** Formal async entry. Shared resource is injected; this page never chooses fixture/live transport. */
export function FleetOverviewPage({
  resource,
  query,
  onQueryChange,
  navigate,
  environments,
  applications,
  catalogUnavailable = false,
  hostMonitoringSummary,
  clock,
}: {
  readonly resource: QueryResource<FleetQuery, FleetSnapshot>;
  readonly query: FleetQuery;
  readonly onQueryChange: (query: FleetQuery) => void;
  readonly navigate: Navigate;
  readonly environments: readonly ObservationOption[];
  readonly applications: readonly ObservationOption[];
  readonly catalogUnavailable?: boolean;
  readonly hostMonitoringSummary?: ReactNode;
  readonly clock?: () => number;
}) {
  const { t } = useTranslation();
  const snapshot = useQueryResource(resource, query);
  const key = fleetQueryKey(query);
  const refresh = () => {
    void resource.load(query).catch(() => undefined);
  };
  return (
    <>
      <Intro
        eyebrow="OPERATIONS / FLEET"
        title={t("overview.intro.title")}
        description={t("overview.intro.description")}
      />
      <ObservationQueryView
        snapshot={snapshot}
        onRetry={refresh}
        showStatusFeedback={!catalogUnavailable}
      >
        {() => null}
      </ObservationQueryView>
      <FleetQueryEditor
        key={key}
        query={query}
        onChange={onQueryChange}
        environments={environments}
        applications={applications}
        clock={clock}
      />
      <ObservationContextBar
        context={query.context}
        asOfMs={"data" in snapshot ? snapshot.data.asOfMs : undefined}
      />
      <ActionButton
        disabled={
          snapshot.status === "loading" ||
          snapshot.status === "refreshing" ||
          snapshot.status === "denied"
        }
        onClick={refresh}
      >
        {t("observation.refresh")}
      </ActionButton>
      {hostMonitoringSummary}
      <ObservationQueryView
        snapshot={snapshot}
        onRetry={refresh}
        unavailableContent={<MetricUnavailableView />}
        showStatusFeedback={false}
      >
        {(value) => (
          <>
            <FleetSummary snapshot={value} navigate={navigate} />
            <FleetConnections connections={value.connections} />
            <MetricCharts bundle={value.metrics} />
            <FleetDirectory
              snapshot={value}
              navigate={navigate}
              onPage={(page) => onQueryChange({ ...query, page })}
            />
          </>
        )}
      </ObservationQueryView>
    </>
  );
}
