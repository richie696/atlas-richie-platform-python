import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { QueryResource } from "../../../shared/state/queryResource";
import { useQueryResource } from "../../../shared/state/useQueryResource";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { COMPATIBILITY_LABEL_KEY } from "../presentation/observationLabels";
import type {
  AgentReportingObservationPage,
  IncidentEventObservationPage,
} from "../model/systemObservation";
import { SystemQueryView } from "./SystemQueryView";
import styles from "./SystemObservation.module.scss";
import { formatUtcDateTime } from "../../../shared/presentation/utcDateTime";

type ProtocolObservationPage = AgentReportingObservationPage | IncidentEventObservationPage;
type PageQuery = { readonly page: number; readonly pageSize: number };

/** Paginated worker facts for one authority; distinct resources never imply one another. */
export function WorkerProtocolObservationList({
  resource,
  titleKey,
  emptyKey,
  sectionId,
}: {
  readonly resource: QueryResource<PageQuery, ProtocolObservationPage>;
  readonly titleKey:
    "system.observed.workerProtocols.title" | "system.observed.incidentEventWorkers.title";
  readonly emptyKey:
    "system.observed.workerProtocols.empty" | "system.observed.incidentEventWorkers.empty";
  readonly sectionId: string;
}) {
  const { t, i18n } = useTranslation();
  const [page, setPage] = useState(1);
  const query = useMemo(() => ({ page, pageSize: 20 }), [page]);
  const state = useQueryResource(resource, query);
  const read = () => void resource.load(query).catch(() => {});
  return (
    <section aria-labelledby={sectionId} data-system-protocol-boundary={sectionId}>
      <h3 id={sectionId}>{t(titleKey)}</h3>
      <SystemQueryView snapshot={state} onRetry={read}>
        {(workers) => (
          <>
            <p>
              {t("system.observed.readAt")}{" "}
              {formatUtcDateTime(workers.asOfMs, i18n.resolvedLanguage ?? i18n.language)}
            </p>
            {workers.items.length === 0 ? (
              <p>{t(emptyKey)}</p>
            ) : (
              <ol className={styles.workerList}>
                {workers.items.map((worker) => (
                  <li
                    className={styles.worker}
                    data-system-protocol-worker={worker.instanceId}
                    key={`${worker.environmentId}:${worker.appId}:${worker.instanceId}`}
                  >
                    <h4>{worker.instanceId}</h4>
                    <dl className={styles.facts}>
                      <div>
                        <dt>{t("system.observed.workerProtocols.application")}</dt>
                        <dd>
                          {worker.environmentId} / {worker.appId}
                        </dd>
                      </div>
                      <div>
                        <dt>{t("system.observed.workerProtocols.process")}</dt>
                        <dd>{worker.processId}</dd>
                      </div>
                      <div>
                        <dt>{t("system.observed.supported")}</dt>
                        <dd>
                          {worker.collectorSupported.join(" · ") ||
                            t("system.observed.noCapability")}
                        </dd>
                      </div>
                      <div>
                        <dt>{t("system.observed.active")}</dt>
                        <dd>{worker.runtimeVersion ?? t("system.observed.notObserved")}</dd>
                      </div>
                      <div>
                        <dt>{t("system.observed.compatibility")}</dt>
                        <dd>{t(COMPATIBILITY_LABEL_KEY[worker.compatibility])}</dd>
                      </div>
                      <div>
                        <dt>{t("system.observed.negotiatedAt")}</dt>
                        <dd>
                          {worker.observedAtMs === null ? (
                            t("system.observed.notObserved")
                          ) : (
                            <time dateTime={new Date(worker.observedAtMs).toISOString()}>
                              {formatUtcDateTime(
                                worker.observedAtMs,
                                i18n.resolvedLanguage ?? i18n.language,
                              )}
                            </time>
                          )}
                        </dd>
                      </div>
                    </dl>
                  </li>
                ))}
              </ol>
            )}
            <nav
              className={styles.workerPagination}
              aria-label={t("system.observed.workerProtocols.pagination")}
            >
              <ActionButton
                disabled={page <= 1}
                onClick={() => setPage((current) => Math.max(1, current - 1))}
              >
                {t("system.observed.workerProtocols.previous")}
              </ActionButton>
              <span>
                {t("system.observed.workerProtocols.page", {
                  page,
                  pages: Math.max(1, Math.ceil(workers.total / workers.pageSize)),
                })}
              </span>
              <ActionButton
                disabled={page * workers.pageSize >= workers.total}
                onClick={() => setPage((current) => current + 1)}
              >
                {t("system.observed.workerProtocols.next")}
              </ActionButton>
            </nav>
          </>
        )}
      </SystemQueryView>
    </section>
  );
}
