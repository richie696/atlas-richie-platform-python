import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { formatUtcDateTime } from "../../../shared/presentation/utcDateTime";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import type {
  createRuleBindingStatesResource,
  createRuleLoadObservationResource,
  createRuleLoadObservationHistoryResource,
} from "../application/ruleObservationResources";
import type {
  RuleBindingObservedState,
  RuleBindingStatesQuery,
  RuleLoadFreshness,
  RuleLoadState,
  RuleLoadObservationHistoryQuery,
} from "../model/ruleObservations";
import type { RuleBinding } from "../model/ruleSet";
import { Panel } from "../../../shared/ui/Panel";
import { DataTable } from "../../../shared/ui/DataTable";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { RuleQueryView } from "./RuleQueryView";
import styles from "./RuleSetWorkspace.module.scss";

/** Presents provider state separately from per-worker runtime application evidence. */
export function RuleRuntimeObservationPanel({
  bindingStates,
  loadObservations,
  loadObservationHistory,
  query,
  refreshRevision,
  selectedBinding,
  locked = false,
  onSelectBinding,
}: {
  readonly bindingStates: ReturnType<typeof createRuleBindingStatesResource>;
  readonly loadObservations: ReturnType<typeof createRuleLoadObservationResource>;
  readonly loadObservationHistory: ReturnType<typeof createRuleLoadObservationHistoryResource>;
  readonly query: RuleBindingStatesQuery;
  /** Re-read provider state after the rule catalog finishes an authoritative refresh. */
  readonly refreshRevision: number;
  readonly selectedBinding: RuleBinding | null;
  readonly locked?: boolean;
  readonly onSelectBinding: (binding: RuleBinding) => void;
}) {
  const { t, i18n } = useTranslation();
  const state = useExternalSnapshot(bindingStates);
  const loadState = useExternalSnapshot(loadObservations);
  const historyState = useExternalSnapshot(loadObservationHistory);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyPageNumber, setHistoryPageNumber] = useState(1);
  const { environmentId, appId, kind, page, pageSize } = query;
  const ownedQuery = useMemo(
    () => ({ environmentId, appId, kind, page, pageSize }),
    [environmentId, appId, kind, page, pageSize],
  );
  const loadQuery = useMemo(
    () =>
      selectedBinding
        ? {
            environmentId: selectedBinding.environmentId,
            appId: selectedBinding.appId,
            bindingId: selectedBinding.id,
            instanceId: null,
            page: 1,
            pageSize: 100,
          }
        : null,
    [selectedBinding],
  );
  const historyQuery = useMemo<RuleLoadObservationHistoryQuery | null>(
    () =>
      selectedBinding
        ? {
            environmentId: selectedBinding.environmentId,
            appId: selectedBinding.appId,
            bindingId: selectedBinding.id,
            instanceId: null,
            page: historyPageNumber,
            pageSize: 20,
          }
        : null,
    [selectedBinding, historyPageNumber],
  );
  useEffect(() => {
    void bindingStates.load(ownedQuery).catch(() => undefined);
    return () => bindingStates.cancel();
  }, [bindingStates, ownedQuery, refreshRevision]);
  useEffect(() => {
    if (!loadQuery) {
      loadObservations.cancel();
      return;
    }
    void loadObservations.load(loadQuery).catch(() => undefined);
    return () => loadObservations.cancel();
  }, [loadObservations, loadQuery]);
  useEffect(() => {
    if (!historyOpen || !historyQuery) {
      loadObservationHistory.cancel();
      return;
    }
    void loadObservationHistory.load(historyQuery).catch(() => undefined);
    return () => loadObservationHistory.cancel();
  }, [historyOpen, historyQuery, loadObservationHistory]);

  const bindingStatusLabels: Readonly<Record<RuleBindingObservedState, string>> = {
    current_with_rules: t("rules.observations.bindingState.current_with_rules"),
    configured_empty: t("rules.observations.bindingState.configured_empty"),
    target_missing: t("rules.observations.bindingState.target_missing"),
    content_invalid: t("rules.observations.bindingState.content_invalid"),
    unsupported_profile: t("rules.observations.bindingState.unsupported_profile"),
    source_unavailable: t("rules.observations.bindingState.source_unavailable"),
    not_read: t("rules.observations.bindingState.not_read"),
  };
  const loadStatusLabels: Readonly<Record<RuleLoadState, string>> = {
    applied: t("rules.observations.loadState.applied"),
    failed_keeps_last_known_good: t("rules.observations.loadState.failed_keeps_last_known_good"),
    failed_before_first_load: t("rules.observations.loadState.failed_before_first_load"),
    not_observed: t("rules.observations.loadState.not_observed"),
  };
  const freshnessLabels: Readonly<Record<RuleLoadFreshness, string>> = {
    current: t("rules.observations.freshness.current"),
    stale: t("rules.observations.freshness.stale"),
    unknown: t("rules.observations.freshness.unknown"),
  };
  const epochStatusLabels = {
    superseded: t("rules.observations.epoch.superseded"),
    revoked: t("rules.observations.epoch.revoked"),
    no_current_epoch: t("rules.observations.epoch.no_current_epoch"),
  } as const;
  const locale = i18n.resolvedLanguage ?? i18n.language;
  return (
    <>
      <Panel
        title={t("rules.observations.bindingTitle")}
        subtitle={t("rules.observations.bindingDescription")}
      >
        <RuleQueryView
          snapshot={state}
          onRetry={() => void bindingStates.load(ownedQuery).catch(() => undefined)}
          partialCopy={{
            title: t("rules.observations.partialTitle"),
            description: t("rules.observations.partialDescription"),
          }}
        >
          {(result) => (
            <>
              <DataTable
                heads={[
                  t("rules.directory.application"),
                  t("rules.directory.kind"),
                  t("rules.observations.providerState"),
                  t("rules.observations.ruleCount"),
                  t("rules.observations.lastAttempt"),
                  t("rules.directory.action"),
                ]}
                rows={result.items.map((item) => (
                  <tr key={item.binding.id}>
                    <td>
                      {item.binding.appId}
                      <br />
                      <small>{item.binding.sourceLabel}</small>
                    </td>
                    <td>{item.binding.kind}</td>
                    <td>
                      {bindingStatusLabels[item.state]}
                      {item.hasLastKnownGood && item.freshness === "stale" && (
                        <>
                          <br />
                          <small>{t("rules.observations.lastKnownGoodStale")}</small>
                        </>
                      )}
                    </td>
                    <td>
                      {item.ruleCount === null ? t("rules.observations.unknown") : item.ruleCount}
                    </td>
                    <td>
                      {item.lastAttemptAt
                        ? formatUtcDateTime(Date.parse(item.lastAttemptAt), locale)
                        : t("rules.observations.notRead")}
                    </td>
                    <td>
                      <ActionButton disabled={locked} onClick={() => onSelectBinding(item.binding)}>
                        {selectedBinding?.id === item.binding.id
                          ? t("rules.observations.selected")
                          : t("rules.directory.open")}
                      </ActionButton>
                    </td>
                  </tr>
                ))}
              />
              <div className={styles.actions}>
                <span>
                  {result.total === null
                    ? t("rules.observations.partialCount")
                    : t("rules.observations.bindingCount", { count: result.total })}
                </span>
              </div>
            </>
          )}
        </RuleQueryView>
      </Panel>
      {selectedBinding && (
        <Panel
          title={t("rules.observations.runtimeTitle")}
          subtitle={t("rules.observations.runtimeDescription", { binding: selectedBinding.id })}
        >
          <RuleQueryView
            snapshot={loadState}
            onRetry={() =>
              loadQuery && void loadObservations.load(loadQuery).catch(() => undefined)
            }
            partialCopy={{
              title: t("rules.observations.partialTitle"),
              description: t("rules.observations.partialDescription"),
            }}
          >
            {(result) => (
              <>
                <p>
                  {result.targets.expected === null
                    ? t("rules.observations.unknownTargets")
                    : t("rules.observations.targetCounts", {
                        expected: result.targets.expected,
                        observed: result.targets.observed ?? "—",
                        stale: result.targets.stale ?? "—",
                        notObserved: result.targets.notObserved ?? "—",
                      })}
                </p>
                <DataTable
                  heads={[
                    t("rules.observations.instance"),
                    t("rules.observations.loadState"),
                    t("rules.observations.freshness"),
                    t("rules.observations.activeSnapshot"),
                    t("rules.observations.receivedAt"),
                  ]}
                  rows={result.items.map((item) => (
                    <tr key={`${item.bindingId}:${item.instanceId}`}>
                      <td>
                        {item.instanceId}
                        <br />
                        <small>{item.processId}</small>
                      </td>
                      <td>
                        {loadStatusLabels[item.loadState]}
                        {item.eventKind && (
                          <>
                            <br />
                            <small>
                              {item.eventKind === "snapshot_applied"
                                ? t("rules.observations.eventKind.snapshot_applied")
                                : item.eventKind === "snapshot_failed"
                                  ? t("rules.observations.eventKind.snapshot_failed")
                                  : t("rules.observations.eventKind.heartbeat")}
                            </small>
                          </>
                        )}
                      </td>
                      <td>{freshnessLabels[item.freshness]}</td>
                      <td>
                        {item.activeSnapshot ? (
                          <>
                            <code>{item.activeSnapshot.canonicalRulesSha256.slice(0, 12)}</code>
                            <br />
                            <small>
                              {item.activeSnapshot.membershipComplete
                                ? t("rules.observations.membershipComplete")
                                : t("rules.observations.membershipUnknown")}
                            </small>
                          </>
                        ) : (
                          t("rules.observations.unknown")
                        )}
                      </td>
                      <td>
                        {item.receivedAt
                          ? formatUtcDateTime(Date.parse(item.receivedAt), locale)
                          : t("rules.observations.notReceived")}
                      </td>
                    </tr>
                  ))}
                />
                {result.items.length === 0 && <p>{t("rules.observations.noEnrollments")}</p>}
              </>
            )}
          </RuleQueryView>
        </Panel>
      )}
      {selectedBinding && (
        <Panel
          title={t("rules.observations.historyTitle")}
          subtitle={t("rules.observations.historyDescription")}
        >
          {!historyOpen ? (
            <ActionButton
              disabled={locked}
              onClick={() => {
                setHistoryPageNumber(1);
                setHistoryOpen(true);
              }}
            >
              {t("rules.observations.showHistory")}
            </ActionButton>
          ) : (
            <RuleQueryView
              snapshot={historyState}
              onRetry={() =>
                historyQuery &&
                void loadObservationHistory.load(historyQuery).catch(() => undefined)
              }
              partialCopy={{
                title: t("rules.observations.partialTitle"),
                description: t("rules.observations.historyPartial"),
              }}
              unavailableContent={
                <div className={styles.actions}>
                  {historyState.status === "empty" && (
                    <span>{t("rules.observations.historyEmpty")}</span>
                  )}
                  <ActionButton onClick={() => setHistoryOpen(false)}>
                    {t("rules.observations.hideHistory")}
                  </ActionButton>
                </div>
              }
            >
              {(result) => (
                <>
                  <p>{t("rules.observations.historyNotCurrent")}</p>
                  <DataTable
                    heads={[
                      t("rules.observations.instance"),
                      t("rules.observations.epochStatus"),
                      t("rules.observations.loadState"),
                      t("rules.observations.activeSnapshot"),
                      t("rules.observations.receivedAt"),
                    ]}
                    rows={result.items.map(({ observationId, epochStatus, observation }) => (
                      <tr key={observationId}>
                        <td>
                          {observation.instanceId}
                          <br />
                          <small>
                            {observation.processId} · {observation.processEpoch}
                          </small>
                        </td>
                        <td>{epochStatusLabels[epochStatus]}</td>
                        <td>{loadStatusLabels[observation.loadState]}</td>
                        <td>
                          {observation.activeSnapshot?.canonicalRulesSha256.slice(0, 12) ??
                            t("rules.observations.unknown")}
                        </td>
                        <td>
                          {observation.receivedAt
                            ? formatUtcDateTime(Date.parse(observation.receivedAt), locale)
                            : t("rules.observations.notReceived")}
                        </td>
                      </tr>
                    ))}
                  />
                  {!result.items.length && <p>{t("rules.observations.historyEmpty")}</p>}
                  <div className={styles.actions}>
                    <ActionButton
                      disabled={historyPageNumber <= 1}
                      onClick={() => setHistoryPageNumber((value) => value - 1)}
                    >
                      {t("rules.observations.historyPrevious")}
                    </ActionButton>
                    <span>
                      {t("rules.observations.historyPage", {
                        page: historyPageNumber,
                        total: result.total ?? "—",
                      })}
                    </span>
                    <ActionButton
                      disabled={!result.hasMore}
                      onClick={() => setHistoryPageNumber((value) => value + 1)}
                    >
                      {t("rules.observations.historyNext")}
                    </ActionButton>
                    <ActionButton onClick={() => setHistoryOpen(false)}>
                      {t("rules.observations.hideHistory")}
                    </ActionButton>
                  </div>
                </>
              )}
            </RuleQueryView>
          )}
        </Panel>
      )}
    </>
  );
}
