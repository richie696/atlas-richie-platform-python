import { useTranslation } from "react-i18next";
import type { QueryResource } from "../../../shared/state/queryResource";
import { useQueryResource } from "../../../shared/state/useQueryResource";
import { Panel } from "../../../shared/ui/Panel";
import { ActionButton } from "../../../shared/ui/ActionButton";
import type {
  AgentReportingObservationPage,
  IncidentEventObservationPage,
  SystemProtocols,
} from "../model/systemObservation";
import { PROTOCOL_LABEL_KEY, COMPATIBILITY_LABEL_KEY } from "../presentation/observationLabels";
import { SystemQueryView } from "./SystemQueryView";
import styles from "./SystemObservation.module.scss";
import { formatUtcDateTime } from "../../../shared/presentation/utcDateTime";
import { WorkerProtocolObservationList } from "./WorkerProtocolObservationList";

type PageQuery = { readonly page: number; readonly pageSize: number };

/** Deployment negotiation facts, not the project's implementation/delivery checklist. */
export function ObservedProtocolsPanel({
  resource,
  agentReportingResource,
  incidentEventResource,
}: {
  readonly resource: QueryResource<null, SystemProtocols>;
  readonly agentReportingResource: QueryResource<PageQuery, AgentReportingObservationPage>;
  readonly incidentEventResource: QueryResource<PageQuery, IncidentEventObservationPage>;
}) {
  const { t, i18n } = useTranslation();
  const state = useQueryResource(resource, null);
  const read = () => void resource.load(null).catch(() => {});
  return (
    <Panel
      title={t("system.observed.protocols")}
      subtitle={t("system.observed.protocolsHint")}
      action={<ActionButton onClick={read}>{t("system.observed.refreshProtocols")}</ActionButton>}
    >
      <div className={styles.content}>
        <SystemQueryView snapshot={state} onRetry={read}>
          {(value) => (
            <>
              <p>
                {t("system.observed.readAt")}{" "}
                {formatUtcDateTime(value.asOfMs, i18n.resolvedLanguage ?? i18n.language)}
              </p>
              {value.items.map((item) => (
                <section key={item.kind} data-system-protocol={item.kind}>
                  <h3>{t(PROTOCOL_LABEL_KEY[item.kind])}</h3>
                  <dl className={styles.facts}>
                    <div>
                      <dt>{t("system.observed.supported")}</dt>
                      <dd>{item.supported.join(" · ") || t("system.observed.noCapability")}</dd>
                    </div>
                    <div>
                      <dt>{t("system.observed.active")}</dt>
                      <dd>{item.active ?? t("system.observed.notObserved")}</dd>
                    </div>
                    <div>
                      <dt>{t("system.observed.compatibility")}</dt>
                      <dd>{t(COMPATIBILITY_LABEL_KEY[item.compatibility])}</dd>
                    </div>
                    <div>
                      <dt>{t("system.observed.negotiatedAt")}</dt>
                      <dd>
                        {item.observedAtMs === null ? (
                          t("system.observed.notObserved")
                        ) : (
                          <time dateTime={new Date(item.observedAtMs).toISOString()}>
                            {formatUtcDateTime(
                              item.observedAtMs,
                              i18n.resolvedLanguage ?? i18n.language,
                            )}
                          </time>
                        )}
                      </dd>
                    </div>
                  </dl>
                </section>
              ))}
              <WorkerProtocolObservationList
                resource={agentReportingResource}
                sectionId="agent-reporting-workers-title"
                titleKey="system.observed.workerProtocols.title"
                emptyKey="system.observed.workerProtocols.empty"
              />
              <WorkerProtocolObservationList
                resource={incidentEventResource}
                sectionId="incident-event-workers-title"
                titleKey="system.observed.incidentEventWorkers.title"
                emptyKey="system.observed.incidentEventWorkers.empty"
              />
            </>
          )}
        </SystemQueryView>
      </div>
    </Panel>
  );
}
