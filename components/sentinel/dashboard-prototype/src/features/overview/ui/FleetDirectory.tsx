import { useTranslation } from "react-i18next";
import type { FleetSnapshot } from "../model/fleet";
import { FLEET_METRICS } from "../model/fleet";
import { OBSERVATION_SCOPE } from "../../../shared/model/observation";
import {
  OBSERVATION_METRIC_LABEL_KEY,
  OBSERVATION_HEALTH_LABEL_KEY,
  observationNavigation,
} from "../../../shared/presentation/observation";
import { ROUTE, type Navigate } from "../../../shared/types/navigation";
import { Panel } from "../../../shared/ui/Panel";
import { DataTable } from "../../../shared/ui/DataTable";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { MetricValue } from "../../../shared/ui/observation/MetricValue";
import { CoverageSummary } from "../../../shared/ui/observation/CoverageSummary";
import { ActionButton } from "../../../shared/ui/ActionButton";
import styles from "./Fleet.module.scss";

/** Filtered/paged rows with full-scope counters and explicit per-application drill-down identities. */
export function FleetDirectory({
  snapshot,
  navigate,
  onPage,
}: {
  readonly snapshot: FleetSnapshot;
  readonly navigate: Navigate;
  readonly onPage: (page: number) => void;
}) {
  const { t } = useTranslation();
  const page = snapshot.applications;
  return (
    <Panel
      title={t("observation.fleet.table")}
      subtitle={t("observation.fleet.page", {
        page: page.page,
        total: page.total,
        overall: snapshot.totalApplications,
      })}
    >
      <DataTable
        heads={[
          t("observation.application"),
          t("observation.health"),
          t("observation.instances"),
          t("observation.rules"),
          ...FLEET_METRICS.map((metric) => t(OBSERVATION_METRIC_LABEL_KEY[metric])),
          t("observation.action"),
        ]}
        rows={page.items.map((item) => (
          <tr key={item.appId} data-fleet-application={item.appId}>
            <td>{item.name}</td>
            <td>{t(OBSERVATION_HEALTH_LABEL_KEY[item.health])}</td>
            <td>
              <CoverageSummary coverage={item.instanceCoverage} />
            </td>
            <td>
              <CoverageSummary coverage={item.ruleCoverage} />
              <LinkButton
                onClick={() =>
                  navigate(
                    ROUTE.Rules,
                    observationNavigation({
                      ...snapshot.query.context,
                      appId: item.appId,
                      scope: OBSERVATION_SCOPE.Application,
                    }),
                  )
                }
              >
                {t("observation.fleet.inspectRules")}
              </LinkButton>
            </td>
            {FLEET_METRICS.map((metric) => {
              const reading = item.metrics.find((value) => value.metric === metric);
              return <td key={metric}>{reading && <MetricValue reading={reading} />}</td>;
            })}
            <td>
              <LinkButton
                onClick={() =>
                  navigate(ROUTE.Applications, {
                    ...observationNavigation(snapshot.query.context),
                    appId: item.appId,
                    metricScope: undefined,
                  })
                }
              >
                {t("observation.inspect")}
              </LinkButton>
            </td>
          </tr>
        ))}
      />
      <div className={styles.actions}>
        <ActionButton disabled={page.page <= 1} onClick={() => onPage(page.page - 1)}>
          {t("observation.previous")}
        </ActionButton>
        <ActionButton
          disabled={page.page * page.pageSize >= page.total}
          onClick={() => onPage(page.page + 1)}
        >
          {t("observation.next")}
        </ActionButton>
      </div>
    </Panel>
  );
}
