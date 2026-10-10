import type { IncidentFact } from "../model/incidentObservation";
import type { Translate } from "../../../shared/types/translation";
import { OBSERVATION_METRIC_LABEL_KEY } from "../../../shared/presentation/observation";
import { formatLocaleNumber } from "../../../shared/presentation/formatLocaleNumber";

/** Translate finite facts only. No exception text, inferred cause or protocol-localized caption. */
export function incidentFactText(fact: IncidentFact, t: Translate, locale: string): string {
  const format = (value: number) => formatLocaleNumber(value, locale, { maximumFractionDigits: 2 });
  switch (fact.code) {
    case "resource_pressure":
      return t("faults.observed.pressure", {
        metric: t(OBSERVATION_METRIC_LABEL_KEY[fact.metric]),
        value: format(fact.value * 100),
        threshold: format(fact.threshold * 100),
      });
    case "response_time":
      return t("faults.observed.responseTime", {
        value: format(fact.valueMs),
        threshold: format(fact.thresholdMs),
      });
    case "rule_published":
      return t("faults.observed.published", { version: fact.versionId });
    case "rule_applied":
      return t("faults.observed.applied", { version: fact.versionId });
  }
}
