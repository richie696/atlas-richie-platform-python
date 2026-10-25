import { Fragment, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { formatUtcDateTime } from "../../../shared/presentation/utcDateTime";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import type { QueryAccessObserver } from "../../../shared/state/ownedQueryResource";
import type { createRuleCatalogDirectory } from "../application/ruleDirectoryResources";
import type { createRuleCatalogUsageResource } from "../application/ruleObservationResources";
import type { createRuleLoadObservationResource } from "../application/ruleObservationResources";
import { createRuleDeploymentResources } from "../application/ruleDeploymentResources";
import type { RuleSetPort } from "../api/ruleSetPort";
import {
  confirmedRuleInstanceUsage,
  ruleInstanceMembership,
  ruleMemberFingerprint,
} from "../application/ruleMemberFingerprint";
import {
  bindingQueryKey,
  type RuleCatalogIssueReason,
  type RuleCatalogQuery,
} from "../model/ruleDirectory";
import type { RuleBinding } from "../model/ruleSet";
import type { RuleLoadFreshness, RuleLoadState } from "../model/ruleObservations";
import { useRuleCopy } from "../i18n/useRuleCopy";
import { Panel } from "../../../shared/ui/Panel";
import { FormGrid } from "../../../shared/ui/FormGrid";
import { Select, type SelectOption } from "../../../shared/ui/Select";
import { TextField } from "../../../shared/ui/TextField";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { DataTable } from "../../../shared/ui/DataTable";
import { RuleQueryView } from "./RuleQueryView";
import styles from "./RuleSetWorkspace.module.scss";
import { formatLocaleNumber } from "../../../shared/presentation/formatLocaleNumber";
import { RulePublicationPanel } from "./RulePublicationPanel";
import { RuleTypeOverview } from "./RuleTypeOverview";

type RuleDetailPane = "configuration" | "instances" | "effects" | "history";
const RULE_DETAIL_PANES: readonly RuleDetailPane[] = [
  "configuration",
  "instances",
  "effects",
  "history",
];

/** Rule-first catalog. Provider snapshot facts and live runtime usage stay visibly separate. */
export function RuleCatalogDirectory({
  resource,
  usageResource,
  instanceResource,
  ruleSetPort,
  readAccess,
  query,
  refreshRevision,
  environments,
  applications,
  locked = false,
  refreshing = false,
  refreshFailed = false,
  onQueryChange,
  onRefresh,
  onSelectBinding,
}: {
  readonly resource: ReturnType<typeof createRuleCatalogDirectory>;
  readonly usageResource: ReturnType<typeof createRuleCatalogUsageResource>;
  readonly instanceResource: ReturnType<typeof createRuleLoadObservationResource>;
  readonly ruleSetPort: RuleSetPort;
  readonly readAccess: QueryAccessObserver;
  readonly query: RuleCatalogQuery;
  /** Incremented only after an authoritative provider refresh has completed. */
  readonly refreshRevision: number;
  readonly environments: readonly SelectOption<string>[];
  readonly applications: readonly SelectOption<string>[];
  readonly locked?: boolean;
  readonly refreshing?: boolean;
  readonly refreshFailed?: boolean;
  readonly onQueryChange: (query: RuleCatalogQuery) => void;
  readonly onRefresh: () => void;
  readonly onSelectBinding: (binding: RuleBinding) => void;
}) {
  const { t, i18n } = useTranslation();
  const { messages } = useRuleCopy();
  const state = useExternalSnapshot(resource);
  const usageState = useExternalSnapshot(usageResource);
  const instanceState = useExternalSnapshot(instanceResource);
  const [expandedRuleKey, setExpandedRuleKey] = useState<string | null>(null);
  const [activePane, setActivePane] = useState<RuleDetailPane>("configuration");
  const [selectedPublication, setSelectedPublication] = useState<{
    readonly ruleKey: string;
    readonly id: string;
  } | null>(null);
  const [instancePage, setInstancePage] = useState(1);
  const [memberFingerprints, setMemberFingerprints] = useState<{
    readonly key: string;
    readonly values: ReadonlyMap<string, string | null>;
  } | null>(null);
  const { environmentId, appId, kind, search, page, pageSize } = query;
  const ownedQuery = useMemo(
    () => ({ environmentId, appId, kind, search, page, pageSize }),
    [environmentId, appId, kind, search, page, pageSize],
  );
  useEffect(() => {
    void resource.load(ownedQuery).catch(() => {});
    return () => resource.cancel();
  }, [resource, ownedQuery, refreshRevision]);
  const current =
    "data" in state && bindingQueryKey(state.data.query) === bindingQueryKey(ownedQuery)
      ? state.data
      : null;
  const usageQuery = useMemo(() => {
    if (!current) return null;
    return {
      environmentId,
      bindings: current.items.map((item) => ({
        bindingId: item.binding.id,
        appId: item.binding.appId,
      })),
    };
  }, [current, environmentId]);
  const fingerprintQueryKey = JSON.stringify(
    (current?.items ?? []).map((item) => [item.binding.id, item.record.id, item.snapshot.checksum]),
  );
  const expandedEntry = current?.items.find(
    (item) => `${item.binding.id}:${item.record.id}:${item.snapshot.checksum}` === expandedRuleKey,
  );
  const publicationResources = useMemo(
    () =>
      expandedEntry
        ? createRuleDeploymentResources(expandedEntry.binding, ruleSetPort, readAccess)
        : null,
    [expandedEntry, readAccess, ruleSetPort],
  );
  useEffect(() => () => publicationResources?.dispose(), [publicationResources]);
  const selectedPublicationId =
    selectedPublication?.ruleKey === expandedRuleKey ? selectedPublication.id : null;
  const instanceQuery = useMemo(
    () =>
      expandedEntry
        ? {
            environmentId: expandedEntry.binding.environmentId,
            appId: expandedEntry.binding.appId,
            bindingId: expandedEntry.binding.id,
            instanceId: null,
            page: instancePage,
            pageSize: 20,
          }
        : null,
    [expandedEntry, instancePage],
  );
  useEffect(() => {
    if (!usageQuery) {
      usageResource.cancel();
      return;
    }
    void usageResource.load(usageQuery).catch(() => undefined);
    let active = true;
    void Promise.all(
      (current?.items ?? []).map(
        async (item) =>
          [`${item.binding.id}:${item.record.id}`, await ruleMemberFingerprint(item)] as const,
      ),
    ).then((items) => {
      if (active) setMemberFingerprints({ key: fingerprintQueryKey, values: new Map(items) });
    });
    return () => {
      active = false;
      usageResource.cancel();
    };
  }, [current, fingerprintQueryKey, usageQuery, usageResource]);
  useEffect(() => {
    if (!instanceQuery) {
      instanceResource.cancel();
      return;
    }
    void instanceResource.load(instanceQuery).catch(() => undefined);
    return () => instanceResource.cancel();
  }, [instanceQuery, instanceResource]);
  const locale = i18n.resolvedLanguage ?? i18n.language;
  const number = (value: number) => formatLocaleNumber(value, locale);
  const unknown = t("rules.catalog.notReported");
  const paneLabels: Readonly<Record<RuleDetailPane, string>> = {
    configuration: t("rules.catalog.pane.configuration"),
    instances: t("rules.catalog.pane.instances"),
    effects: t("rules.catalog.pane.effects"),
    history: t("rules.catalog.pane.history"),
  };
  const issueLabels: Readonly<Record<RuleCatalogIssueReason, string>> = {
    source_unavailable: t("rules.catalog.issue.source_unavailable"),
    content_invalid: t("rules.catalog.issue.content_invalid"),
    not_read: t("rules.catalog.issue.not_read"),
  };
  const loadStateLabels: Readonly<Record<RuleLoadState, string>> = {
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
  const membershipLabels = {
    included: t("rules.catalog.membership.included"),
    not_included: t("rules.catalog.membership.not_included"),
    unknown: t("rules.catalog.membership.unknown"),
  } as const;
  return (
    <Panel
      title={t("rules.catalog.rulesTitle")}
      subtitle={t("rules.catalog.rulesDescription")}
      action={
        <ActionButton disabled={locked || refreshing} onClick={onRefresh}>
          {refreshing ? t("rules.catalog.refreshing") : t("rules.catalog.refreshRules")}
        </ActionButton>
      }
    >
      <div className={styles.content}>
        {refreshFailed && <p role="status">{t("rules.catalog.refreshFailed")}</p>}
        <FormGrid>
          <Select
            label={t("rules.directory.environment")}
            value={environmentId}
            options={environments}
            disabled={locked}
            onChange={(value) =>
              onQueryChange({ ...query, environmentId: value, appId: null, page: 1 })
            }
          />
          <Select
            label={t("rules.directory.application")}
            value={appId ?? ""}
            options={[{ value: "", label: t("rules.directory.allApplications") }, ...applications]}
            disabled={locked}
            onChange={(value) => onQueryChange({ ...query, appId: value || null, page: 1 })}
          />
          <TextField
            label={t("rules.catalog.searchRules")}
            value={search}
            disabled={locked}
            onChange={(value) => onQueryChange({ ...query, search: value, page: 1 })}
          />
        </FormGrid>
        <RuleTypeOverview
          selectedKind={kind}
          disabled={locked}
          onSelect={(nextKind) => onQueryChange({ ...query, kind: nextKind, page: 1 })}
        />
        {current && (
          <p>
            {current.coverage === "complete"
              ? t("rules.catalog.completeCoverage", {
                  bindings: number(current.bindings.total),
                  current: number(current.bindings.current),
                  stale: number(current.bindings.stale),
                  rules: number(current.total ?? 0),
                })
              : t("rules.catalog.partialCoverage", {
                  bindings: number(current.bindings.total),
                  current: number(current.bindings.current),
                  stale: number(current.bindings.stale),
                  unread: number(current.bindings.notRead),
                })}
          </p>
        )}
        <RuleQueryView
          snapshot={state}
          onRetry={() => void resource.load(ownedQuery).catch(() => {})}
          partialCopy={{
            title: t("rules.catalog.partialTitle"),
            description: t("rules.catalog.partialDescription"),
          }}
        >
          {(result) => (
            <>
              <div className={styles.ruleCatalogTable}>
                <DataTable
                  heads={[
                    t("rules.catalog.resource"),
                    t("rules.directory.kind"),
                    t("rules.catalog.threshold"),
                    t("rules.catalog.source"),
                    t("rules.catalog.ruleAttribution"),
                    t("rules.catalog.snapshot"),
                    t("rules.catalog.instances"),
                    t("rules.directory.action"),
                  ]}
                  rows={result.items.map((item) => {
                    const rule = item.record.rule.value;
                    const resourceName =
                      "resource" in rule ? rule.resource : t("rules.catalog.systemResource");
                    const threshold =
                      "count" in rule ? String(rule.count) : t("rules.catalog.systemThresholds");
                    const ruleKey = `${item.binding.id}:${item.record.id}:${item.snapshot.checksum}`;
                    const expanded = expandedRuleKey === ruleKey;
                    return (
                      <Fragment key={ruleKey}>
                        <tr key={ruleKey}>
                          <td>
                            {resourceName}
                            <br />
                            <small>{item.binding.appId}</small>
                          </td>
                          <td>{messages.types[item.record.rule.kind].label}</td>
                          <td>{threshold}</td>
                          <td>
                            {item.binding.sourceLabel}
                            <br />
                            <small>{item.binding.location}</small>
                          </td>
                          <td>{t("rules.catalog.ruleAttributionUnavailable")}</td>
                          <td>
                            {item.read.freshness === "current"
                              ? t("rules.catalog.current")
                              : t("rules.catalog.stale")}
                            <br />
                            <small>
                              {formatUtcDateTime(Date.parse(item.snapshot.asOf), locale)}
                            </small>
                          </td>
                          <td>
                            {(() => {
                              const digest =
                                memberFingerprints?.key === fingerprintQueryKey
                                  ? memberFingerprints.values.get(
                                      `${item.binding.id}:${item.record.id}`,
                                    )
                                  : undefined;
                              const page =
                                "data" in usageState &&
                                usageState.data.query.environmentId === environmentId &&
                                usageState.data.query.bindings.some(
                                  (binding) => binding.bindingId === item.binding.id,
                                )
                                  ? usageState.data.bindings[item.binding.id]
                                  : undefined;
                              const usage = confirmedRuleInstanceUsage(item, digest, page);
                              if (!usage) return unknown;
                              const usageDetail = t("rules.catalog.instanceUsage", {
                                loaded: number(usage.loaded),
                                expected: number(usage.expected),
                                notIncluded: number(usage.notIncluded),
                                unconfirmed: number(usage.unconfirmed),
                              });
                              return (
                                <ActionButton
                                  data-rule-loaded-count={ruleKey}
                                  aria-label={usageDetail}
                                  title={usageDetail}
                                  onClick={() => {
                                    setInstancePage(1);
                                    setExpandedRuleKey(ruleKey);
                                    setActivePane("instances");
                                  }}
                                >
                                  {t("rules.catalog.instanceUsageCompact", {
                                    loaded: number(usage.loaded),
                                    expected: number(usage.expected),
                                  })}
                                </ActionButton>
                              );
                            })()}
                          </td>
                          <td>
                            <div className={styles.ruleRowActions}>
                              <ActionButton
                                aria-expanded={expanded}
                                aria-controls={`rule-detail-${encodeURIComponent(ruleKey)}`}
                                data-rule-usage-toggle={ruleKey}
                                onClick={() => {
                                  setInstancePage(1);
                                  setExpandedRuleKey(expanded ? null : ruleKey);
                                  setActivePane("configuration");
                                }}
                              >
                                {expanded
                                  ? t("rules.catalog.hideDetails")
                                  : t("rules.catalog.showDetails")}
                              </ActionButton>
                              <ActionButton
                                data-rule-binding-open={item.binding.id}
                                disabled={locked}
                                onClick={() => onSelectBinding(item.binding)}
                              >
                                {t("rules.directory.open")}
                              </ActionButton>
                            </div>
                          </td>
                        </tr>
                        {expanded && (
                          <tr key={`${ruleKey}:instances`}>
                            <td colSpan={8}>
                              <section
                                id={`rule-detail-${encodeURIComponent(ruleKey)}`}
                                className={styles.ruleInstanceDetails}
                                aria-label={t("rules.catalog.detailTitle", {
                                  resource: resourceName,
                                })}
                              >
                                <h3>
                                  {t("rules.catalog.detailTitle", { resource: resourceName })}
                                </h3>
                                <div
                                  className={styles.ruleDetailTabs}
                                  role="tablist"
                                  aria-label={t("rules.catalog.detailPanes")}
                                >
                                  {RULE_DETAIL_PANES.map((pane, index) => {
                                    const encoded = encodeURIComponent(ruleKey);
                                    const tabId = `rule-tab-${encoded}-${pane}`;
                                    const nextIndex = (index + 1) % RULE_DETAIL_PANES.length;
                                    return (
                                      <button
                                        key={pane}
                                        type="button"
                                        role="tab"
                                        id={tabId}
                                        aria-selected={activePane === pane}
                                        aria-controls={`rule-detail-panel-${encoded}`}
                                        tabIndex={activePane === pane ? 0 : -1}
                                        data-rule-detail-pane={pane}
                                        onKeyDown={(event) => {
                                          const destination =
                                            event.key === "ArrowRight"
                                              ? nextIndex
                                              : event.key === "ArrowLeft"
                                                ? (index + RULE_DETAIL_PANES.length - 1) %
                                                  RULE_DETAIL_PANES.length
                                                : event.key === "Home"
                                                  ? 0
                                                  : event.key === "End"
                                                    ? RULE_DETAIL_PANES.length - 1
                                                    : -1;
                                          if (destination >= 0) {
                                            event.preventDefault();
                                            const target = RULE_DETAIL_PANES[destination]!;
                                            setActivePane(target);
                                            document
                                              .getElementById(`rule-tab-${encoded}-${target}`)
                                              ?.focus();
                                          }
                                        }}
                                        onClick={() => setActivePane(pane)}
                                      >
                                        {paneLabels[pane]}
                                      </button>
                                    );
                                  })}
                                </div>
                                <section
                                  id={`rule-detail-panel-${encodeURIComponent(ruleKey)}`}
                                  role="tabpanel"
                                  aria-labelledby={`rule-tab-${encodeURIComponent(ruleKey)}-${activePane}`}
                                  tabIndex={0}
                                  data-rule-detail-panel={activePane}
                                >
                                  {activePane === "configuration" && (
                                    <RuleConfigurationPane
                                      item={item}
                                      resourceName={resourceName}
                                    />
                                  )}
                                  {activePane === "effects" && (
                                    <p role="status">{t("rules.catalog.ruleEffectUnavailable")}</p>
                                  )}
                                  {activePane === "history" && publicationResources && (
                                    <RulePublicationHistoryPane
                                      resources={publicationResources}
                                      bindingId={item.binding.id}
                                      selectedId={selectedPublicationId}
                                      onSelect={(id) => setSelectedPublication({ ruleKey, id })}
                                    />
                                  )}
                                  {activePane === "instances" &&
                                    (() => {
                                      const digest =
                                        memberFingerprints?.key === fingerprintQueryKey
                                          ? memberFingerprints.values.get(
                                              `${item.binding.id}:${item.record.id}`,
                                            )
                                          : undefined;
                                      const page =
                                        "data" in instanceState &&
                                        instanceQuery &&
                                        JSON.stringify(instanceState.data.query) ===
                                          JSON.stringify(instanceQuery)
                                          ? instanceState.data
                                          : undefined;
                                      const details = ruleInstanceMembership(item, digest, page);
                                      if (!page || !details) {
                                        const failed = instanceState.status === "error";
                                        return (
                                          <div className={styles.actions}>
                                            <p role="status">
                                              {failed
                                                ? t("rules.catalog.instanceDetailsReadFailed")
                                                : t("rules.catalog.instanceDetailsLoading")}
                                            </p>
                                            {failed && instanceQuery && (
                                              <ActionButton
                                                onClick={() =>
                                                  void instanceResource
                                                    .load(instanceQuery)
                                                    .catch(() => undefined)
                                                }
                                              >
                                                {t("rules.catalog.instanceDetailsRetry")}
                                              </ActionButton>
                                            )}
                                          </div>
                                        );
                                      }
                                      const coverageComplete =
                                        page.coverage === "complete" &&
                                        page.targets.expected !== null;
                                      return (
                                        <>
                                          <p role="status">
                                            {coverageComplete
                                              ? t("rules.catalog.instanceDetailsCoverage", {
                                                  expected: number(page.targets.expected ?? 0),
                                                })
                                              : t("rules.catalog.instanceDetailsPartial", {
                                                  observed: number(details.length),
                                                })}
                                          </p>
                                          {details.length === 0 ? (
                                            <p>
                                              {coverageComplete && page.targets.expected === 0
                                                ? t("rules.catalog.noRegisteredInstances")
                                                : t("rules.catalog.noObservedInstances")}
                                            </p>
                                          ) : (
                                            <DataTable
                                              heads={[
                                                t("rules.observations.instance"),
                                                t("rules.observations.processEpoch"),
                                                t("rules.observations.loadState"),
                                                t("rules.observations.freshness"),
                                                t("rules.catalog.ruleMembership"),
                                                t("rules.observations.activeSnapshot"),
                                                t("rules.observations.observedAt"),
                                                t("rules.observations.receivedAt"),
                                              ]}
                                              rows={details.map(({ observation, membership }) => (
                                                <tr
                                                  key={`${observation.instanceId}:${observation.processEpoch ?? "unknown"}`}
                                                >
                                                  <td>
                                                    {observation.instanceId}
                                                    <br />
                                                    <small>{observation.processId}</small>
                                                  </td>
                                                  <td>
                                                    {observation.processEpoch ? (
                                                      <code>{observation.processEpoch}</code>
                                                    ) : (
                                                      t("rules.observations.unknown")
                                                    )}
                                                  </td>
                                                  <td>{loadStateLabels[observation.loadState]}</td>
                                                  <td>{freshnessLabels[observation.freshness]}</td>
                                                  <td>{membershipLabels[membership]}</td>
                                                  <td>
                                                    {observation.activeSnapshot ? (
                                                      <>
                                                        <code>
                                                          {observation.activeSnapshot
                                                            .sourceRevision ??
                                                            t("rules.observations.unknown")}
                                                        </code>
                                                        <br />
                                                        <small>
                                                          {
                                                            observation.activeSnapshot
                                                              .canonicalRulesSha256
                                                          }
                                                        </small>
                                                        <br />
                                                        <small>
                                                          {observation.activeSnapshot
                                                            .membershipComplete
                                                            ? t(
                                                                "rules.observations.membershipComplete",
                                                              )
                                                            : t(
                                                                "rules.observations.membershipUnknown",
                                                              )}
                                                        </small>
                                                      </>
                                                    ) : (
                                                      t("rules.observations.unknown")
                                                    )}
                                                  </td>
                                                  <td>
                                                    {observation.observedAt
                                                      ? formatUtcDateTime(
                                                          Date.parse(observation.observedAt),
                                                          locale,
                                                        )
                                                      : t("rules.observations.notReceived")}
                                                  </td>
                                                  <td>
                                                    {observation.receivedAt
                                                      ? formatUtcDateTime(
                                                          Date.parse(observation.receivedAt),
                                                          locale,
                                                        )
                                                      : t("rules.observations.notReceived")}
                                                  </td>
                                                </tr>
                                              ))}
                                            />
                                          )}
                                          <div className={styles.actions}>
                                            <ActionButton
                                              disabled={instancePage <= 1}
                                              data-instance-page-prev
                                              onClick={() => setInstancePage((value) => value - 1)}
                                            >
                                              {t("rules.catalog.previousInstances")}
                                            </ActionButton>
                                            <span>
                                              {t("rules.catalog.instancePage", {
                                                page: number(instancePage),
                                              })}
                                            </span>
                                            <ActionButton
                                              disabled={!page.hasMore}
                                              data-instance-page-next
                                              onClick={() => setInstancePage((value) => value + 1)}
                                            >
                                              {t("rules.catalog.nextInstances")}
                                            </ActionButton>
                                          </div>
                                        </>
                                      );
                                    })()}
                                </section>
                              </section>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                />
              </div>
              {result.issues.length > 0 && (
                <section aria-label={t("rules.catalog.issuesTitle")}>
                  <h3>{t("rules.catalog.issuesTitle")}</h3>
                  <DataTable
                    heads={[
                      t("rules.directory.application"),
                      t("rules.catalog.source"),
                      t("rules.catalog.readStatus"),
                    ]}
                    rows={result.issues.map((issue) => (
                      <tr key={issue.binding.id}>
                        <td>{issue.binding.appId}</td>
                        <td>{issue.binding.sourceLabel}</td>
                        <td>{issueLabels[issue.reason]}</td>
                      </tr>
                    ))}
                  />
                </section>
              )}
              <div className={styles.actions}>
                <ActionButton
                  disabled={locked || page <= 1}
                  onClick={() => onQueryChange({ ...query, page: page - 1 })}
                >
                  {t("rules.catalog.previousInstances")}
                </ActionButton>
                <span>
                  {result.total === null
                    ? t("rules.catalog.pageUnknown", {
                        page: number(page),
                        shown: number(result.items.length),
                      })
                    : t("rules.catalog.page", {
                        page: number(page),
                        total: number(result.total),
                        shown: number(result.items.length),
                      })}
                </span>
                <ActionButton
                  disabled={locked || !result.hasMore}
                  onClick={() => onQueryChange({ ...query, page: page + 1 })}
                >
                  {t("rules.catalog.nextInstances")}
                </ActionButton>
              </div>
            </>
          )}
        </RuleQueryView>
      </div>
    </Panel>
  );
}

function RuleConfigurationPane({
  item,
  resourceName,
}: {
  readonly item: import("../model/ruleDirectory").RuleCatalogPage["items"][number];
  readonly resourceName: string;
}) {
  const { t } = useTranslation();
  return (
    <div className={styles.ruleDetailContent} data-rule-configuration>
      <dl className={styles.facts}>
        <div>
          <dt>{t("rules.catalog.resource")}</dt>
          <dd>{resourceName}</dd>
        </div>
        <div>
          <dt>{t("rules.catalog.source")}</dt>
          <dd>
            {item.binding.sourceLabel} · {item.binding.location}
          </dd>
        </div>
        <div>
          <dt>{t("rules.catalog.snapshot")}</dt>
          <dd>{item.snapshot.sourceRevision ?? t("rules.catalog.notReported")}</dd>
        </div>
        <div>
          <dt>{t("rules.catalog.snapshotChecksum")}</dt>
          <dd>
            <code>{item.snapshot.checksum}</code>
          </dd>
        </div>
        <div>
          <dt>{t("rules.catalog.snapshotFreshness")}</dt>
          <dd>
            {t(item.read.freshness === "current" ? "rules.catalog.current" : "rules.catalog.stale")}
          </dd>
        </div>
      </dl>
      <pre>{JSON.stringify(item.record.rule.value, null, 2)}</pre>
    </div>
  );
}

function RulePublicationHistoryPane({
  resources,
  bindingId,
  selectedId,
  onSelect,
}: {
  readonly resources: ReturnType<typeof createRuleDeploymentResources>;
  readonly bindingId: string;
  readonly selectedId: string | null;
  readonly onSelect: (id: string) => void;
}) {
  const publications = useExternalSnapshot(resources.publications);
  const publication = useExternalSnapshot(resources.publication);
  const receipts = useExternalSnapshot(resources.receipts);
  const { t } = useTranslation();
  useEffect(() => {
    void resources.publications.load(bindingId).catch(() => undefined);
  }, [bindingId, resources]);
  const select = (id: string) => {
    onSelect(id);
    void resources.publication.load(id).catch(() => undefined);
  };
  const readReceipts = (page: number) => {
    const selected = "data" in publication ? publication.data : null;
    if (selected)
      void resources.receipts
        .load({ publication: selected, page, pageSize: 20 })
        .catch(() => undefined);
  };
  return (
    <div className={styles.ruleDetailContent} data-rule-publication-history>
      <p role="note">{t("rules.catalog.historyBindingScope")}</p>
      <RulePublicationPanel
        publications={publications}
        publication={publication}
        receipts={receipts}
        selectedId={selectedId}
        onSelect={select}
        onRead={() => void resources.publications.load(bindingId).catch(() => undefined)}
        onReadReceipts={readReceipts}
      />
    </div>
  );
}
