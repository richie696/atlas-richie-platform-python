import { useTranslation } from "react-i18next";
import type { ObservationContext } from "../../model/observation";
import { OBSERVATION_SCOPE_LABEL_KEY } from "../../presentation/observation";
import { formatUtcDateTime } from "../../presentation/utcDateTime";
import styles from "./Observation.module.scss";

/** Shows the UTC-backed observation window in the configured system timezone. */
export function ObservationContextBar({
  context,
  asOfMs,
}: {
  readonly context: ObservationContext;
  readonly asOfMs?: number;
}) {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage ?? i18n.language;
  const formatRangeTime = (value: number) =>
    formatUtcDateTime(value, locale, {
      dateStyle: "short",
      timeStyle: "medium",
    });
  const formatReadTime = (value: number) =>
    formatUtcDateTime(value, locale, {
      dateStyle: "short",
      timeStyle: "medium",
    });
  return (
    <div className={styles.context} data-observation-context>
      {context.environmentId} · {context.appId ?? t("observation.allApplications")} ·{" "}
      {t(OBSERVATION_SCOPE_LABEL_KEY[context.scope])} · {formatRangeTime(context.window.fromMs)} –{" "}
      {formatRangeTime(context.window.toMs)}{" "}
      {asOfMs !== undefined && (
        <span>{t("observation.asOf", { time: formatReadTime(asOfMs) })}</span>
      )}
    </div>
  );
}
