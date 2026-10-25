import { useTranslation } from "react-i18next";
import { METRIC_ID, METRIC_UNIT, OPERATIONAL_METRICS } from "../../model/observation";
import {
  metricChartKey,
  metricUnitSymbol,
  OBSERVATION_METRIC_LABEL_KEY,
} from "../../presentation/observation";
import { NumberCard } from "../NumberCard";
import { Panel } from "../Panel";
import { TrendChart } from "../charts/TrendChart";
import styles from "./Observation.module.scss";

/** Keep the metric layout visible when no confirmed server sample exists; never invent zeroes. */
export function MetricUnavailableView({
  metrics = OPERATIONAL_METRICS,
}: {
  readonly metrics?: readonly (typeof METRIC_ID)[keyof typeof METRIC_ID][];
}) {
  const { t } = useTranslation();
  const unavailable = t("observation.read.noConfirmedSample");

  return (
    <section aria-label={t("observation.read.dataArea")} data-observation-state="unavailable">
      <div className={styles.cards}>
        {metrics.map((metric) => (
          <div key={metric} data-metric-card={metric} data-quality="unavailable">
            <NumberCard
              label={t(OBSERVATION_METRIC_LABEL_KEY[metric])}
              value="—"
              unit=""
              note={unavailable}
            />
          </div>
        ))}
      </div>
      <div className={styles.charts}>
        {metrics.map((metric) => (
          <Panel key={metric} title={t(OBSERVATION_METRIC_LABEL_KEY[metric])}>
            <TrendChart
              data={[]}
              metric={metricChartKey(metric)}
              unit={metricUnitSymbol(metric)}
              emptyMessage={unavailable}
              domain={METRIC_UNIT[metric] === "ratio" ? [0, 100] : undefined}
            />
          </Panel>
        ))}
      </div>
    </section>
  );
}
