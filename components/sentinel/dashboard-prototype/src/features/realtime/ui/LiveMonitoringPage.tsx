import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import { AppError, AppErrorKind } from "@richie696/react-framework";
import type { RealtimeMonitor } from "../application/realtimeMonitor";
import { realtimeReadCopy } from "../presentation/realtimeReadCopy";
import {
  realtimeSelectionKey,
  validRealtimeSelection,
  type RealtimeSelection,
} from "../model/monitoring";
import { Intro } from "../../../shared/ui/Intro";
import { FeedbackPanel } from "../../../shared/ui/FeedbackPanel";
import { ObservationContextBar } from "../../../shared/ui/observation/ObservationContextBar";
import { ObservationQueryView } from "../../../shared/ui/observation/ObservationQueryView";
import { MetricCards } from "../../../shared/ui/observation/MetricCards";
import { MetricCharts } from "../../../shared/ui/observation/MetricCharts";
import type { ObservationOption } from "../../../shared/ui/observation/ObservationFilters";
import type { ObservedInstance } from "../../applications";
import { MonitoringControls } from "./MonitoringControls";
import { MonitoringStatusBar } from "./MonitoringStatusBar";

/** Only a known access revocation is represented by the owner; don't silently mask a disposed/configuration error. */
function startMonitoring(monitor: RealtimeMonitor, selection: RealtimeSelection) {
  try {
    monitor.start(selection);
  } catch (cause) {
    if (!(cause instanceof AppError) || cause.kind !== AppErrorKind.FORBIDDEN) throw cause;
  }
}

/** Formal read-only monitor. Page composition only; timer/window/abort/cache ownership stays in the monitor. */
export function LiveMonitoringPage({
  monitor,
  selection,
  onSelectionChange,
  environments,
  applications,
  instances,
  instanceHint,
  selectedInstanceId,
  instanceCatalogLoading,
  queryReady,
  instanceTargetMissing,
  instanceTargetUnsupported,
  clock,
}: {
  readonly monitor: RealtimeMonitor;
  readonly selection: RealtimeSelection;
  readonly onSelectionChange: (selection: RealtimeSelection) => void;
  readonly environments: readonly ObservationOption[];
  readonly applications: readonly ObservationOption[];
  readonly instances: readonly ObservedInstance[];
  readonly instanceHint?: string;
  readonly selectedInstanceId: string | null;
  readonly instanceCatalogLoading: boolean;
  readonly queryReady: boolean;
  readonly instanceTargetMissing: boolean;
  readonly instanceTargetUnsupported: boolean;
  readonly clock?: () => number;
}) {
  const { t } = useTranslation();
  const snapshot = useExternalSnapshot(monitor);
  const valid = validRealtimeSelection(selection),
    key = realtimeSelectionKey(selection);
  useEffect(() => {
    if (valid && queryReady) startMonitoring(monitor, selection);
    return monitor.cancel;
  }, [monitor, queryReady, selection, valid]);
  const same = snapshot.selection !== null && realtimeSelectionKey(snapshot.selection) === key;
  const observation =
    snapshot.observation.status === "denied" || same
      ? snapshot.observation
      : { status: "loading" as const, key };
  const readCopy = realtimeReadCopy(observation);
  const readDescriptions = readCopy
    ? {
        error: readCopy.error ? t(readCopy.error) : undefined,
        stale: readCopy.stale ? t(readCopy.stale) : undefined,
      }
    : undefined;
  const retry = () => {
    monitor.cancel();
    if (queryReady) startMonitoring(monitor, selection);
  };
  if (!valid)
    return (
      <FeedbackPanel
        tone="error"
        copy={{
          title: t("observation.read.title"),
          description: t("observation.monitor.invalidQuery"),
        }}
      />
    );
  return (
    <>
      <Intro
        eyebrow="LIVE / TELEMETRY"
        title={t("realtime.intro.title")}
        description={t("realtime.intro.description")}
      />
      <MonitoringControls
        selection={selection}
        onChange={onSelectionChange}
        environments={environments}
        applications={applications}
        instances={instances}
        instanceHint={instanceHint}
        selectedInstanceId={selectedInstanceId}
        instanceCatalogLoading={instanceCatalogLoading}
        clock={clock}
      />
      <MonitoringStatusBar snapshot={snapshot} onPause={monitor.pause} onResume={monitor.resume} />
      <ObservationContextBar
        context={"data" in observation ? observation.data.query.context : selection.context}
        asOfMs={"data" in observation ? observation.data.asOfMs : undefined}
      />
      {instanceTargetMissing || instanceTargetUnsupported ? (
        <FeedbackPanel
          tone="error"
          copy={{
            title: t("observation.read.title"),
            description: t(
              instanceTargetUnsupported
                ? "observation.monitor.instanceUnsupported"
                : "observation.read.targetAbsent",
            ),
          }}
        />
      ) : queryReady ? (
        <ObservationQueryView
          snapshot={observation}
          onRetry={retry}
          descriptions={readDescriptions}
        >
          {(value) => (
            <>
              <MetricCards readings={value.summary} />
              <MetricCharts bundle={value} />
            </>
          )}
        </ObservationQueryView>
      ) : (
        <FeedbackPanel
          tone="info"
          copy={{
            title: t("observation.read.title"),
            description: t("observation.read.loading"),
          }}
        />
      )}
    </>
  );
}
