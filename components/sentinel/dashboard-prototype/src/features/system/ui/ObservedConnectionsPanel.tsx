import { useTranslation } from "react-i18next";
import type { QueryResource } from "../../../shared/state/queryResource";
import { useQueryResource } from "../../../shared/state/useQueryResource";
import { Panel } from "../../../shared/ui/Panel";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { DataTable } from "../../../shared/ui/DataTable";
import { connectionProbeExpired, type SystemConnections } from "../model/systemObservation";
import {
  CONNECTION_LABEL_KEY,
  HEALTH_LABEL_KEY,
  HEALTH_REASON_LABEL_KEY,
  CAPABILITY_LABEL_KEY,
} from "../presentation/observationLabels";
import { SystemQueryView } from "./SystemQueryView";
import styles from "./SystemObservation.module.scss";
import { formatUtcDateTime } from "../../../shared/presentation/utcDateTime";
import { formatLocaleNumber } from "../../../shared/presentation/formatLocaleNumber";
/** Render each server probe independently, including no probe/expired facts. Never equate navigator.online with service health. */
export function ObservedConnectionsPanel({
  resource,
}: {
  readonly resource: QueryResource<null, SystemConnections>;
}) {
  const { t, i18n } = useTranslation(),
    state = useQueryResource(resource, null);
  const read = () => void resource.load(null).catch(() => {});
  const unknown = t("system.observed.notObserved");
  const locale = i18n.resolvedLanguage ?? i18n.language;
  const time = (value: number | null) =>
    value === null ? (
      unknown
    ) : (
      <time dateTime={new Date(value).toISOString()}>{formatUtcDateTime(value, locale)}</time>
    );
  return (
    <Panel
      title={t("system.observed.connections")}
      subtitle={t("system.observed.connectionsHint")}
      action={<ActionButton onClick={read}>{t("system.observed.refresh")}</ActionButton>}
    >
      <div className={styles.content}>
        <SystemQueryView snapshot={state} onRetry={read}>
          {(value) => (
            <>
              <p>
                {t("system.observed.readAt")} {time(value.asOfMs)}
              </p>
              <DataTable
                heads={[
                  t("system.observed.connection"),
                  t("system.observed.probeState"),
                  t("system.observed.checkedAt"),
                  t("system.observed.expiresAt"),
                  t("system.observed.latency"),
                  t("system.observed.capabilities"),
                ]}
                rows={value.items.map((item) => (
                  <tr key={item.id} data-system-connection={item.id}>
                    <td>
                      {t(CONNECTION_LABEL_KEY[item.kind])}
                      <br />
                      {item.sourceId ?? item.id}
                      {item.provider ? ` · ${item.provider === "nacos" ? "Nacos" : "Consul"}` : ""}
                    </td>
                    <td>
                      {t(HEALTH_LABEL_KEY[item.state])}
                      {connectionProbeExpired(item, value.asOfMs) && (
                        <p>{t("system.observed.expiredProbe")}</p>
                      )}
                      {item.reason && <p>{t(HEALTH_REASON_LABEL_KEY[item.reason])}</p>}
                    </td>
                    <td>{time(item.checkedAtMs)}</td>
                    <td>{time(item.expiresAtMs)}</td>
                    <td>
                      {item.latencyMs === null
                        ? unknown
                        : t("system.observed.latencyValue", {
                            value: formatLocaleNumber(item.latencyMs, locale, {
                              maximumFractionDigits: 2,
                            }),
                          })}
                    </td>
                    <td>
                      {item.capabilities.length
                        ? item.capabilities
                            .map((capability) => t(CAPABILITY_LABEL_KEY[capability]))
                            .join(" · ")
                        : t("system.observed.noCapability")}
                    </td>
                  </tr>
                ))}
              />
            </>
          )}
        </SystemQueryView>
      </div>
    </Panel>
  );
}
