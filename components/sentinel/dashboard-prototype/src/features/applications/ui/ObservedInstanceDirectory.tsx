import { useTranslation } from "react-i18next";
import { OPERATIONAL_METRICS } from "../../../shared/model/observation";
import {
  OBSERVATION_METRIC_LABEL_KEY,
  OBSERVATION_HEALTH_LABEL_KEY,
} from "../../../shared/presentation/observation";
import { DataTable } from "../../../shared/ui/DataTable";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { Panel } from "../../../shared/ui/Panel";
import { MetricValue } from "../../../shared/ui/observation/MetricValue";
import { formatUtcDateTime } from "../../../shared/presentation/utcDateTime";
import {
  instanceSelection,
  type InstanceCatalog,
  type InstanceDetailQuery,
  type ObservedInstance,
} from "../model/instanceObservation";
import styles from "./InstanceObservation.module.scss";

/** Page-local host groups deliberately cannot imply a complete deployment topology. */
export function ObservedInstanceDirectory({
  catalog,
  selection,
  onSelect,
  onPage,
}: {
  readonly catalog: InstanceCatalog;
  readonly selection: InstanceDetailQuery | null;
  readonly onSelect: (query: InstanceDetailQuery) => void;
  readonly onPage: (page: number) => void;
}) {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage ?? i18n.language;
  const groups = new Map<string | null, ObservedInstance[]>();
  for (const item of catalog.items)
    groups.set(item.hostId, [...(groups.get(item.hostId) ?? []), item]);
  const date = (atMs: number | null) =>
    atMs === null
      ? "—"
      : formatUtcDateTime(atMs, locale, { dateStyle: "short", timeStyle: "medium" });
  return (
    <Panel
      title={t("applications.matrix.title")}
      subtitle={t("applications.observed.counts", {
        total: catalog.totalInstances,
        attention: catalog.attentionInstances,
        filtered: catalog.filteredTotal,
        page: catalog.query.page,
      })}
    >
      <p className={styles.note}>{t("applications.observed.pageGroups")}</p>
      {[...groups].map(([host, items]) => (
        <details key={host ?? "unknown"} open className={styles.group}>
          <summary>
            {host ?? t("applications.observed.unknownHost")} · {items.length}
          </summary>
          <DataTable
            heads={[
              t("observation.application"),
              t("applications.matrix.head.instance"),
              t("observation.health"),
              t("applications.observed.lastReport"),
              ...OPERATIONAL_METRICS.map((metric) => t(OBSERVATION_METRIC_LABEL_KEY[metric])),
              t("observation.action"),
            ]}
            rows={items.map((item) => (
              <tr
                key={JSON.stringify([item.appId, item.instanceId])}
                data-observed-instance={item.instanceId}
              >
                <td>{item.appId}</td>
                <td>
                  {item.instanceId}
                  <small className={styles.epoch}>{item.processEpoch}</small>
                </td>
                <td>{t(OBSERVATION_HEALTH_LABEL_KEY[item.health])}</td>
                <td>{date(item.lastReportAtMs)}</td>
                {OPERATIONAL_METRICS.map((metric) => {
                  const reading = item.processMetrics.find((value) => value.metric === metric);
                  return <td key={metric}>{reading && <MetricValue reading={reading} />}</td>;
                })}
                <td>
                  <ActionButton
                    aria-pressed={
                      selection?.context.instanceId === item.instanceId &&
                      selection.context.appId === item.appId &&
                      selection.processEpoch === item.processEpoch
                    }
                    onClick={() => onSelect(instanceSelection(item, catalog.query.context))}
                  >
                    {t("observation.inspect")}
                  </ActionButton>
                </td>
              </tr>
            ))}
          />
        </details>
      ))}
      <div className={styles.actions}>
        <ActionButton
          disabled={catalog.query.page <= 1}
          onClick={() => onPage(catalog.query.page - 1)}
        >
          {t("observation.previous")}
        </ActionButton>
        <ActionButton
          disabled={catalog.query.page * catalog.query.pageSize >= catalog.filteredTotal}
          onClick={() => onPage(catalog.query.page + 1)}
        >
          {t("observation.next")}
        </ActionButton>
      </div>
    </Panel>
  );
}
