import { useTranslation } from "react-i18next";
import type { IncidentPage } from "../model/incidentObservation";
import { SEVERITY_LABEL_KEY, CATEGORY_LABEL_KEY } from "../presentation/incidentLabels";
import { incidentFactText } from "../presentation/observedIncident";
import { formatUtcDateTime } from "../../../shared/presentation/utcDateTime";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { Panel } from "../../../shared/ui/Panel";
import styles from "./IncidentObservation.module.scss";

/** Preserve authoritative time/ID order; cursor tokens stay opaque to the view. */
export function ObservedIncidentTimeline({
  page,
  selectedId,
  onSelect,
  onCursor,
}: {
  readonly page: IncidentPage;
  readonly selectedId: string | null;
  readonly onSelect: (id: string) => void;
  readonly onCursor: (cursor: string | null) => void;
}) {
  const { t, i18n } = useTranslation();
  return (
    <Panel
      title={t("faults.timeline.title")}
      subtitle={t("faults.observed.pageSummary", {
        total: page.statistics.total,
        filtered: page.filteredTotal,
        shown: page.items.length,
      })}
    >
      <ol className={styles.timeline}>
        {page.items.map((event) => (
          <li key={event.id} data-observed-incident={event.id}>
            <ActionButton aria-pressed={event.id === selectedId} onClick={() => onSelect(event.id)}>
              {t("faults.observed.selectEvent", { id: event.id })}
            </ActionButton>
            <p>
              <time dateTime={new Date(event.occurredAtMs).toISOString()}>
                {formatUtcDateTime(event.occurredAtMs, i18n.resolvedLanguage ?? i18n.language)}
              </time>{" "}
              · {t(SEVERITY_LABEL_KEY[event.severity])} · {t(CATEGORY_LABEL_KEY[event.category])}
            </p>
            <p>{incidentFactText(event.caption, t, i18n.resolvedLanguage ?? i18n.language)}</p>
            <p>
              {event.appId} · {event.instanceId ?? t("faults.observed.applicationEvent")}
            </p>
          </li>
        ))}
      </ol>
      <div className={styles.actions}>
        <ActionButton disabled={page.query.cursor === null} onClick={() => onCursor(null)}>
          {t("faults.observed.firstPage")}
        </ActionButton>
        <ActionButton disabled={page.nextCursor === null} onClick={() => onCursor(page.nextCursor)}>
          {t("faults.observed.nextPage")}
        </ActionButton>
      </div>
    </Panel>
  );
}
