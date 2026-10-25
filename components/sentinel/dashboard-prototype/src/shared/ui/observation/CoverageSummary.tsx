import { useTranslation } from "react-i18next";
import type { ObservationCoverage } from "../../model/observation";
import { formatLocaleNumber } from "../../presentation/formatLocaleNumber";

/** Present the reported cohort without inventing an unknown population denominator. */
export function CoverageSummary({ coverage }: { readonly coverage: ObservationCoverage }) {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage ?? i18n.language;
  return (
    <>
      {coverage.expected === null
        ? t("observation.coverageUnknown", {
            reporting: formatLocaleNumber(coverage.reporting, locale),
          })
        : t("observation.coverage", {
            reporting: formatLocaleNumber(coverage.reporting, locale),
            expected: formatLocaleNumber(coverage.expected, locale),
          })}
      {coverage.inventorySource !== null && (
        <>
          <br />
          {t("observation.inventorySource", { source: coverage.inventorySource })}
        </>
      )}
    </>
  );
}
