import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { Navigate } from "../../../shared/types/navigation";
import { ALL_APPLICATIONS, ROUTE } from "../../../shared/types/navigation";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { FeedbackPanel } from "../../../shared/ui/FeedbackPanel";
import { Panel } from "../../../shared/ui/Panel";
import styles from "./HostMonitoringSummary.module.scss";

type MonitoringSource = {
  readonly id: string;
  readonly displayName: string;
  readonly environmentId: string;
  readonly enabled: boolean;
};

/** Minimal read port for the overview; source-management workflow remains owned by system/. */
export interface HostMonitoringSummarySourcePort {
  readSources(signal: AbortSignal): Promise<{ readonly items: readonly MonitoringSource[] }>;
}

/**
 * Shows only registered-source facts on the fleet overview and links to the real HOST directory.
 * It deliberately does not label a source healthy or claim samples until the HOST query is read.
 */
export function HostMonitoringSummary({
  environmentId,
  sourcePort,
  navigate,
}: {
  readonly environmentId: string;
  readonly sourcePort: HostMonitoringSummarySourcePort;
  readonly navigate: Navigate;
}) {
  const { t } = useTranslation();
  const [state, setState] = useState<
    | { readonly environmentId: string; readonly status: "loading" }
    | { readonly environmentId: string; readonly status: "ready"; readonly enabledCount: number }
    | { readonly environmentId: string; readonly status: "error" }
  >(() => ({ environmentId, status: "loading" }));

  useEffect(() => {
    const controller = new AbortController();
    void sourcePort
      .readSources(controller.signal)
      .then(({ items }) => {
        if (!controller.signal.aborted) {
          setState({
            environmentId,
            status: "ready",
            enabledCount: items.filter(
              (source) => source.enabled && source.environmentId === environmentId,
            ).length,
          });
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setState({ environmentId, status: "error" });
      });
    return () => controller.abort();
  }, [environmentId, sourcePort]);

  const currentState =
    state.environmentId === environmentId ? state : { status: "loading" as const };

  const openHostDirectory = () =>
    navigate(ROUTE.Applications, {
      environmentId,
      appId: ALL_APPLICATIONS,
      view: "hosts",
    });

  return (
    <Panel
      title={t("overview.hostMonitoring.title")}
      subtitle={t("overview.hostMonitoring.description")}
    >
      <div className={styles.summary}>
        <div className={styles.status}>
          {currentState.status === "loading" ? (
            <p role="status">{t("overview.hostMonitoring.loading")}</p>
          ) : currentState.status === "error" ? (
            <FeedbackPanel
              tone="error"
              copy={{
                title: t("overview.hostMonitoring.unavailable"),
                description: t("overview.hostMonitoring.unavailableHelp"),
              }}
            />
          ) : (
            <>
              <strong>
                {t("overview.hostMonitoring.sourceCount")}: {currentState.enabledCount}
              </strong>
              <p>
                {currentState.enabledCount > 0
                  ? t("overview.hostMonitoring.configured")
                  : t("overview.hostMonitoring.notConfigured")}
              </p>
            </>
          )}
        </div>
        <div className={styles.actions}>
          <ActionButton variant="secondary" onClick={() => navigate(ROUTE.System)}>
            {t("overview.hostMonitoring.configure")}
          </ActionButton>
          <ActionButton onClick={openHostDirectory}>
            {t("overview.hostMonitoring.openDirectory")}
          </ActionButton>
        </div>
      </div>
    </Panel>
  );
}
