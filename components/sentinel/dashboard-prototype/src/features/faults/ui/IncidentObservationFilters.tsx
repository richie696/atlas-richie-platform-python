import { useTranslation } from "react-i18next";
import {
  ObservationFilters,
  type ObservationOption,
} from "../../../shared/ui/observation/ObservationFilters";
import { Select } from "../../../shared/ui/Select";
import type { IncidentQuery } from "../model/incidentObservation";
import type { ObservedInstance } from "../../applications";
import { INCIDENT_SEVERITY, INCIDENT_CATEGORY } from "../model/incident";
import { SEVERITY_LABEL_KEY, CATEGORY_LABEL_KEY } from "../presentation/incidentLabels";
import styles from "./IncidentObservation.module.scss";
const ALL = "all";
const ALL_INSTANCES = "scope:all";
const instanceOptionValue = (instance: ObservedInstance) =>
  `instance:${JSON.stringify([instance.appId, instance.instanceId])}`;

/** Query editors never fetch or choose an event. Filtering resets cursor, not whole-scope counters. */
export function IncidentObservationFilters({
  query,
  onChange,
  environments,
  applications,
  instances,
  selectedInstance,
  instancesLoading,
  instancesUnavailable,
  instancesLimited,
  instanceTotal,
  onInstanceChange,
  clock,
}: {
  readonly query: IncidentQuery;
  readonly onChange: (query: IncidentQuery) => void;
  readonly environments: readonly ObservationOption[];
  readonly applications: readonly ObservationOption[];
  readonly instances: readonly ObservedInstance[];
  readonly selectedInstance: ObservedInstance | null;
  readonly instancesLoading: boolean;
  readonly instancesUnavailable: boolean;
  readonly instancesLimited: boolean;
  readonly instanceTotal: number;
  readonly onInstanceChange: (instance: ObservedInstance | null) => void;
  readonly clock?: () => number;
}) {
  const { t } = useTranslation();
  return (
    <section className={styles.filters} aria-label={t("faults.observed.filters")}>
      <ObservationFilters
        context={query.context}
        environments={environments}
        applications={applications}
        clock={clock}
        onChange={(context) => onChange({ ...query, context, cursor: null })}
      />
      <Select
        label={t("observation.monitor.instance")}
        value={selectedInstance ? instanceOptionValue(selectedInstance) : ALL_INSTANCES}
        options={[
          { value: ALL_INSTANCES, label: t("observation.monitor.allInstances") },
          ...instances.map((instance) => {
            const applicationName = applications.find((item) => item.id === instance.appId)?.name;
            return {
              value: instanceOptionValue(instance),
              label: applicationName
                ? `${applicationName} · ${instance.processId ?? instance.instanceId}`
                : (instance.processId ?? instance.instanceId),
            };
          }),
        ]}
        disabled={instancesLoading || instancesUnavailable}
        hint={
          instancesUnavailable
            ? t("observation.monitor.instanceUnavailable")
            : instancesLimited
              ? t("observation.monitor.instanceLimit", {
                  shown: instances.length,
                  total: instanceTotal,
                })
              : undefined
        }
        onChange={(value) => {
          const selected = instances.find((item) => instanceOptionValue(item) === value);
          onInstanceChange(selected ?? null);
        }}
      />
      <Select
        label={t("faults.timeline.severityFilter")}
        value={query.severity ?? ALL}
        options={[
          { value: ALL, label: t("faults.severity.all") },
          ...Object.values(INCIDENT_SEVERITY).map((value) => ({
            value,
            label: t(SEVERITY_LABEL_KEY[value]),
          })),
        ]}
        onChange={(value) => {
          const severity = Object.values(INCIDENT_SEVERITY).find((item) => item === value) ?? null;
          onChange({ ...query, severity, cursor: null });
        }}
      />
      <Select
        label={t("faults.observed.categoryFilter")}
        value={query.category ?? ALL}
        options={[
          { value: ALL, label: t("faults.observed.allCategories") },
          ...Object.values(INCIDENT_CATEGORY).map((value) => ({
            value,
            label: t(CATEGORY_LABEL_KEY[value]),
          })),
        ]}
        onChange={(value) => {
          const category = Object.values(INCIDENT_CATEGORY).find((item) => item === value) ?? null;
          onChange({ ...query, category, cursor: null });
        }}
      />
    </section>
  );
}
