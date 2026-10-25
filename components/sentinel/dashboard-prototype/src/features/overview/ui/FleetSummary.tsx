import { useTranslation } from "react-i18next";
import type { FleetSnapshot } from "../model/fleet";
import type { Navigate } from "../../../shared/types/navigation";
import { ROUTE } from "../../../shared/types/navigation";
import { observationNavigation } from "../../../shared/presentation/observation";
import { Panel } from "../../../shared/ui/Panel";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { MetricCards } from "../../../shared/ui/observation/MetricCards";
import { formatLocaleNumber } from "../../../shared/presentation/formatLocaleNumber";

/** Server-scope totals. A page of rows is never substituted for a fleet denominator. */
export function FleetSummary({
  snapshot,
  navigate,
}: {
  readonly snapshot: FleetSnapshot;
  readonly navigate: Navigate;
}) {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage ?? i18n.language;
  const target = snapshot.attentionTargets[0];
  return (
    <>
      <Panel
        title={t("observation.fleet.summary")}
        subtitle={t("observation.fleet.counts", {
          total: formatLocaleNumber(snapshot.totalApplications, locale),
          attention: formatLocaleNumber(snapshot.attentionApplications, locale),
        })}
        action={
          <>
            <ActionButton
              onClick={() => navigate(ROUTE.Faults, observationNavigation(snapshot.query.context))}
            >
              {t("observation.fleet.incidents")}
            </ActionButton>
            {target && (
              <ActionButton
                onClick={() =>
                  navigate(ROUTE.Applications, {
                    ...observationNavigation(snapshot.query.context),
                    appId: target,
                    metricScope: undefined,
                  })
                }
              >
                {t("observation.fleet.attention")}
              </ActionButton>
            )}
          </>
        }
      >
        <MetricCards readings={snapshot.metrics.summary} />
      </Panel>
    </>
  );
}
