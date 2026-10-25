import {
  OBSERVATION_SCOPE,
  OPERATIONAL_METRICS,
  isObservationTime,
  observationContextKey,
  validCoverage,
  validMetricBundle,
  validMetricQuery,
  validMetricReading,
  validObservationContext,
  type MetricBundle,
  type MetricReading,
  type ObservationContext,
  type ObservationCoverage,
} from "../../../shared/model/observation";

/** Collection layers are capabilities, not assumptions based on an instance's deployment type. */
export const INSTANCE_LAYER = Object.freeze({
  Host: OBSERVATION_SCOPE.Host,
  Container: OBSERVATION_SCOPE.Container,
  Process: OBSERVATION_SCOPE.Process,
});
export type InstanceLayer = (typeof INSTANCE_LAYER)[keyof typeof INSTANCE_LAYER];
const INSTANCE_LAYERS: readonly InstanceLayer[] = Object.freeze(Object.values(INSTANCE_LAYER));

/** Runtime guard for a collection layer received from a route or remote payload. */
export function isInstanceLayer(value: unknown): value is InstanceLayer {
  return typeof value === "string" && INSTANCE_LAYERS.some((scope) => scope === value);
}
export const INSTANCE_DETAIL_STEP_MS = 60_000;
export const MAX_INSTANCE_PAGE_SIZE = 100;
export const MAX_INSTANCE_SEARCH_LENGTH = 200;
/** Internal consumer failure code; final HTTP schema is frozen with the F6 Console contract. */
export const INSTANCE_READ_FAILURE = Object.freeze({
  IncarnationChanged: "instance_incarnation_changed",
} as const);
export const INSTANCE_HEALTH = Object.freeze({
  Healthy: "healthy",
  Attention: "attention",
  Unknown: "unknown",
} as const);
export type InstanceHealth = (typeof INSTANCE_HEALTH)[keyof typeof INSTANCE_HEALTH];
export const RULE_RECEIPT = Object.freeze({
  Applied: "applied",
  Pending: "pending",
  Failed: "failed",
  Unknown: "unknown",
} as const);
export interface InstanceIdentity {
  readonly instanceId: string;
  readonly appId: string;
  readonly environmentId: string;
  readonly hostId: string | null;
  readonly containerId: string | null;
  readonly processId: string | null;
  /** Incarnation identity, not OS pid; receipts and metric responses must match this exact process. */
  readonly processEpoch: string;
}
export interface InstanceRuleReceipt {
  readonly state: (typeof RULE_RECEIPT)[keyof typeof RULE_RECEIPT];
  readonly desiredVersionId: string | null;
  readonly appliedVersionId: string | null;
  readonly processEpoch: string;
  readonly receivedAtMs: number | null;
}
export interface ObservedInstance extends InstanceIdentity {
  readonly health: InstanceHealth;
  readonly lastReportAtMs: number | null;
  readonly supportedScopes: readonly InstanceLayer[];
  readonly ruleReceipt: InstanceRuleReceipt;
  /** Directory summaries are explicitly process-level, never presented as host/container metrics. */
  readonly processMetrics: readonly MetricReading[];
}
export interface InstanceCatalogQuery {
  readonly context: ObservationContext;
  readonly page: number;
  readonly pageSize: number;
  readonly search: string;
  readonly attentionOnly: boolean;
}
export interface InstanceCatalog {
  readonly query: InstanceCatalogQuery;
  readonly asOfMs: number;
  readonly coverage: ObservationCoverage;
  readonly totalInstances: number;
  readonly attentionInstances: number;
  readonly items: readonly ObservedInstance[];
  readonly filteredTotal: number;
}
export interface InstanceDetailQuery {
  readonly context: ObservationContext;
  readonly processEpoch: string;
  readonly stepMs: number;
}
/** Unsupported scope returns an explicit fact with no borrowed metrics. Not-found is a read error. */
export interface InstanceObservation {
  readonly query: InstanceDetailQuery;
  readonly asOfMs: number;
  readonly instance: ObservedInstance;
  readonly metrics: MetricBundle | null;
}
const identifier = (value: string) => !!value.trim();
const count = (value: number) => Number.isSafeInteger(value) && value >= 0;
export function instanceCatalogKey(query: InstanceCatalogQuery): string {
  return JSON.stringify([
    observationContextKey(query.context),
    query.page,
    query.pageSize,
    query.search,
    query.attentionOnly,
  ]);
}
export function instanceDetailKey(query: InstanceDetailQuery): string {
  return JSON.stringify([observationContextKey(query.context), query.processEpoch, query.stepMs]);
}
export function validInstanceCatalogQuery(query: InstanceCatalogQuery): boolean {
  return (
    validObservationContext(query.context) &&
    query.context.instanceId === null &&
    query.context.resource === null &&
    query.context.scope ===
      (query.context.appId === null ? OBSERVATION_SCOPE.Fleet : OBSERVATION_SCOPE.Application) &&
    count(query.page) &&
    query.page > 0 &&
    count(query.pageSize) &&
    query.pageSize > 0 &&
    query.pageSize <= MAX_INSTANCE_PAGE_SIZE &&
    query.search.length <= MAX_INSTANCE_SEARCH_LENGTH &&
    typeof query.attentionOnly === "boolean"
  );
}
export function validInstanceDetailQuery(query: InstanceDetailQuery): boolean {
  return (
    identifier(query.processEpoch) &&
    query.context.appId !== null &&
    query.context.instanceId !== null &&
    query.context.resource === null &&
    isInstanceLayer(query.context.scope) &&
    validMetricQuery({ context: query.context, metrics: OPERATIONAL_METRICS, stepMs: query.stepMs })
  );
}
export function validRuleReceipt(receipt: InstanceRuleReceipt, processEpoch: string): boolean {
  return (
    Object.values(RULE_RECEIPT).includes(receipt.state) &&
    receipt.processEpoch === processEpoch &&
    [receipt.desiredVersionId, receipt.appliedVersionId].every(
      (value) => value === null || identifier(value),
    ) &&
    (receipt.receivedAtMs === null || isObservationTime(receipt.receivedAtMs)) &&
    (receipt.state !== RULE_RECEIPT.Applied ||
      (receipt.appliedVersionId !== null &&
        receipt.appliedVersionId === receipt.desiredVersionId &&
        receipt.receivedAtMs !== null))
  );
}
export function validObservedInstance(
  instance: ObservedInstance,
  context: ObservationContext,
): boolean {
  return (
    [instance.instanceId, instance.appId, instance.environmentId, instance.processEpoch].every(
      identifier,
    ) &&
    instance.environmentId === context.environmentId &&
    (context.appId === null || instance.appId === context.appId) &&
    (context.instanceId === null || instance.instanceId === context.instanceId) &&
    [instance.hostId, instance.containerId, instance.processId].every(
      (value) => value === null || identifier(value),
    ) &&
    Object.values(INSTANCE_HEALTH).includes(instance.health) &&
    (instance.lastReportAtMs === null || isObservationTime(instance.lastReportAtMs)) &&
    new Set(instance.supportedScopes).size === instance.supportedScopes.length &&
    instance.supportedScopes.every(isInstanceLayer) &&
    (!instance.supportedScopes.includes(INSTANCE_LAYER.Host) || instance.hostId !== null) &&
    (!instance.supportedScopes.includes(INSTANCE_LAYER.Container) ||
      instance.containerId !== null) &&
    (!instance.supportedScopes.includes(INSTANCE_LAYER.Process) || instance.processId !== null) &&
    validRuleReceipt(instance.ruleReceipt, instance.processEpoch) &&
    instance.processMetrics.length === OPERATIONAL_METRICS.length &&
    new Set(instance.processMetrics.map((value) => value.metric)).size ===
      instance.processMetrics.length &&
    instance.processMetrics.every(
      (value) =>
        OPERATIONAL_METRICS.includes(value.metric) && validMetricReading(value, context.window),
    )
  );
}
/** Counters describe the complete scope, while host groups only describe the returned page. */
export function validInstanceCatalog(value: InstanceCatalog, query: InstanceCatalogQuery): boolean {
  return (
    validInstanceCatalogQuery(query) &&
    instanceCatalogKey(value.query) === instanceCatalogKey(query) &&
    isObservationTime(value.asOfMs) &&
    validCoverage(value.coverage) &&
    count(value.totalInstances) &&
    count(value.attentionInstances) &&
    value.attentionInstances <= value.totalInstances &&
    count(value.filteredTotal) &&
    value.filteredTotal <=
      (query.attentionOnly ? value.attentionInstances : value.totalInstances) &&
    ((query.page - 1) * query.pageSize < value.filteredTotal || value.items.length === 0) &&
    value.items.length <= query.pageSize &&
    value.items.length <= value.filteredTotal &&
    new Set(value.items.map((item) => JSON.stringify([item.appId, item.instanceId]))).size ===
      value.items.length &&
    value.items.every(
      (item) =>
        validObservedInstance(item, query.context) &&
        (!query.attentionOnly || item.health === INSTANCE_HEALTH.Attention),
    )
  );
}
export function validInstanceObservation(
  value: InstanceObservation,
  query: InstanceDetailQuery,
): boolean {
  if (
    !validInstanceDetailQuery(query) ||
    instanceDetailKey(value.query) !== instanceDetailKey(query) ||
    !isObservationTime(value.asOfMs) ||
    !validObservedInstance(value.instance, query.context) ||
    value.instance.processEpoch !== query.processEpoch
  )
    return false;
  const supported =
    isInstanceLayer(query.context.scope) &&
    value.instance.supportedScopes.includes(query.context.scope);
  return supported
    ? value.metrics !== null &&
        value.metrics.asOfMs === value.asOfMs &&
        validMetricBundle(value.metrics, {
          context: query.context,
          metrics: OPERATIONAL_METRICS,
          stepMs: query.stepMs,
        })
    : value.metrics === null;
}
/** Selection is independent of directory filtering/pagination; there is no first-row fallback. */
export function instanceSelection(
  instance: InstanceIdentity,
  context: ObservationContext,
  scope: InstanceLayer = INSTANCE_LAYER.Process,
): InstanceDetailQuery {
  return {
    context: {
      ...context,
      environmentId: instance.environmentId,
      appId: instance.appId,
      instanceId: instance.instanceId,
      resource: null,
      scope,
    },
    processEpoch: instance.processEpoch,
    stepMs: INSTANCE_DETAIL_STEP_MS,
  };
}
