import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSession } from "../../../core/session/SessionProvider";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { FeedbackPanel } from "../../../shared/ui/FeedbackPanel";
import { Intro } from "../../../shared/ui/Intro";
import { Panel } from "../../../shared/ui/Panel";
import { Select } from "../../../shared/ui/Select";
import { TextField } from "../../../shared/ui/TextField";
import { TrendChart } from "../../../shared/ui/charts/TrendChart";
import type { Navigate } from "../../../shared/types/navigation";
import type { TranslationKey } from "../../../shared/types/translation";
import { ALL_APPLICATIONS, ROUTE } from "../../../shared/types/navigation";
import type { HostAssociation, HostAssociationPort } from "../application/hostAssociationPort";
import { HOST_METRIC_CHART_KEY, type HostMetricName } from "../presentation/hostMetricChartKey";
import { reporterFreshness, type ReporterFreshness } from "../presentation/reporterStatus";
import styles from "./HostDirectoryPage.module.scss";

type Source = {
  readonly id: string;
  readonly displayName: string;
  readonly environmentId: string;
  readonly enabled: boolean;
};
type Sample = { readonly at: string; readonly value: number };
type Metric = {
  readonly metric: HostMetricName;
  readonly unit: string;
  readonly quality: string;
  readonly samples: readonly Sample[];
};
type Host = {
  readonly hostId: string;
  readonly identity: readonly { readonly name: string; readonly value: string }[];
  readonly metrics: readonly Metric[];
};
type HostSnapshot = { readonly hosts: readonly Host[]; readonly quality: string };
type SourcePort = {
  readSources(signal: AbortSignal): Promise<{ readonly items: readonly Source[] }>;
};
type MetricsPort = {
  read(
    sourceId: string,
    query: { from: string; to: string; stepMs: number },
    signal: AbortSignal,
  ): Promise<HostSnapshot>;
};
const metricLabels: Readonly<Record<HostMetricName, TranslationKey>> = Object.freeze({
  host_cpu_busy_ratio: "observation.hostMetrics.cpuBusy",
  host_memory_used_bytes: "observation.hostMetrics.memoryUsedBytes",
  host_memory_used_ratio: "observation.hostMetrics.memoryUsedRatio",
  host_load_1m: "observation.hostMetrics.load1",
});
const reporterStatusLabels: Readonly<Record<ReporterFreshness, TranslationKey>> = Object.freeze({
  active: "applications.hosts.reporter.active",
  stale: "applications.hosts.reporter.stale",
  unknown: "applications.hosts.reporter.unknown",
  unavailable: "applications.hosts.reporter.unavailable",
});

/** Host directory is an explicit HOST-scope view, separate from process metrics and instance rows. */
export function HostDirectoryPage({
  environmentId,
  appId,
  sourcesPort,
  metricsPort,
  associationPort,
  navigate,
}: {
  readonly environmentId: string;
  readonly appId?: string;
  readonly sourcesPort: SourcePort;
  readonly metricsPort: MetricsPort;
  readonly associationPort: HostAssociationPort;
  readonly navigate: Navigate;
}) {
  const { t } = useTranslation();
  const isAdmin = useSession().roleId === "admin";
  const [sources, setSources] = useState<readonly Source[]>([]);
  const [sourceId, setSourceId] = useState("");
  const [hosts, setHosts] = useState<readonly Host[]>([]);
  const [associations, setAssociations] = useState<readonly HostAssociation[]>([]);
  const [associationTotal, setAssociationTotal] = useState(0);
  const [associatedHostIds, setAssociatedHostIds] = useState<readonly string[]>([]);
  const [hostIdsComplete, setHostIdsComplete] = useState(true);
  const [associationPageState, setAssociationPageState] = useState({ scope: "", page: 1 });
  const associationPageSize = 100;
  const [associationAsOf, setAssociationAsOf] = useState<number | null>(null);
  const [chartWindow, setChartWindow] = useState<readonly [number, number] | undefined>();
  const [selectedHostId, setSelectedHostId] = useState("");
  const [appDraft, setAppDraft] = useState(appId && appId !== ALL_APPLICATIONS ? appId : "");
  const [instanceDraft, setInstanceDraft] = useState("");
  const [status, setStatus] = useState<"loading" | "ready" | "empty" | "error">("loading");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const [associationReadError, setAssociationReadError] = useState(false);
  const [commandError, setCommandError] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const pendingRequestKeys = useRef(new Map<string, string>());
  const associationScope = JSON.stringify([environmentId, sourceId, appId ?? null]);
  const associationPage =
    associationPageState.scope === associationScope ? associationPageState.page : 1;
  const pageStatus = sourceId ? status : status === "loading" ? "loading" : "empty";

  const requestKeyFor = (intent: string) => {
    const existing = pendingRequestKeys.current.get(intent);
    if (existing) return existing;
    const requestKey = crypto.randomUUID();
    pendingRequestKeys.current.set(intent, requestKey);
    return requestKey;
  };

  useEffect(() => {
    const controller = new AbortController();
    void sourcesPort
      .readSources(controller.signal)
      .then((value) => {
        const available = value.items.filter(
          (item) => item.enabled && item.environmentId === environmentId,
        );
        setSources(available);
        setStatus("ready");
        setSourceId((current) =>
          available.some((item) => item.id === current) ? current : (available[0]?.id ?? ""),
        );
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setError(true);
          setStatus("error");
        }
      });
    return () => controller.abort();
  }, [environmentId, refreshKey, sourcesPort]);

  useEffect(() => {
    const controller = new AbortController();
    if (!sourceId) {
      return () => controller.abort();
    }
    const now = Date.now();
    const from = new Date(now - 60 * 60_000).toISOString();
    const to = new Date(now).toISOString();
    void Promise.allSettled([
      metricsPort.read(sourceId, { from, to, stepMs: 60_000 }, controller.signal),
      associationPort.read(
        environmentId,
        {
          sourceId,
          ...(appId && appId !== ALL_APPLICATIONS ? { appId } : {}),
          page: associationPage,
          pageSize: associationPageSize,
        },
        controller.signal,
      ),
    ])
      .then(([metricsResult, associationResult]) => {
        if (controller.signal.aborted) return;
        if (metricsResult.status === "rejected") {
          setError(true);
          setStatus("error");
          return;
        }
        const snapshot = metricsResult.value;
        setHosts(snapshot.hosts);
        setChartWindow([Date.parse(from), Date.parse(to)]);
        setStatus(snapshot.hosts.length ? "ready" : "empty");
        if (associationResult.status === "fulfilled") {
          const directory = associationResult.value;
          setAssociations(directory.items);
          setAssociationTotal(directory.total);
          setAssociatedHostIds(directory.associatedHostIds);
          setHostIdsComplete(directory.hostIdsComplete);
          setAssociationAsOf(Date.parse(directory.asOf));
          setAssociationReadError(false);
        } else {
          setAssociationReadError(true);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setError(true);
          setStatus("error");
        }
      });
    return () => controller.abort();
  }, [
    appId,
    associationPage,
    associationPageSize,
    associationPort,
    environmentId,
    metricsPort,
    refreshKey,
    sourceId,
  ]);

  const visibleHosts = useMemo(() => {
    if (!appId || appId === ALL_APPLICATIONS) return hosts;
    // Keep source-scoped host metrics visible during an association-store outage, but do not
    // attribute any of them to the selected application without the SQL mapping fact.
    if (associationReadError) return hosts;
    if (!hostIdsComplete) return [];
    const linked = new Set(associatedHostIds);
    return hosts.filter((host) => linked.has(host.hostId));
  }, [appId, associationReadError, associatedHostIds, hostIdsComplete, hosts]);
  // Keep a source-scoped metric preview visible, but never treat its fallback as an operator
  // selection for a write. Association commands require an explicit click on the host row.
  const selectedHost =
    visibleHosts.find((host) => host.hostId === selectedHostId) ?? visibleHosts[0] ?? null;
  const explicitHostSelected = selectedHost !== null && selectedHost.hostId === selectedHostId;
  const matchingAssociations = associationReadError
    ? []
    : associations.filter((item) => item.hostId === selectedHost?.hostId);

  const associate = async () => {
    if (
      !selectedHost ||
      !explicitHostSelected ||
      !sourceId ||
      !appDraft.trim() ||
      !instanceDraft.trim()
    )
      return;
    const controller = new AbortController();
    const app = appDraft.trim();
    const instance = instanceDraft.trim();
    const intent = JSON.stringify([
      "put",
      environmentId,
      sourceId,
      selectedHost.hostId,
      app,
      instance,
    ]);
    setBusy(true);
    setCommandError(false);
    const requestKey = requestKeyFor(intent);
    try {
      const previous = await associationPort
        .readOperation(requestKey, controller.signal)
        .catch(() => null);
      if (
        previous?.status === "completed" &&
        "hostId" in previous.result &&
        previous.result.environmentId === environmentId &&
        previous.result.sourceId === sourceId &&
        previous.result.hostId === selectedHost.hostId &&
        previous.result.appId === app &&
        previous.result.instanceId === instance
      ) {
        pendingRequestKeys.current.delete(intent);
        setInstanceDraft("");
        setRefreshKey((value) => value + 1);
        return;
      }
      const target = await associationPort.read(
        environmentId,
        { sourceId, appId: app, instanceId: instance, page: 1, pageSize: 1 },
        controller.signal,
      );
      const existing = target.items[0] ?? null;
      try {
        await associationPort.associate(
          {
            requestKey,
            environmentId,
            sourceId,
            hostId: selectedHost.hostId,
            appId: app,
            instanceId: instance,
            expectedRevision: existing?.revision ?? null,
          },
          controller.signal,
        );
      } catch (commandError) {
        const receipt = await associationPort
          .readOperation(requestKey, controller.signal)
          .catch(() => null);
        if (receipt?.status !== "completed" || !("hostId" in receipt.result)) {
          throw commandError;
        }
      }
      pendingRequestKeys.current.delete(intent);
      setInstanceDraft("");
      setRefreshKey((value) => value + 1);
      setCommandError(false);
    } catch {
      setCommandError(true);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (item: HostAssociation) => {
    const controller = new AbortController();
    const intent = JSON.stringify([
      "delete",
      environmentId,
      item.appId,
      item.instanceId,
      item.revision,
    ]);
    setBusy(true);
    setCommandError(false);
    const requestKey = requestKeyFor(intent);
    try {
      try {
        await associationPort.remove(
          {
            requestKey,
            environmentId,
            appId: item.appId,
            instanceId: item.instanceId,
            expectedRevision: item.revision,
          },
          controller.signal,
        );
      } catch (commandError) {
        const receipt = await associationPort
          .readOperation(requestKey, controller.signal)
          .catch(() => null);
        if (receipt?.status !== "completed" || !("removed" in receipt.result)) {
          throw commandError;
        }
      }
      pendingRequestKeys.current.delete(intent);
      setRefreshKey((value) => value + 1);
      setCommandError(false);
    } catch {
      setCommandError(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className={styles.page}>
      <Intro
        eyebrow="APPLICATIONS / HOSTS"
        title={t("applications.hosts.title")}
        description={t("applications.hosts.description")}
      />
      <div className={styles.tabs} role="group" aria-label={t("applications.hosts.views")}>
        <ActionButton
          variant="secondary"
          onClick={() =>
            navigate(ROUTE.Applications, { environmentId, appId: appId ?? ALL_APPLICATIONS })
          }
        >
          {t("applications.hosts.instancesTab")}
        </ActionButton>
        <ActionButton variant="primary" aria-current="page">
          {t("applications.hosts.hostsTab")}
        </ActionButton>
      </div>
      <Panel
        title={t("applications.hosts.directory")}
        subtitle={t("applications.hosts.directoryHelp")}
      >
        <div className={styles.filters}>
          <Select
            label={t("observation.hostMetrics.source")}
            value={sourceId}
            options={sources.map((source) => ({ value: source.id, label: source.displayName }))}
            onChange={(value) => {
              setStatus(value ? "loading" : "empty");
              setError(false);
              setAssociationPageState({ scope: "", page: 1 });
              setSelectedHostId("");
              setSourceId(value);
            }}
          />
          <ActionButton
            onClick={() => {
              setStatus("loading");
              setError(false);
              setRefreshKey((value) => value + 1);
            }}
            disabled={status === "loading"}
          >
            {t("observation.refresh")}
          </ActionButton>
        </div>
        {error && (
          <FeedbackPanel
            tone="error"
            copy={{
              title: t("observation.read.title"),
              description: t("observation.hostMetrics.unavailable"),
            }}
          />
        )}
        {commandError && (
          <FeedbackPanel
            tone="error"
            copy={{
              title: t("applications.hosts.commandUnconfirmed"),
              description: t("applications.hosts.commandUnconfirmedHelp"),
            }}
          />
        )}
        {pageStatus === "loading" && <p role="status">{t("observation.read.loading")}</p>}
        {pageStatus === "empty" && (
          <FeedbackPanel
            copy={{
              title: t("applications.hosts.empty"),
              description: t("applications.hosts.emptyHelp"),
            }}
          />
        )}
        {pageStatus === "ready" && (
          <div className={styles.hostGrid}>
            <p className={styles.scopeNote} role="note">
              {t("observation.hostMetrics.scopeBoundary")}
            </p>
            <div className={styles.hostList} aria-label={t("applications.hosts.directory")}>
              {visibleHosts.map((host) => (
                <button
                  type="button"
                  key={host.hostId}
                  className={host.hostId === selectedHostId ? styles.selected : styles.hostButton}
                  onClick={() => setSelectedHostId(host.hostId)}
                >
                  <span>{host.hostId}</span>
                  <small>
                    {host.identity.map((label) => `${label.name}=${label.value}`).join(" · ")}
                  </small>
                  <small>
                    {t(
                      associationReadError
                        ? "applications.hosts.hostAssociationUnknown"
                        : associatedHostIds.includes(host.hostId)
                          ? "applications.hosts.hostAssociated"
                          : hostIdsComplete
                            ? "applications.hosts.hostUnassociated"
                            : "applications.hosts.hostAssociationUnknown",
                    )}
                  </small>
                </button>
              ))}
              {visibleHosts.length === 0 && <p>{t("applications.hosts.unassociatedOnlyInAll")}</p>}
            </div>
            {selectedHost && (
              <section className={styles.detail} aria-labelledby="host-detail-title">
                <h2 id="host-detail-title">{selectedHost.hostId}</h2>
                <p>
                  {selectedHost.identity.map((label) => `${label.name}=${label.value}`).join(" · ")}
                </p>
                <div className={styles.charts}>
                  {selectedHost.metrics.map((metric) => {
                    const points = metric.samples.map((sample) => ({
                      id: sample.at,
                      timestampMs: Date.parse(sample.at),
                      [HOST_METRIC_CHART_KEY[metric.metric]]:
                        metric.unit === "ratio" ? sample.value * 100 : sample.value,
                    }));
                    return (
                      <Panel
                        key={metric.metric}
                        title={t(
                          metricLabels[metric.metric] ?? "observation.hostMetrics.unavailable",
                        )}
                        subtitle={metric.quality}
                      >
                        <TrendChart
                          data={points}
                          metric={HOST_METRIC_CHART_KEY[metric.metric]}
                          unit={metric.unit === "ratio" ? "%" : metric.unit}
                          color="primary"
                          emptyMessage={t("observation.hostMetrics.noSamples")}
                          timeWindow={chartWindow}
                        />
                      </Panel>
                    );
                  })}
                </div>
                <Panel
                  title={t("applications.hosts.associations")}
                  subtitle={t("applications.hosts.associationsHelp")}
                >
                  {associationReadError && (
                    <p role="status">{t("applications.hosts.associationReadUnavailable")}</p>
                  )}
                  {matchingAssociations.map((item) => (
                    <div className={styles.association} key={`${item.appId}:${item.instanceId}`}>
                      <span>
                        {item.appId} / {item.instanceId} ·{" "}
                        {t(
                          reporterStatusLabels[
                            reporterFreshness(item, associationAsOf ?? Number.NaN)
                          ],
                        )}
                      </span>
                      {isAdmin && (
                        <ActionButton
                          size="sm"
                          variant="secondary"
                          disabled={busy}
                          onClick={() => void remove(item)}
                        >
                          {t("applications.hosts.remove")}
                        </ActionButton>
                      )}
                    </div>
                  ))}
                  {!associationReadError && matchingAssociations.length === 0 && (
                    <p>
                      {associationTotal === 0
                        ? t("applications.hosts.noAssociations")
                        : t("applications.hosts.associationsOtherPage")}
                    </p>
                  )}
                  {!associationReadError && associationTotal > associationPageSize && (
                    <div className={styles.associationPagination}>
                      <ActionButton
                        size="sm"
                        variant="secondary"
                        disabled={busy || associationPage <= 1}
                        onClick={() =>
                          setAssociationPageState({
                            scope: associationScope,
                            page: Math.max(1, associationPage - 1),
                          })
                        }
                      >
                        {t("applications.hosts.previous")}
                      </ActionButton>
                      <span>
                        {t("applications.hosts.page", {
                          page: associationPage,
                          pages: Math.ceil(associationTotal / associationPageSize),
                          total: associationTotal,
                        })}
                      </span>
                      <ActionButton
                        size="sm"
                        variant="secondary"
                        disabled={
                          busy ||
                          associationPage >= Math.ceil(associationTotal / associationPageSize)
                        }
                        onClick={() =>
                          setAssociationPageState({
                            scope: associationScope,
                            page: associationPage + 1,
                          })
                        }
                      >
                        {t("applications.hosts.next")}
                      </ActionButton>
                    </div>
                  )}
                  {isAdmin && !explicitHostSelected && (
                    <p role="status">{t("applications.hosts.selectHost")}</p>
                  )}
                  {isAdmin && explicitHostSelected && (
                    <div className={styles.associateForm}>
                      <TextField
                        label={t("applications.hosts.appId")}
                        value={appDraft}
                        onChange={setAppDraft}
                      />
                      <TextField
                        label={t("applications.hosts.instanceId")}
                        value={instanceDraft}
                        onChange={setInstanceDraft}
                      />
                      <ActionButton
                        variant="primary"
                        disabled={busy || !instanceDraft.trim() || !appDraft.trim()}
                        onClick={() => void associate()}
                      >
                        {t("applications.hosts.associate")}
                      </ActionButton>
                    </div>
                  )}
                </Panel>
              </section>
            )}
          </div>
        )}
        {pageStatus === "ready" && appId && appId !== ALL_APPLICATIONS && !hostIdsComplete && (
          <FeedbackPanel
            tone="warning"
            copy={{
              title: t("applications.hosts.associationSummaryIncomplete"),
              description: t("applications.hosts.associationSummaryIncompleteHelp"),
            }}
          />
        )}
      </Panel>
    </main>
  );
}
