import { useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useQueryResource } from "../../../shared/state/useQueryResource";
import type { QueryResource } from "../../../shared/state/queryResource";
import type { QuerySnapshot } from "../../../shared/state/queryResource";
import { Intro } from "../../../shared/ui/Intro";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { NumberCard } from "../../../shared/ui/NumberCard";
import { ObservationQueryView } from "../../../shared/ui/observation/ObservationQueryView";
import { ObservationContextBar } from "../../../shared/ui/observation/ObservationContextBar";
import type { ObservationOption } from "../../../shared/ui/observation/ObservationFilters";
import type { Navigate } from "../../../shared/types/navigation";
import type {
  IncidentQuery,
  IncidentPage,
  IncidentDetailQuery,
  IncidentEvidence,
} from "../model/incidentObservation";
import type { InstanceCatalog, ObservedInstance } from "../../applications";
import { IncidentObservationFilters } from "./IncidentObservationFilters";
import { ObservedIncidentTimeline } from "./ObservedIncidentTimeline";
import { ObservedIncidentEvidence } from "./ObservedIncidentEvidence";
import styles from "./IncidentObservation.module.scss";
import { formatLocaleNumber } from "../../../shared/presentation/formatLocaleNumber";
const COUNTER_LABEL = Object.freeze({
  total: "faults.observed.total",
  critical: "faults.summary.critical",
  warning: "faults.summary.warning",
  ruleChanges: "faults.summary.ruleChange",
  affectedApplications: "faults.summary.affectedApps",
});

/** Compose independently owned list/evidence reads. App/URL owns query and explicit event selection. */
export function IncidentObservationPage({
  resources,
  instanceSnapshot,
  instances,
  selectedInstance,
  instanceTotal,
  query,
  selectedEventId,
  onQueryChange,
  onSelect,
  onInstanceChange,
  environments,
  applications,
  navigate,
  clock,
}: {
  readonly resources: {
    readonly timeline: QueryResource<IncidentQuery, IncidentPage>;
    readonly evidence: QueryResource<IncidentDetailQuery, IncidentEvidence>;
  };
  readonly instanceSnapshot: QuerySnapshot<InstanceCatalog>;
  readonly instances: readonly ObservedInstance[];
  readonly selectedInstance: ObservedInstance | null;
  readonly instanceTotal: number;
  readonly query: IncidentQuery;
  readonly selectedEventId: string | null;
  readonly onQueryChange: (query: IncidentQuery) => void;
  readonly onSelect: (id: string | null) => void;
  readonly onInstanceChange: (instance: ObservedInstance | null) => void;
  readonly environments: readonly ObservationOption[];
  readonly applications: readonly ObservationOption[];
  readonly navigate: Navigate;
  readonly clock?: () => number;
}) {
  const { t, i18n } = useTranslation();
  const snapshot = useQueryResource(resources.timeline, query);
  // Cursor movement does not replace or reload the selected evidence. Filter changes clear selection explicitly.
  const selection = useMemo<IncidentDetailQuery | null>(
    () =>
      selectedEventId === null
        ? null
        : {
            context: query.context,
            eventId: selectedEventId,
            severity: query.severity,
            category: query.category,
          },
    [selectedEventId, query.context, query.severity, query.category],
  );
  useEffect(() => {
    if (selection === null) resources.evidence.reset();
  }, [resources.evidence, selection]);
  const refresh = () => {
    void resources.timeline.load(query).catch(() => undefined);
  };
  const locale = i18n.resolvedLanguage ?? i18n.language;
  return (
    <>
      <Intro
        eyebrow={t("faults.intro.eyebrow")}
        title={t("faults.intro.title")}
        description={t("faults.intro.description")}
      />
      <IncidentObservationFilters
        query={query}
        environments={environments}
        applications={applications}
        instances={instances}
        selectedInstance={selectedInstance}
        instancesLoading={["idle", "loading", "refreshing"].includes(instanceSnapshot.status)}
        instancesUnavailable={
          instanceSnapshot.status === "error" || instanceSnapshot.status === "denied"
        }
        instancesLimited={instanceTotal > instances.length}
        instanceTotal={instanceTotal}
        onInstanceChange={onInstanceChange}
        clock={clock}
        onChange={(next) => {
          onQueryChange(next);
        }}
      />
      <ObservationContextBar
        context={query.context}
        asOfMs={"data" in snapshot ? snapshot.data.asOfMs : undefined}
      />
      <ActionButton
        data-incident-list-refresh
        disabled={["loading", "refreshing", "denied"].includes(snapshot.status)}
        onClick={refresh}
      >
        {t("observation.refresh")}
      </ActionButton>
      {"data" in snapshot && (
        <section className={styles.statistics} data-incident-statistics>
          {(Object.keys(COUNTER_LABEL) as (keyof typeof COUNTER_LABEL)[]).map((key) => (
            <NumberCard
              key={key}
              label={t(COUNTER_LABEL[key])}
              value={formatLocaleNumber(snapshot.data.statistics[key], locale)}
              note={t("faults.observed.wholeScope")}
            />
          ))}
        </section>
      )}
      <div className={styles.layout}>
        <ObservationQueryView
          snapshot={snapshot}
          onRetry={refresh}
          descriptions={{
            empty: t("faults.observed.empty"),
            filteredEmpty: t("faults.observed.filteredEmpty"),
          }}
        >
          {(page) => (
            <ObservedIncidentTimeline
              page={page}
              selectedId={selectedEventId}
              onSelect={onSelect}
              onCursor={(cursor) => onQueryChange({ ...query, cursor })}
            />
          )}
        </ObservationQueryView>
        {selection === null ? (
          <p role="status">{t("faults.observed.selectExplicit")}</p>
        ) : (
          <ObservedIncidentEvidence
            query={selection}
            resource={resources.evidence}
            navigate={navigate}
          />
        )}
      </div>
    </>
  );
}
