import { useTranslation } from "react-i18next";
import type { RealtimeSelection } from "../model/monitoring";
import { selectRealtimeInstance, WINDOW_MODE } from "../model/monitoring";
import { OBSERVATION_SCOPE, OPERATIONAL_METRICS } from "../../../shared/model/observation";
import {
  OBSERVATION_METRIC_LABEL_KEY,
  OBSERVATION_SCOPE_LABEL_KEY,
} from "../../../shared/presentation/observation";
import type { ObservedInstance } from "../../applications";
import {
  ObservationFilters,
  type ObservationOption,
} from "../../../shared/ui/observation/ObservationFilters";
import { Select } from "../../../shared/ui/Select";
import styles from "./Monitoring.module.scss";
const ALL_MONITOR_METRICS = "all";
const ALL_MONITOR_INSTANCES = "all";

/** User selection changes a query, not navigation to another page or the collector's sampling policy. */
export function MonitoringControls({
  selection,
  onChange,
  environments,
  applications,
  instances,
  instanceHint,
  selectedInstanceId,
  instanceCatalogLoading,
  clock,
}: {
  readonly selection: RealtimeSelection;
  readonly onChange: (selection: RealtimeSelection) => void;
  readonly environments: readonly ObservationOption[];
  readonly applications: readonly ObservationOption[];
  readonly instances: readonly ObservedInstance[];
  readonly instanceHint?: string;
  readonly selectedInstanceId: string | null;
  readonly instanceCatalogLoading: boolean;
  readonly clock?: () => number;
}) {
  const { t } = useTranslation();
  const metric = selection.metrics.length === 1 ? selection.metrics[0] : ALL_MONITOR_METRICS;
  return (
    <div className={styles.filters}>
      <ObservationFilters
        context={selection.context}
        onChange={(context) => onChange({ ...selection, context })}
        environments={environments}
        applications={applications}
        clock={clock}
      />
      <Select
        label={t("observation.monitor.instance")}
        hint={instanceHint}
        value={selection.context.instanceId ?? ALL_MONITOR_INSTANCES}
        options={[
          { value: ALL_MONITOR_INSTANCES, label: t("observation.monitor.allInstances") },
          ...instances
            .filter((instance) => instance.supportedScopes.length > 0)
            .map((instance) => ({
              value: instance.instanceId,
              label: instance.instanceId,
            })),
          ...(selection.context.instanceId &&
          !instances.some((instance) => instance.instanceId === selection.context.instanceId)
            ? [{ value: selection.context.instanceId, label: selection.context.instanceId }]
            : []),
        ]}
        disabled={instanceCatalogLoading}
        onChange={(instanceId) => {
          if (instanceId === ALL_MONITOR_INSTANCES) {
            const next = selectRealtimeInstance(selection, null);
            if (next) onChange(next);
            return;
          }
          const instance = instances.find((candidate) => candidate.instanceId === instanceId);
          if (!instance || instance.supportedScopes.length === 0) return;
          const next = selectRealtimeInstance(selection, instance);
          if (next) onChange(next);
        }}
      />
      <Select
        label={t("observation.monitor.scope")}
        value={selection.context.scope}
        options={(selectedInstanceId
          ? (instances.find((instance) => instance.instanceId === selectedInstanceId)
              ?.supportedScopes ?? [])
          : selection.context.appId === null
            ? [OBSERVATION_SCOPE.Fleet]
            : [OBSERVATION_SCOPE.Application]
        ).map((scope) => ({
          value: scope,
          label: t(OBSERVATION_SCOPE_LABEL_KEY[scope]),
        }))}
        disabled={
          selectedInstanceId
            ? (instances.find((instance) => instance.instanceId === selectedInstanceId)
                ?.supportedScopes.length ?? 0) < 2
            : true
        }
        onChange={(scope) => onChange({ ...selection, context: { ...selection.context, scope } })}
      />
      <Select
        label={t("observation.monitor.metric")}
        value={metric}
        options={[
          { value: ALL_MONITOR_METRICS, label: t("observation.monitor.allMetrics") },
          ...OPERATIONAL_METRICS.map((value) => ({
            value,
            label: t(OBSERVATION_METRIC_LABEL_KEY[value]),
          })),
        ]}
        onChange={(id) => {
          const selected = OPERATIONAL_METRICS.find((value) => value === id);
          if (id === ALL_MONITOR_METRICS) onChange({ ...selection, metrics: OPERATIONAL_METRICS });
          else if (selected) onChange({ ...selection, metrics: [selected] });
        }}
      />
      <Select
        label={t("observation.monitor.windowMode")}
        value={selection.windowMode}
        options={[
          { value: WINDOW_MODE.Rolling, label: t("observation.monitor.rolling") },
          { value: WINDOW_MODE.Fixed, label: t("observation.monitor.fixed") },
        ]}
        onChange={(windowMode) => onChange({ ...selection, windowMode })}
      />
    </div>
  );
}
