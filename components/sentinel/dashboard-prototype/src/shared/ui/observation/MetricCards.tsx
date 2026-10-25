import { useTranslation } from "react-i18next";
import type { MetricReading } from "../../model/observation";
import {
  formatMetricReading,
  metricUnitSymbol,
  OBSERVATION_METRIC_LABEL_KEY,
  OBSERVATION_QUALITY_LABEL_KEY,
  METRIC_BASIS_LABEL_KEY,
} from "../../presentation/observation";
import { NumberCard } from "../NumberCard";
import styles from "./Observation.module.scss";
import { CoverageSummary } from "./CoverageSummary";

/** Same-window server summary; never reduce table rows or draw missing samples as zero. */
export function MetricCards({ readings }: { readonly readings: readonly MetricReading[] }) {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage ?? i18n.language;
  return (
    <div className={styles.cards}>
      {readings.map((reading) => (
        <div key={reading.metric} data-metric-card={reading.metric} data-quality={reading.quality}>
          <NumberCard
            label={t(OBSERVATION_METRIC_LABEL_KEY[reading.metric])}
            value={formatMetricReading(reading, locale)}
            unit={reading.value === null ? "" : metricUnitSymbol(reading.metric)}
            note={
              <>
                {t(OBSERVATION_QUALITY_LABEL_KEY[reading.quality])} · {reading.source}
                <br />
                {t(METRIC_BASIS_LABEL_KEY[reading.denominator])} ·{" "}
                <CoverageSummary coverage={reading.coverage} />
              </>
            }
          />
        </div>
      ))}
    </div>
  );
}
