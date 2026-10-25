/** Synthetic Console metrics for tests and explicit MSW demo mode only. */
import {
  METRIC_ID,
  type MetricQuery,
  type ObservationCoverage,
} from "../../../shared/model/observation";
import {
  metricBundleFromFacts,
  type MetricSeriesProfiles,
  type MetricFacts,
} from "../../../shared/model/metricBundleFromFacts";

export type RealtimeObservationScenario = {
  readonly readScenarios: {
    readonly metricFailures: {
      readonly recovering: {
        readonly applicationId: string;
        readonly failOnRead: number;
        readonly errorCode: "service_unavailable";
      };
      readonly retryable: {
        readonly applicationId: string;
        readonly failOnRead: number;
        readonly errorCode: "service_unavailable";
      };
    };
    readonly networkFailure: {
      readonly applicationId: string;
      /** Inject one transport failure only after this many valid responses were produced. */
      readonly afterSuccessfulReads: number;
    };
  };
  readonly environment: { readonly id: string };
  readonly metricSource: string;
  readonly inventorySource: string;
  readonly trendProfiles: MetricSeriesProfiles;
  readonly applications: readonly {
    readonly id: string;
    readonly qps: number;
    readonly observations: {
      readonly rtP95Ms: number;
      readonly blockedRatio: number;
      readonly cpuRatio: number;
      readonly memoryRatio: number;
    };
    readonly metricAnnotation?: { readonly id: string; readonly versionId: string };
  }[];
  readonly fleetObservations: {
    readonly rtP95Ms: number;
    readonly blockedRatio: number;
    readonly cpuRatio: number;
    readonly memoryRatio: number;
  };
  readonly instances: readonly {
    readonly id: string;
    readonly appId: string;
    readonly qps: number;
    readonly observations: {
      readonly rtP95Ms: number;
      readonly blockedRatio: number;
      readonly cpuRatio: number;
      readonly memoryRatio: number;
    };
  }[];
};

export function metricBundleFor(query: MetricQuery, scenario: RealtimeObservationScenario) {
  const application = scenario.applications.find((item) => item.id === query.context.appId);
  const instance = scenario.instances.find(
    (item) => item.id === query.context.instanceId && item.appId === query.context.appId,
  );
  const selectedInstances = query.context.instanceId
    ? instance
      ? [instance]
      : []
    : scenario.instances.filter(
        (item) => query.context.appId === null || item.appId === query.context.appId,
      );
  const knownTarget = query.context.appId === null || application !== undefined;
  const coverage: ObservationCoverage = knownTarget
    ? {
        expected: selectedInstances.length,
        reporting: selectedInstances.length,
        inventorySource: scenario.inventorySource,
      }
    : { expected: null, reporting: 0, inventorySource: null };
  const facts: MetricFacts =
    query.context.instanceId !== null
      ? instance
        ? {
            [METRIC_ID.HttpQps]: instance.qps,
            [METRIC_ID.RtP95]: instance.observations.rtP95Ms,
            [METRIC_ID.BlockedRatio]: instance.observations.blockedRatio,
            [METRIC_ID.CpuRatio]: instance.observations.cpuRatio,
            [METRIC_ID.MemoryRatio]: instance.observations.memoryRatio,
          }
        : {}
      : application
        ? {
            [METRIC_ID.HttpQps]: application.qps,
            [METRIC_ID.RtP95]: application.observations.rtP95Ms,
            [METRIC_ID.BlockedRatio]: application.observations.blockedRatio,
            [METRIC_ID.CpuRatio]: application.observations.cpuRatio,
            [METRIC_ID.MemoryRatio]: application.observations.memoryRatio,
          }
        : query.context.appId === null
          ? {
              [METRIC_ID.HttpQps]: scenario.applications.reduce((sum, item) => sum + item.qps, 0),
              [METRIC_ID.RtP95]: scenario.fleetObservations.rtP95Ms,
              [METRIC_ID.BlockedRatio]: scenario.fleetObservations.blockedRatio,
              [METRIC_ID.CpuRatio]: scenario.fleetObservations.cpuRatio,
              [METRIC_ID.MemoryRatio]: scenario.fleetObservations.memoryRatio,
            }
          : {};
  const annotations = application?.metricAnnotation
    ? [
        {
          id: application.metricAnnotation.id,
          kind: "publication" as const,
          atMs:
            query.context.window.fromMs +
            Math.floor((query.context.window.toMs - query.context.window.fromMs) / 2),
          versionId: application.metricAnnotation.versionId,
          publicationId: application.metricAnnotation.id,
        },
      ]
    : [];
  return metricBundleFromFacts(
    query,
    facts,
    coverage,
    scenario.metricSource,
    annotations,
    scenario.trendProfiles,
  );
}
