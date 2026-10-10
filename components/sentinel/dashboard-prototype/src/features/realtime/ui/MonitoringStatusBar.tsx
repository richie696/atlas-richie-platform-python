import { useTranslation } from "react-i18next";
import type { RealtimeMonitorSnapshot } from "../application/realtimeMonitor";
import { MONITOR_MODE } from "../model/monitoring";
import { ActionButton } from "../../../shared/ui/ActionButton";
import styles from "./Monitoring.module.scss";
const MODE_LABEL_KEY = Object.freeze({
  idle: "observation.monitor.idle",
  polling: "observation.monitor.polling",
  paused: "observation.monitor.paused",
  stopped: "observation.monitor.stopped",
} as const);

/** Read/pause status is independent of navigator.onLine, and doesn't claim the collector is stopped. */
export function MonitoringStatusBar({
  snapshot,
  onPause,
  onResume,
}: {
  readonly snapshot: RealtimeMonitorSnapshot;
  readonly onPause: () => void;
  readonly onResume: () => void;
}) {
  const { t } = useTranslation();
  const active = snapshot.mode === MONITOR_MODE.Polling;
  return (
    <div className={styles.status} data-monitor-status>
      <div>
        <strong>{t(MODE_LABEL_KEY[snapshot.mode])}</strong>
        <span>{t("observation.monitor.browserOnly")}</span>
      </div>
      <ActionButton
        disabled={snapshot.observation.status === "denied" || snapshot.selection === null}
        onClick={active ? onPause : onResume}
      >
        {t(active ? "observation.monitor.pause" : "observation.monitor.resume")}
      </ActionButton>
    </div>
  );
}
