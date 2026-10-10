import { useTranslation } from "react-i18next";
import type { MetricReading } from "../../model/observation";
import {
  formatMetricReading,
  metricUnitSymbol,
  OBSERVATION_QUALITY_LABEL_KEY,
} from "../../presentation/observation";

/** Table cell: unavailable is explicit, while a measured zero remains a number. */
export function MetricValue({ reading }: { readonly reading: MetricReading }) {
  const { t, i18n } = useTranslation();
  return (
    <span
      data-metric={reading.metric}
      data-quality={reading.quality}
      title={t(OBSERVATION_QUALITY_LABEL_KEY[reading.quality])}
    >
      {formatMetricReading(reading, i18n.resolvedLanguage ?? i18n.language)}{" "}
      {reading.value === null
        ? t(OBSERVATION_QUALITY_LABEL_KEY[reading.quality])
        : metricUnitSymbol(reading.metric)}
    </span>
  );
}
