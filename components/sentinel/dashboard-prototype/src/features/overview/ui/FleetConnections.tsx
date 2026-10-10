import { useTranslation } from "react-i18next";
import type { FleetConnection } from "../model/fleet";
import { Panel } from "../../../shared/ui/Panel";
import { DataTable } from "../../../shared/ui/DataTable";
import { formatUtcDateTime } from "../../../shared/presentation/utcDateTime";
import { formatLocaleNumber } from "../../../shared/presentation/formatLocaleNumber";
const CONNECTION_LABEL_KEY = Object.freeze({
  available: "observation.connection.available",
  unavailable: "observation.connection.unavailable",
  not_configured: "observation.connection.notConfigured",
  unknown: "observation.connection.unknown",
} as const);

/** Actual dependency probes; no browser-online inference or static "demo healthy" state. */
export function FleetConnections({
  connections,
}: {
  readonly connections: readonly FleetConnection[];
}) {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage ?? i18n.language;
  return (
    <Panel
      title={t("observation.fleet.dependencies")}
      subtitle={t("observation.fleet.dependencyScope")}
    >
      <DataTable
        heads={[
          t("observation.connection.provider"),
          t("observation.health"),
          t("observation.connection.probedAt"),
          t("observation.connection.latency"),
        ]}
        rows={connections.map((item) => (
          <tr key={item.id}>
            <td>{item.provider}</td>
            <td>{t(CONNECTION_LABEL_KEY[item.state])}</td>
            <td>
              {item.checkedAtMs === null
                ? "—"
                : formatUtcDateTime(item.checkedAtMs, locale, {
                    dateStyle: "short",
                    timeStyle: "medium",
                  })}
            </td>
            <td>
              {item.latencyMs === null ? "—" : `${formatLocaleNumber(item.latencyMs, locale)} ms`}
            </td>
          </tr>
        ))}
      />
    </Panel>
  );
}
