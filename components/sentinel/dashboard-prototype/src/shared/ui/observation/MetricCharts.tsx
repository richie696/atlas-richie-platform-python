import { useTranslation } from "react-i18next";
import type { MetricBundle } from "../../model/observation";
import {
  metricPlot,
  OBSERVATION_METRIC_LABEL_KEY,
  OBSERVATION_QUALITY_LABEL_KEY,
} from "../../presentation/observation";
import { Panel } from "../Panel";
import { TrendChart } from "../charts/TrendChart";
import styles from "./Observation.module.scss";
const ANNOTATION_LABEL_KEY = Object.freeze({
  publication: "observation.annotation.publication",
  source_activation: "observation.annotation.source",
  incident: "observation.annotation.incident",
} as const);

/** Units/gaps/annotations are a pure projection of the same validated query bundle. */
export function MetricCharts({ bundle }: { readonly bundle: MetricBundle }) {
  const { t } = useTranslation();
  const annotations = bundle.annotations.map((item) => ({
    time: item.atMs,
    label: t(ANNOTATION_LABEL_KEY[item.kind]),
  }));
  return (
    <div className={styles.charts}>
      {bundle.series.map((series) => {
        const plot = metricPlot(series);
        return (
          <Panel
            key={series.metric}
            title={t(OBSERVATION_METRIC_LABEL_KEY[series.metric])}
            subtitle={`${t(OBSERVATION_QUALITY_LABEL_KEY[series.quality])} · ${series.source}`}
          >
            <TrendChart
              data={plot.points}
              metric={plot.metric}
              unit={plot.unit}
              annotations={annotations}
              timeWindow={[bundle.query.context.window.fromMs, bundle.query.context.window.toMs]}
              timeZone="UTC"
              domain={series.unit === "ratio" ? [0, 100] : undefined}
            />
          </Panel>
        );
      })}
    </div>
  );
}
