/** Deterministic synthetic observations shared by HTTP tests and the opt-in MSW demo. */
import {
  METRIC_ID,
  type MetricBundle,
  type ObservationContext,
  type ObservationCoverage,
} from "../../../shared/model/observation";
import {
  metricBundleFromFacts,
  type MetricSeriesProfiles,
  type MetricFacts,
} from "../../../shared/model/metricBundleFromFacts";
import { FLEET_METRICS, type FleetQuery, type FleetSnapshot } from "../model/fleet";

type SyntheticObservations = {
  readonly rtP95Ms: number;
  readonly blockedRatio: number;
  readonly cpuRatio: number;
  readonly memoryRatio: number;
};

export type FleetObservationScenario = {
  readonly readScenarios: {
    readonly forbiddenApplicationId: string;
    readonly fleetFailure: {
      readonly applicationId: string;
      readonly failOnRead: number;
      readonly errorCode: "service_unavailable";
    };
  };
  readonly environment: { readonly id: string };
  readonly window: { readonly fromMs: number; readonly toMs: number };
  readonly metricSource: string;
  readonly inventorySource: string;
  readonly trendProfiles: MetricSeriesProfiles;
  readonly applications: readonly {
    readonly id: string;
    readonly name: string;
    readonly qps: number;
    readonly health: "attention" | "healthy";
    readonly observations: SyntheticObservations;
    readonly ruleCoverage: ObservationCoverage;
    readonly metricAnnotation?: { readonly id: string; readonly versionId: string };
  }[];
  readonly fleetObservations: SyntheticObservations;
  readonly instances: readonly {
    readonly id: string;
    readonly appId: string;
    readonly qps: number;
  }[];
  readonly connections: readonly {
    readonly id: string;
    readonly provider: "nacos" | "consul" | "collector";
    readonly state: "available" | "unavailable" | "not_configured" | "unknown";
    readonly latencyMs: number | null;
  }[];
};

function factsForApplication(
  application: FleetObservationScenario["applications"][number],
): MetricFacts {
  return {
    [METRIC_ID.HttpQps]: application.qps,
    [METRIC_ID.RtP95]: application.observations.rtP95Ms,
    [METRIC_ID.BlockedRatio]: application.observations.blockedRatio,
    [METRIC_ID.CpuRatio]: application.observations.cpuRatio,
    [METRIC_ID.MemoryRatio]: application.observations.memoryRatio,
  };
}

function factsForFleet(scenario: FleetObservationScenario): MetricFacts {
  return {
    [METRIC_ID.HttpQps]: scenario.applications.reduce(
      (sum, application) => sum + application.qps,
      0,
    ),
    [METRIC_ID.RtP95]: scenario.fleetObservations.rtP95Ms,
    [METRIC_ID.BlockedRatio]: scenario.fleetObservations.blockedRatio,
    [METRIC_ID.CpuRatio]: scenario.fleetObservations.cpuRatio,
    [METRIC_ID.MemoryRatio]: scenario.fleetObservations.memoryRatio,
  };
}

function coverageFor(
  scenario: FleetObservationScenario,
  applicationId: string | null,
): ObservationCoverage {
  const knownApplication =
    applicationId === null ||
    scenario.applications.some((application) => application.id === applicationId);
  if (!knownApplication) return { expected: null, reporting: 0, inventorySource: null };
  const instances = scenario.instances.filter(
    (instance) => applicationId === null || instance.appId === applicationId,
  );
  return {
    expected: instances.length,
    reporting: instances.length,
    inventorySource: scenario.inventorySource,
  };
}

export function bundleFor(
  context: ObservationContext,
  scenario: FleetObservationScenario,
  stepMs: number,
): MetricBundle {
  const application = scenario.applications.find((item) => item.id === context.appId);
  const knownTarget = context.appId === null || application !== undefined;
  const facts = application
    ? factsForApplication(application)
    : context.appId === null
      ? factsForFleet(scenario)
      : {};
  const applicationAnnotation = application?.metricAnnotation
    ? [
        {
          id: application.metricAnnotation.id,
          kind: "publication" as const,
          atMs:
            context.window.fromMs + Math.floor((context.window.toMs - context.window.fromMs) / 2),
          publicationId: application.metricAnnotation.id,
          versionId: application.metricAnnotation.versionId,
        },
      ]
    : [];
  return metricBundleFromFacts(
    { context, metrics: FLEET_METRICS, stepMs },
    knownTarget ? facts : {},
    coverageFor(scenario, context.appId),
    scenario.metricSource,
    applicationAnnotation,
    scenario.trendProfiles,
  );
}

export function snapshotFor(input: FleetQuery, scenario: FleetObservationScenario): FleetSnapshot {
  const metrics = bundleFor(input.context, scenario, input.stepMs);
  const scopedRows = scenario.applications.filter(
    (application) => input.context.appId === null || application.id === input.context.appId,
  );
  const rows = scopedRows.filter(
    (application) => !input.search || application.id.includes(input.search),
  );
  const attentionTargets = scopedRows
    .filter((application) => application.health === "attention")
    .map((application) => application.id);
  return {
    query: input,
    asOfMs: metrics.asOfMs,
    coverage: coverageFor(scenario, input.context.appId),
    totalApplications: scopedRows.length,
    attentionApplications: attentionTargets.length,
    attentionTargets,
    applications: {
      items: rows
        .slice((input.page - 1) * input.pageSize, input.page * input.pageSize)
        .map((application) => {
          const applicationContext = {
            ...input.context,
            appId: application.id,
            scope: "application" as const,
          };
          const instanceCoverage = coverageFor(scenario, application.id);
          return {
            appId: application.id,
            name: application.name,
            health: application.health,
            instanceCoverage,
            ruleCoverage: application.ruleCoverage,
            metrics: bundleFor(applicationContext, scenario, input.stepMs).summary,
          };
        }),
      total: rows.length,
      page: input.page,
      pageSize: input.pageSize,
    },
    metrics,
    connections: scenario.connections.map((connection) => ({
      ...connection,
      checkedAtMs: metrics.asOfMs,
    })),
  };
}
