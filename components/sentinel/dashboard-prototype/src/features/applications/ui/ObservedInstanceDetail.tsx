import { useTranslation } from "react-i18next";
import { useQueryResource } from "../../../shared/state/useQueryResource";
import type { QueryResource } from "../../../shared/state/queryResource";
import {
  observationNavigation,
  OBSERVATION_SCOPE_LABEL_KEY,
} from "../../../shared/presentation/observation";
import { ROUTE, type Navigate } from "../../../shared/types/navigation";
import { Panel } from "../../../shared/ui/Panel";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { ObservationQueryView } from "../../../shared/ui/observation/ObservationQueryView";
import { ObservationContextBar } from "../../../shared/ui/observation/ObservationContextBar";
import { MetricCards } from "../../../shared/ui/observation/MetricCards";
import { MetricCharts } from "../../../shared/ui/observation/MetricCharts";
import {
  INSTANCE_LAYER,
  INSTANCE_READ_FAILURE,
  type InstanceDetailQuery,
  type InstanceObservation,
} from "../model/instanceObservation";
import styles from "./InstanceObservation.module.scss";
import { RULE_RECEIPT_LABEL_KEY } from "../presentation/observationLabels";

/** Exact selected incarnation/layer owns this response. Unsupported layers never render process/container curves. */
export function ObservedInstanceDetail({
  resource,
  query,
  onChange,
  navigate,
}: {
  readonly resource: QueryResource<InstanceDetailQuery, InstanceObservation>;
  readonly query: InstanceDetailQuery;
  readonly onChange: (query: InstanceDetailQuery | null) => void;
  readonly navigate: Navigate;
}) {
  const { t } = useTranslation();
  const snapshot = useQueryResource(resource, query);
  const refresh = () => {
    void resource.load(query).catch(() => undefined);
  };
  return (
    <Panel
      title={t("applications.detail.title")}
      subtitle={`${query.context.instanceId} · ${query.processEpoch}`}
    >
      <div className={styles.actions}>
        {Object.values(INSTANCE_LAYER).map((scope) => (
          <ActionButton
            key={scope}
            aria-pressed={query.context.scope === scope}
            onClick={() => onChange({ ...query, context: { ...query.context, scope } })}
          >
            {t(OBSERVATION_SCOPE_LABEL_KEY[scope])}
          </ActionButton>
        ))}
        <ActionButton
          data-instance-detail-refresh
          disabled={["loading", "refreshing", "denied"].includes(snapshot.status)}
          onClick={refresh}
        >
          {t("observation.refresh")}
        </ActionButton>
      </div>
      <ObservationContextBar
        context={query.context}
        asOfMs={"data" in snapshot ? snapshot.data.asOfMs : undefined}
      />
      <ObservationQueryView snapshot={snapshot} onRetry={refresh}>
        {(value) => (
          <>
            <dl className={styles.identity}>
              <dt>{t("applications.scope.host")}</dt>
              <dd>{value.instance.hostId ?? "—"}</dd>
              <dt>{t("applications.scope.container")}</dt>
              <dd>{value.instance.containerId ?? "—"}</dd>
              <dt>{t("applications.scope.process")}</dt>
              <dd>{value.instance.processId ?? "—"}</dd>
              <dt>{t("applications.observed.receipt")}</dt>
              <dd data-instance-receipt>
                {t(RULE_RECEIPT_LABEL_KEY[value.instance.ruleReceipt.state])} ·{" "}
                {value.instance.ruleReceipt.appliedVersionId ?? "—"} /{" "}
                {value.instance.ruleReceipt.desiredVersionId ?? "—"}
              </dd>
            </dl>
            {value.metrics === null ? (
              <p role="status" data-instance-unsupported className={styles.note}>
                {t("applications.observed.unsupported")}
              </p>
            ) : (
              <>
                <MetricCards readings={value.metrics.summary} />
                <MetricCharts bundle={value.metrics} />
              </>
            )}
            <div className={styles.actions}>
              <ActionButton
                onClick={() => navigate(ROUTE.Rules, observationNavigation(value.query.context))}
              >
                {t("applications.action.viewRules")}
              </ActionButton>
              <ActionButton
                onClick={() => navigate(ROUTE.Realtime, observationNavigation(value.query.context))}
              >
                {t("realtime.intro.title")}
              </ActionButton>
            </div>
          </>
        )}
      </ObservationQueryView>
      {snapshot.status === "error" &&
        (snapshot.error.code === INSTANCE_READ_FAILURE.IncarnationChanged ||
          snapshot.error.status === 404 ||
          snapshot.error.status === 410) && (
          <div role="status" className={styles.note}>
            <p>
              {snapshot.error.code === INSTANCE_READ_FAILURE.IncarnationChanged
                ? t("applications.observed.incarnationChanged")
                : t("applications.observed.targetNotFound")}
            </p>
            <ActionButton onClick={() => onChange(null)}>
              {t("applications.observed.clearSelection")}
            </ActionButton>
          </div>
        )}
    </Panel>
  );
}
