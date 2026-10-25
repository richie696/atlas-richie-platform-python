import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Intro } from "../../../shared/ui/Intro";
import { MetricUnavailableView } from "../../../shared/ui/observation/MetricUnavailableView";
import { Panel } from "../../../shared/ui/Panel";

/** Keeps the overview's metric workspace visible when no authorized scope can be selected. */
export function FleetOverviewUnavailable({ children }: { readonly children?: ReactNode }) {
  const { t } = useTranslation();

  return (
    <>
      <Intro
        eyebrow="OPERATIONS / FLEET"
        title={t("overview.intro.title")}
        description={t("overview.intro.description")}
      />
      {children}
      <Panel title={t("observation.fleet.summary")}>
        <MetricUnavailableView />
      </Panel>
    </>
  );
}
