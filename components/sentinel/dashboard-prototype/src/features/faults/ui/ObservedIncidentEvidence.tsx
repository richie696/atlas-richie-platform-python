import { useTranslation } from "react-i18next";
import { useQueryResource } from "../../../shared/state/useQueryResource";
import type { QueryResource } from "../../../shared/state/queryResource";
import { OBSERVATION_SCOPE } from "../../../shared/model/observation";
import { observationNavigation } from "../../../shared/presentation/observation";
import { ROUTE, type Navigate } from "../../../shared/types/navigation";
import { ObservationQueryView } from "../../../shared/ui/observation/ObservationQueryView";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { Panel } from "../../../shared/ui/Panel";
import type { IncidentDetailQuery, IncidentEvidence } from "../model/incidentObservation";
import { incidentFactText } from "../presentation/observedIncident";
import { formatUtcDateTime } from "../../../shared/presentation/utcDateTime";
import styles from "./IncidentObservation.module.scss";
const VIEW = Object.freeze({
  instance: ROUTE.Applications,
  metrics: ROUTE.Realtime,
  rules: ROUTE.Rules,
});
const VIEW_LABEL = Object.freeze({
  instance: "faults.evidence.viewApp",
  metrics: "realtime.intro.title",
  rules: "rules.title",
});
const COMPLETENESS_LABEL = Object.freeze({
  complete: "faults.observed.complete",
  partial: "faults.observed.partial",
  unavailable: "faults.observed.unavailable",
});

/** Independently owned evidence; suggestions are navigation only, never automated diagnosis or rule writes. */
export function ObservedIncidentEvidence({
  resource,
  query,
  navigate,
}: {
  readonly resource: QueryResource<IncidentDetailQuery, IncidentEvidence>;
  readonly query: IncidentDetailQuery;
  readonly navigate: Navigate;
}) {
  const { t, i18n } = useTranslation();
  const snapshot = useQueryResource(resource, query);
  const refresh = () => {
    void resource.load(query).catch(() => undefined);
  };
  return (
    <Panel
      title={t("faults.evidence.title")}
      subtitle={query.eventId}
      action={
        <ActionButton
          data-incident-detail-refresh
          onClick={refresh}
          disabled={["loading", "refreshing", "denied"].includes(snapshot.status)}
        >
          {t("observation.refresh")}
        </ActionButton>
      }
    >
      <ObservationQueryView
        snapshot={snapshot}
        onRetry={refresh}
        descriptions={{ partial: t("faults.observed.partialEvidence") }}
      >
        {(value) => (
          <section data-incident-evidence={value.event.id} className={styles.evidence}>
            <p>
              {incidentFactText(value.event.caption, t, i18n.resolvedLanguage ?? i18n.language)}
            </p>
            <dl className={styles.metadata}>
              <dt>{t("faults.observed.completeness")}</dt>
              <dd>{t(COMPLETENESS_LABEL[value.completeness])}</dd>
              <dt>{t("faults.evidence.affectedApp")}</dt>
              <dd>{value.event.appId}</dd>
              <dt>{t("faults.evidence.relatedInstance")}</dt>
              <dd>{value.event.instanceId ?? "—"}</dd>
              <dt>{t("faults.observed.processEpoch")}</dt>
              <dd>{value.event.processEpoch ?? "—"}</dd>
              <dt>{t("faults.evidence.occurredAt")}</dt>
              <dd>
                {formatUtcDateTime(
                  value.event.occurredAtMs,
                  i18n.resolvedLanguage ?? i18n.language,
                )}
              </dd>
              <dt>{t("faults.observed.receivedAt")}</dt>
              <dd>
                {formatUtcDateTime(
                  value.event.receivedAtMs,
                  i18n.resolvedLanguage ?? i18n.language,
                )}
              </dd>
              <dt>{t("faults.observed.readAt")}</dt>
              <dd>{formatUtcDateTime(value.asOfMs, i18n.resolvedLanguage ?? i18n.language)}</dd>
              <dt>{t("faults.observed.sourceEvent")}</dt>
              <dd>{value.event.sourceEventId ?? "—"}</dd>
              <dt>{t("faults.observed.publication")}</dt>
              <dd>{value.event.publicationId ?? "—"}</dd>
            </dl>
            <h3>{t("faults.evidence.observed")}</h3>
            {value.facts.length === 0 ? (
              <p role="status">{t("faults.observed.noEvidence")}</p>
            ) : (
              <ul className={styles.facts}>
                {value.facts.map((item) => (
                  <li key={item.id} data-incident-fact={item.id}>
                    <p>{incidentFactText(item.fact, t, i18n.resolvedLanguage ?? i18n.language)}</p>
                    <p>
                      {item.source} ·{" "}
                      <time dateTime={new Date(item.atMs).toISOString()}>
                        {formatUtcDateTime(item.atMs, i18n.resolvedLanguage ?? i18n.language)}
                      </time>
                    </p>
                  </li>
                ))}
              </ul>
            )}
            <p role="note">{t("faults.observed.noCausality")}</p>
            <div className={styles.actions}>
              {value.suggestedViews.map((view) => (
                <ActionButton
                  key={view}
                  onClick={() =>
                    navigate(VIEW[view], {
                      ...observationNavigation({
                        ...query.context,
                        appId: value.event.appId,
                        instanceId: value.event.instanceId,
                        scope:
                          value.event.instanceId === null
                            ? OBSERVATION_SCOPE.Application
                            : OBSERVATION_SCOPE.Process,
                      }),
                      eventId: value.event.id,
                      bindingId: view === "rules" ? value.relatedRule?.bindingId : undefined,
                      versionId: view === "rules" ? value.relatedRule?.versionId : undefined,
                      publicationId:
                        view === "rules" ? value.relatedRule?.publicationId : undefined,
                    })
                  }
                >
                  {t(VIEW_LABEL[view])}
                </ActionButton>
              ))}
            </div>
          </section>
        )}
      </ObservationQueryView>
    </Panel>
  );
}
