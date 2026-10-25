/** Deterministic synthetic instance observations for tests and explicit MSW demo mode only. */
import {
  METRIC_ID,
  OPERATIONAL_METRICS,
  type ObservationContext,
} from "../../../shared/model/observation";
import { metricBundleFromFacts } from "../../../shared/model/metricBundleFromFacts";
import type { MetricSeriesProfiles } from "../../../shared/model/metricBundleFromFacts";
import {
  INSTANCE_LAYER,
  type InstanceLayer,
  type InstanceCatalog,
  type InstanceCatalogQuery,
  type InstanceDetailQuery,
  type InstanceObservation,
  type ObservedInstance,
} from "../model/instanceObservation";

export type InstanceObservationScenario = {
  readonly environment: { readonly id: string; readonly name: string };
  readonly window: { readonly fromMs: number; readonly toMs: number };
  readonly metricSource: string;
  readonly inventorySource: string;
  readonly trendProfiles: MetricSeriesProfiles;
  readonly applications: readonly {
    readonly id: string;
    readonly name: string;
    readonly qps: number;
    readonly observations: {
      readonly rtP95Ms: number;
      readonly blockedRatio: number;
      readonly cpuRatio: number;
      readonly memoryRatio: number;
    };
  }[];
  readonly instances: readonly {
    readonly index: number;
    readonly id: string;
    readonly appId: string;
    readonly hostId: string;
    readonly containerId: string;
    readonly processId: string;
    readonly processEpoch: string;
    readonly supportedScopes: readonly InstanceLayer[];
    readonly lastReportOffsetMs: number;
    readonly health: "healthy" | "attention";
    readonly qps: number;
    readonly ruleReceipt: {
      readonly state: "applied" | "pending" | "failed" | "unknown";
      readonly desiredVersionId: string | null;
      readonly appliedVersionId: string | null;
      readonly receivedOffsetMs: number | null;
    };
    readonly observations: {
      readonly rtP95Ms: number;
      readonly blockedRatio: number;
      readonly cpuRatio: number;
      readonly memoryRatio: number;
    };
  }[];
};

function metricBundle(
  context: ObservationContext,
  facts: {
    readonly qps: number;
    readonly observations: {
      readonly rtP95Ms: number;
      readonly blockedRatio: number;
      readonly cpuRatio: number;
      readonly memoryRatio: number;
    };
  },
  metricSource: string,
  inventorySource: string,
  stepMs = 60_000,
  profiles: MetricSeriesProfiles = {},
) {
  return metricBundleFromFacts(
    { context, metrics: OPERATIONAL_METRICS, stepMs },
    {
      [METRIC_ID.HttpQps]: facts.qps,
      [METRIC_ID.RtP95]: facts.observations.rtP95Ms,
      [METRIC_ID.BlockedRatio]: facts.observations.blockedRatio,
      [METRIC_ID.CpuRatio]: facts.observations.cpuRatio,
      [METRIC_ID.MemoryRatio]: facts.observations.memoryRatio,
    },
    { expected: 1, reporting: 1, inventorySource },
    metricSource,
    [],
    profiles,
  );
}

export function instanceFor(
  index: number,
  input: InstanceCatalogQuery,
  scenario: InstanceObservationScenario,
): ObservedInstance {
  const seed = scenario.instances.find((item) => item.index === index);
  if (!seed) throw new RangeError(`Unknown demo instance index: ${index}`);
  const appId = seed.appId;
  const application = scenario.applications.find((item) => item.id === appId);
  if (!application) throw new Error(`Demo instance references an unknown application: ${appId}`);
  const context = {
    ...input.context,
    appId,
    instanceId: seed.id,
    scope: INSTANCE_LAYER.Process,
  };
  return {
    environmentId: input.context.environmentId,
    appId,
    instanceId: seed.id,
    hostId: seed.hostId,
    containerId: seed.containerId,
    processId: seed.processId,
    processEpoch: seed.processEpoch,
    health: seed.health,
    lastReportAtMs: input.context.window.fromMs + seed.lastReportOffsetMs,
    // This seed carries process-level samples only; container/host layers must stay unavailable.
    supportedScopes: seed.supportedScopes,
    ruleReceipt: {
      state: seed.ruleReceipt.state,
      desiredVersionId: seed.ruleReceipt.desiredVersionId,
      appliedVersionId: seed.ruleReceipt.appliedVersionId,
      processEpoch: seed.processEpoch,
      receivedAtMs:
        seed.ruleReceipt.receivedOffsetMs === null
          ? null
          : input.context.window.toMs + seed.ruleReceipt.receivedOffsetMs,
    },
    processMetrics: metricBundle(
      context,
      seed,
      scenario.metricSource,
      scenario.inventorySource,
      60_000,
      scenario.trendProfiles,
    ).summary,
  };
}

export function catalogFor(
  input: InstanceCatalogQuery,
  scenario: InstanceObservationScenario,
): InstanceCatalog {
  const all = scenario.instances
    .map(({ index }) => instanceFor(index, input, scenario))
    .filter((item) => input.context.appId === null || item.appId === input.context.appId);
  const filtered = all.filter(
    (item) =>
      (!input.attentionOnly || item.health === "attention") &&
      (!input.search || item.instanceId.includes(input.search)),
  );
  return {
    query: input,
    asOfMs: input.context.window.toMs,
    totalInstances: all.length,
    attentionInstances: all.filter((item) => item.health === "attention").length,
    coverage: {
      expected: all.length,
      reporting: all.length,
      inventorySource: scenario.inventorySource,
    },
    filteredTotal: filtered.length,
    items: filtered.slice((input.page - 1) * input.pageSize, input.page * input.pageSize),
  };
}

export function detailFor(
  input: InstanceDetailQuery,
  scenario: InstanceObservationScenario,
): InstanceObservation {
  const index = Number(input.context.instanceId?.split("-").at(-1));
  const instance = instanceFor(
    index,
    { ...input, page: 1, pageSize: 1, search: "", attentionOnly: false },
    scenario,
  );
  const processSeed = scenario.instances.find((item) => item.id === instance.instanceId);
  const supportsProcess =
    input.context.scope === INSTANCE_LAYER.Process &&
    instance.supportedScopes.includes(INSTANCE_LAYER.Process);
  const metrics =
    supportsProcess && processSeed
      ? metricBundle(
          input.context,
          processSeed,
          scenario.metricSource,
          scenario.inventorySource,
          input.stepMs,
          scenario.trendProfiles,
        )
      : null;
  return { query: input, asOfMs: input.context.window.toMs, instance, metrics };
}
