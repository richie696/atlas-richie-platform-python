import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import type {
  HostMetricsQueryResource,
  HostMetricsSourceResource,
} from "../application/hostMetricsResources";
import type { HostMetricsObservation } from "../application/hostMetricsResources";
import { hostMetricsQueryStepMs } from "../application/hostMetricsResources";
import type { RealtimeSelection } from "../model/monitoring";
import { Panel } from "../../../shared/ui/Panel";
import { Select } from "../../../shared/ui/Select";
import { FeedbackPanel } from "../../../shared/ui/FeedbackPanel";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { TrendChart } from "../../../shared/ui/charts/TrendChart";
import type { MetricKey } from "../../../shared/types/dashboard";
import type { TranslationKey } from "../../../shared/types/translation";
import styles from "./HostMetricsPanel.module.scss";

const HOST_METRIC_PRESENTATION = Object.freeze([
  {
    kind: "host_cpu_busy_ratio",
    key: "hostCpu",
    label: "observation.hostMetrics.cpuBusy",
    unit: "%",
    color: "primary",
    scaleRatio: true,
  },
  {
    kind: "host_memory_used_bytes",
    key: "hostMemoryBytes",
    label: "observation.hostMetrics.memoryUsedBytes",
    unit: "B",
    color: "secondary",
    scaleRatio: false,
  },
  {
    kind: "host_memory_used_ratio",
    key: "hostMemoryRatio",
    label: "observation.hostMetrics.memoryUsedRatio",
    unit: "%",
    color: "danger",
    scaleRatio: true,
  },
  {
    kind: "host_load_1m",
    key: "hostLoad",
    label: "observation.hostMetrics.load1",
    unit: "",
    color: "primary",
    scaleRatio: false,
  },
] as const satisfies readonly {
  kind: HostMetricsObservation["hosts"][number]["metrics"][number]["metric"];
  key: MetricKey;
  label: string;
  unit: string;
  color: "primary" | "secondary" | "danger";
  scaleRatio: boolean;
}[]);
const HOST_QUALITY_LABEL_KEY: Readonly<Record<HostMetricsObservation["quality"], TranslationKey>> =
  Object.freeze({
    available: "observation.hostMetrics.quality.available",
    partial: "observation.hostMetrics.quality.partial",
    stale: "observation.hostMetrics.quality.stale",
    no_samples: "observation.hostMetrics.quality.no_samples",
    not_integrated: "observation.hostMetrics.quality.not_integrated",
    unavailable: "observation.hostMetrics.quality.unavailable",
  });

/** HOST-scope Prometheus charts are independent from the process-level Sentinel telemetry block. */
export function HostMetricsPanel({
  environmentId,
  selection,
  sourcesResource,
  metricsResource,
  onConfigure,
}: {
  readonly environmentId: string;
  readonly selection: RealtimeSelection;
  readonly sourcesResource: HostMetricsSourceResource;
  readonly metricsResource: HostMetricsQueryResource;
  readonly onConfigure: () => void;
}) {
  const { t } = useTranslation();
  const sourceSnapshot = useExternalSnapshot(sourcesResource);
  const directoryQuery = useMemo(() => ({ environmentId }), [environmentId]);
  const directoryKey = sourcesResource.keyOf(directoryQuery);
  const sources =
    "data" in sourceSnapshot && sourceSnapshot.key === directoryKey ? sourceSnapshot.data : [];
  const [sourceChoice, setSourceChoice] = useState("");
  const source = sources.find((candidate) => candidate.id === sourceChoice) ?? sources[0] ?? null;
  const [hostChoice, setHostChoice] = useState("");
  const duration = selection.context.window.toMs - selection.context.window.fromMs;
  const stepMs = hostMetricsQueryStepMs(duration);
  const query = useMemo(
    () => ({
      sourceId: source?.id ?? "",
      window: {
        from: new Date(selection.context.window.fromMs).toISOString(),
        to: new Date(selection.context.window.toMs).toISOString(),
        stepMs,
      },
    }),
    [selection.context.window.fromMs, selection.context.window.toMs, source?.id, stepMs],
  );
  const queryKey = metricsResource.keyOf(query);
  const metricsSnapshot = useExternalSnapshot(metricsResource);
  useEffect(() => {
    void sourcesResource.load(directoryQuery).catch(() => undefined);
    return () => sourcesResource.cancel();
  }, [directoryQuery, sourcesResource]);
  useEffect(() => {
    if (!source) {
      metricsResource.cancel();
      return;
    }
    void metricsResource.load(query).catch(() => undefined);
    return () => metricsResource.cancel();
  }, [metricsResource, query, source]);

  const snapshot =
    "data" in metricsSnapshot && metricsSnapshot.key === queryKey ? metricsSnapshot.data : null;
  const host =
    snapshot?.hosts.find((candidate) => candidate.hostId === hostChoice) ??
    snapshot?.hosts[0] ??
    null;
  const error = sourceSnapshot.status === "error" || sourceSnapshot.status === "stale";
  const denied = sourceSnapshot.status === "denied";
  const metricsError = metricsSnapshot.status === "error" || metricsSnapshot.status === "stale";
  const metricsDenied = metricsSnapshot.status === "denied";

  return (
    <section className={styles.section} aria-labelledby="host-metrics-title">
      <div className={styles.heading}>
        <div>
          <h2 id="host-metrics-title">{t("observation.hostMetrics.title")}</h2>
          <p>{t("observation.hostMetrics.subtitle")}</p>
          <p className={styles.quality} role="note">
            {t("observation.hostMetrics.scopeBoundary")}
          </p>
        </div>
        {sources.length > 0 && (
          <div className={styles.filters}>
            {sources.length > 1 && (
              <Select
                label={t("observation.hostMetrics.source")}
                value={source?.id ?? ""}
                options={sources.map((item) => ({ value: item.id, label: item.displayName }))}
                onChange={setSourceChoice}
              />
            )}
            {(snapshot?.hosts.length ?? 0) > 1 && (
              <Select
                label={t("observation.hostMetrics.host")}
                value={host?.hostId ?? ""}
                options={
                  snapshot?.hosts.map((item) => ({ value: item.hostId, label: item.hostId })) ?? []
                }
                onChange={setHostChoice}
              />
            )}
          </div>
        )}
      </div>
      {error || denied ? (
        <FeedbackPanel
          tone={denied ? "warning" : "error"}
          copy={{
            title: t("observation.read.title"),
            description: t(
              denied ? "observation.read.denied" : "observation.hostMetrics.unavailable",
            ),
          }}
          actions={
            <ActionButton
              className="link-button"
              variant="ghost"
              size="sm"
              onClick={() => void sourcesResource.load(directoryQuery).catch(() => undefined)}
            >
              {t("observation.read.retry")}
            </ActionButton>
          }
        />
      ) : sourcesResource.getSnapshot().status === "loading" ||
        sourcesResource.getSnapshot().status === "idle" ? (
        <p className={styles.status} role="status">
          {t("observation.read.loading")}
        </p>
      ) : !source ? (
        <FeedbackPanel
          copy={{
            title: t("observation.hostMetrics.noSource"),
            description: t("observation.hostMetrics.noSource"),
          }}
          actions={
            <ActionButton className="link-button" variant="ghost" size="sm" onClick={onConfigure}>
              {t("observation.hostMetrics.configure")}
            </ActionButton>
          }
        />
      ) : metricsError || metricsDenied ? (
        <FeedbackPanel
          tone={metricsDenied ? "warning" : "error"}
          copy={{
            title: t("observation.read.title"),
            description: t("observation.hostMetrics.unavailable"),
          }}
          actions={
            <ActionButton
              className="link-button"
              variant="ghost"
              size="sm"
              onClick={() => void metricsResource.load(query).catch(() => undefined)}
            >
              {t("observation.read.retry")}
            </ActionButton>
          }
        />
      ) : metricsSnapshot.status === "loading" ||
        metricsSnapshot.status === "idle" ||
        metricsSnapshot.status === "refreshing" ? (
        <p className={styles.status} role="status">
          {t("observation.read.loading")}
        </p>
      ) : !snapshot || !host ? (
        <FeedbackPanel
          copy={{
            title: t("observation.hostMetrics.noSamples"),
            description: t("observation.hostMetrics.noSamples"),
          }}
        />
      ) : (
        <>
          {snapshot.quality !== "available" && (
            <p className={styles.quality} role="status">
              {t("observation.hostMetrics.quality")}: {t(HOST_QUALITY_LABEL_KEY[snapshot.quality])}
            </p>
          )}
          <HostMetricChartGrid
            host={host}
            fromMs={selection.context.window.fromMs}
            toMs={selection.context.window.toMs}
          />
        </>
      )}
      {(!source || !snapshot || !host || error || denied || metricsError || metricsDenied) && (
        <HostMetricChartGrid
          host={null}
          fromMs={selection.context.window.fromMs}
          toMs={selection.context.window.toMs}
        />
      )}
    </section>
  );
}

function HostMetricChartGrid({
  host,
  fromMs,
  toMs,
}: {
  readonly host: HostMetricsObservation["hosts"][number] | null;
  readonly fromMs: number;
  readonly toMs: number;
}) {
  const { t } = useTranslation();
  return (
    <div className={styles.charts}>
      {HOST_METRIC_PRESENTATION.map((presentation) => {
        const metric = host?.metrics.find((item) => item.metric === presentation.kind);
        const points =
          metric?.samples.map((sample) => ({
            id: sample.at,
            timestampMs: Date.parse(sample.at),
            [presentation.key]: presentation.scaleRatio ? sample.value * 100 : sample.value,
          })) ?? [];
        const unit = metric?.unit === "ratio" ? "%" : presentation.unit;
        return (
          <Panel
            key={presentation.kind}
            title={t(presentation.label)}
            subtitle={`${host?.hostId ?? t("observation.hostMetrics.host")} · ${t(HOST_QUALITY_LABEL_KEY[metric?.quality ?? "unavailable"])}`}
          >
            <TrendChart
              data={points}
              metric={presentation.key}
              unit={unit}
              color={presentation.color}
              emptyMessage={t("observation.hostMetrics.noSamples")}
              domain={metric?.unit === "ratio" ? [0, 100] : undefined}
              timeWindow={[fromMs, toMs]}
            />
          </Panel>
        );
      })}
    </div>
  );
}
