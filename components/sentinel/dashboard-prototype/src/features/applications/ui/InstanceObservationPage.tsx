import { useTranslation } from "react-i18next";
import { useQueryResource } from "../../../shared/state/useQueryResource";
import { useEffect } from "react";
import type { QueryResource } from "../../../shared/state/queryResource";
import type { Navigate } from "../../../shared/types/navigation";
import { ObservationContextBar } from "../../../shared/ui/observation/ObservationContextBar";
import { ObservationQueryView } from "../../../shared/ui/observation/ObservationQueryView";
import { Intro } from "../../../shared/ui/Intro";
import { ActionButton } from "../../../shared/ui/ActionButton";
import type { ObservationOption } from "../../../shared/ui/observation/ObservationFilters";
import {
  instanceCatalogKey,
  type InstanceCatalog,
  type InstanceCatalogQuery,
  type InstanceDetailQuery,
  type InstanceObservation,
} from "../model/instanceObservation";
import { InstanceCatalogFilters } from "./InstanceCatalogFilters";
import { ObservedInstanceDirectory } from "./ObservedInstanceDirectory";
import { ObservedInstanceDetail } from "./ObservedInstanceDetail";
import styles from "./InstanceObservation.module.scss";

/** App/URL owns explicit selection. Neither a page change nor a hidden filtered row auto-selects another instance. */
export function InstanceObservationPage({
  resources,
  query,
  selection,
  requestedInstanceId,
  onQueryChange,
  onSelectionChange,
  environments,
  applications,
  navigate,
  onShowHosts,
  clock,
}: {
  readonly resources: {
    readonly catalog: QueryResource<InstanceCatalogQuery, InstanceCatalog>;
    readonly detail: QueryResource<InstanceDetailQuery, InstanceObservation>;
  };
  readonly query: InstanceCatalogQuery;
  readonly selection: InstanceDetailQuery | null;
  readonly requestedInstanceId?: string;
  readonly onQueryChange: (query: InstanceCatalogQuery) => void;
  readonly onSelectionChange: (query: InstanceDetailQuery | null) => void;
  readonly environments: readonly ObservationOption[];
  readonly applications: readonly ObservationOption[];
  readonly navigate: Navigate;
  readonly onShowHosts?: () => void;
  readonly clock?: () => number;
}) {
  const { t } = useTranslation();
  const snapshot = useQueryResource(resources.catalog, query);
  // The detail child owns its load/cancel lifecycle. Clearing selection also clears completed data.
  useEffect(() => {
    if (selection === null) resources.detail.reset();
  }, [resources.detail, selection]);
  const refresh = () => {
    void resources.catalog.load(query).catch(() => undefined);
  };
  const selectionMatches =
    selection !== null &&
    selection.context.environmentId === query.context.environmentId &&
    (query.context.appId === null || selection.context.appId === query.context.appId) &&
    selection.context.window.fromMs === query.context.window.fromMs &&
    selection.context.window.toMs === query.context.window.toMs;
  return (
    <>
      <Intro
        eyebrow="APPLICATIONS / INSTANCES"
        title={t("applications.intro.title")}
        description={t("applications.intro.description")}
        aside={
          onShowHosts ? (
            <ActionButton onClick={onShowHosts}>{t("applications.hosts.hostsTab")}</ActionButton>
          ) : null
        }
      />
      <InstanceCatalogFilters
        key={instanceCatalogKey(query)}
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
        onClick={refresh}
        disabled={["loading", "refreshing", "denied"].includes(snapshot.status)}
      >
        {t("observation.refresh")}
      </ActionButton>
      <ObservationQueryView snapshot={snapshot} onRetry={refresh}>
        {(value) => (
          <ObservedInstanceDirectory
            catalog={value}
            selection={selectionMatches ? selection : null}
            onSelect={onSelectionChange}
            onPage={(page) => onQueryChange({ ...query, page })}
          />
        )}
      </ObservationQueryView>
      <div className={styles.detail}>
        {selectionMatches ? (
          <ObservedInstanceDetail
            resource={resources.detail}
            query={selection}
            onChange={onSelectionChange}
            navigate={navigate}
          />
        ) : (
          <div role="status">
            <p>
              {requestedInstanceId
                ? t("applications.observed.targetNotFound")
                : t("applications.observed.selectExplicit")}
            </p>
            {requestedInstanceId && (
              <ActionButton onClick={() => onSelectionChange(null)}>
                {t("applications.observed.clearSelection")}
              </ActionButton>
            )}
          </div>
        )}
      </div>
    </>
  );
}
