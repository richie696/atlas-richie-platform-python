import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { OBSERVATION_SCOPE, type ObservationContext } from "../../../shared/model/observation";
import type { ObservationOption } from "../../../shared/ui/observation/ObservationFilters";
import { ObservationFilters } from "../../../shared/ui/observation/ObservationFilters";
import { observationWindowFromRoute } from "../../../shared/presentation/observation";
import { Intro } from "../../../shared/ui/Intro";
import {
  ALL_APPLICATIONS,
  ROUTE,
  TIME_RANGE,
  TIME_RANGE_MS,
} from "../../../shared/types/navigation";
import type { DashboardPageProps } from "../../../shared/types/dashboard";
import styles from "./InstanceObservation.module.scss";

/** Explicit empty state for an opaque application ID absent from the authorized catalog. */
export function MissingApplicationState({
  page,
  environmentId,
  environments,
  applications,
}: {
  readonly page: DashboardPageProps & {
    readonly environmentId?: string;
    readonly from?: string;
    readonly to?: string;
  };
  readonly environmentId: string;
  readonly environments: readonly ObservationOption[];
  readonly applications: readonly ObservationOption[];
}) {
  const { t } = useTranslation();
  const [anchorMs] = useState(() => Date.now());
  const window = useMemo(
    () => observationWindowFromRoute(page.from, page.to, page.range, anchorMs),
    [anchorMs, page.from, page.range, page.to],
  );
  const missingAppId = page.appId;
  const context: ObservationContext = {
    environmentId,
    appId: missingAppId,
    instanceId: null,
    resource: null,
    scope: OBSERVATION_SCOPE.Application,
    window,
  };
  const options = applications.some((application) => application.id === missingAppId)
    ? applications
    : [...applications, { id: missingAppId, name: missingAppId }];

  return (
    <section data-applications-page data-application-not-found>
      <Intro
        eyebrow="APPLICATIONS / INSTANCES"
        title={t("applications.intro.title")}
        description={t("applications.intro.description")}
      />
      <section className={styles.filters} data-observation-filters>
        <ObservationFilters
          context={context}
          environments={environments}
          applications={options}
          allowAllApplications={false}
          onChange={(next) => {
            const duration = next.window.toMs - next.window.fromMs;
            const range =
              duration === TIME_RANGE_MS[TIME_RANGE.Last15Minutes]
                ? TIME_RANGE.Last15Minutes
                : TIME_RANGE.Last1Hour;
            page.navigate(ROUTE.Applications, {
              environmentId: next.environmentId,
              appId: next.appId ?? ALL_APPLICATIONS,
              range,
              from: new Date(next.window.fromMs).toISOString(),
              to: new Date(next.window.toMs).toISOString(),
            });
          }}
        />
      </section>
      <section className={styles.note} role="status" data-application-not-found-message>
        <p>{t("applications.empty.target")}</p>
      </section>
    </section>
  );
}
