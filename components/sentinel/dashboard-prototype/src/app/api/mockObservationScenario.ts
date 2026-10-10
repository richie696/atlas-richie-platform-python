import { MOCK_SYSTEM_SCENARIO } from "./mockSystemScenario";
import { METRIC_ID } from "../../shared/model/observation";
import { INSTANCE_LAYER } from "../../features/applications/model";

/** Canonical demo facts shared by HTTP handlers; never imported by feature source. */
const APPLICATIONS = Object.freeze([
  Object.freeze({
    id: MOCK_SYSTEM_SCENARIO.applicationId,
    name: MOCK_SYSTEM_SCENARIO.applicationId,
    health: "attention" as const,
    observations: Object.freeze({
      rtP95Ms: 74,
      blockedRatio: 0.08,
      cpuRatio: 0.54,
      memoryRatio: 0.52,
    }),
    metricAnnotation: Object.freeze({ id: "demo-publication-one", versionId: "demo-version-two" }),
  }),
  Object.freeze({
    id: "app-two",
    name: "app-two",
    health: "healthy" as const,
    observations: Object.freeze({
      rtP95Ms: 58,
      blockedRatio: 0.03,
      cpuRatio: 0.43,
      memoryRatio: 0.49,
    }),
  }),
  Object.freeze({
    id: "app-three",
    name: "app-three",
    health: "healthy" as const,
    observations: Object.freeze({
      rtP95Ms: 46,
      blockedRatio: 0.01,
      cpuRatio: 0.39,
      memoryRatio: 0.47,
    }),
  }),
]);

const INSTANCES = Object.freeze([
  Object.freeze({
    index: 1,
    id: "instance-1",
    appId: MOCK_SYSTEM_SCENARIO.applicationId,
    hostId: "host-one",
    containerId: "container-1",
    processId: "pid-1",
    processEpoch: "incarnation-1",
    supportedScopes: Object.freeze([INSTANCE_LAYER.Process]),
    lastReportOffsetMs: 120_000,
    health: "healthy" as const,
    qps: 22,
    observations: Object.freeze({
      rtP95Ms: 68,
      blockedRatio: 0.07,
      cpuRatio: 0.52,
      memoryRatio: 0.5,
    }),
  }),
  Object.freeze({
    index: 2,
    id: "instance-2",
    appId: MOCK_SYSTEM_SCENARIO.applicationId,
    hostId: "host-one",
    containerId: "container-2",
    processId: "pid-2",
    processEpoch: "incarnation-2",
    supportedScopes: Object.freeze([INSTANCE_LAYER.Process]),
    lastReportOffsetMs: 120_000,
    health: "attention" as const,
    qps: 20,
    observations: Object.freeze({
      rtP95Ms: 81,
      blockedRatio: 0.09,
      cpuRatio: 0.56,
      memoryRatio: 0.54,
    }),
  }),
  Object.freeze({
    index: 3,
    id: "instance-3",
    appId: "app-two",
    hostId: "host-two",
    containerId: "container-3",
    processId: "pid-3",
    processEpoch: "incarnation-3",
    supportedScopes: Object.freeze([INSTANCE_LAYER.Process]),
    lastReportOffsetMs: 120_000,
    health: "healthy" as const,
    qps: 84,
    observations: Object.freeze({
      rtP95Ms: 58,
      blockedRatio: 0.03,
      cpuRatio: 0.43,
      memoryRatio: 0.49,
    }),
  }),
  Object.freeze({
    index: 4,
    id: "instance-4",
    appId: "app-three",
    hostId: "host-three",
    containerId: "container-4",
    processId: "pid-4",
    processEpoch: "incarnation-4",
    supportedScopes: Object.freeze([INSTANCE_LAYER.Process]),
    lastReportOffsetMs: 120_000,
    health: "healthy" as const,
    qps: 63,
    observations: Object.freeze({
      rtP95Ms: 46,
      blockedRatio: 0.01,
      cpuRatio: 0.39,
      memoryRatio: 0.47,
    }),
  }),
]);

const applications = Object.freeze(
  APPLICATIONS.map((application) =>
    Object.freeze({
      ...application,
      qps: INSTANCES.filter((instance) => instance.appId === application.id).reduce(
        (total, instance) => total + instance.qps,
        0,
      ),
    }),
  ),
);

const primaryConnection = MOCK_SYSTEM_SCENARIO.connections.find(
  (connection) => connection.sourceRef === "primary",
);
if (!primaryConnection || !MOCK_SYSTEM_SCENARIO.primarySource.provider)
  throw new Error("The demo fleet scenario requires a configured primary source");
const fleetConnectionState = primaryConnection.state;

export const MOCK_OBSERVATION_SCENARIO = Object.freeze({
  readScenarios: Object.freeze({
    forbiddenApplicationId: "mock-forbidden-application",
    fleetFailure: Object.freeze({
      applicationId: "mock-recovering-application",
      failOnRead: 1,
      errorCode: "service_unavailable" as const,
    }),
    metricFailures: Object.freeze({
      recovering: Object.freeze({
        applicationId: "app-two",
        failOnRead: 3,
        errorCode: "service_unavailable" as const,
      }),
      retryable: Object.freeze({
        applicationId: "app-three",
        failOnRead: 1,
        errorCode: "service_unavailable" as const,
      }),
    }),
    networkFailure: Object.freeze({
      applicationId: "app-three",
      afterSuccessfulReads: 2,
    }),
  }),
  environment: Object.freeze({
    id: MOCK_SYSTEM_SCENARIO.environmentId,
    name: "演示环境",
  }),
  window: Object.freeze({
    fromMs: Date.parse("2026-10-06T23:55:00Z"),
    toMs: Date.parse("2026-10-07T00:10:00Z"),
  }),
  metricSource: "synthetic-console",
  inventorySource: "synthetic-inventory",
  applications,
  fleetObservations: Object.freeze({
    rtP95Ms: 63,
    blockedRatio: 0.04,
    cpuRatio: 0.49,
    memoryRatio: 0.5,
  }),
  trendProfiles: Object.freeze({
    [METRIC_ID.HttpQps]: Object.freeze([
      0.97, 1.03, 1.01, 0.94, 0.9, 0.95, 1.06, 1.04, 0.99, 0.93, 1.02, 1.08, 1,
    ]),
    [METRIC_ID.RtP95]: Object.freeze([
      0.94, 0.98, 1.06, 1.14, 1.02, 0.92, 1.01, 1.17, 1.08, 0.97, 1.04, 1.1, 1,
    ]),
    [METRIC_ID.BlockedRatio]: Object.freeze([
      0.88, 0.97, 1.1, 1.02, 0.9, 1.12, 1.05, 0.95, 1.14, 1, 0.91, 1.08, 1,
    ]),
    [METRIC_ID.CpuRatio]: Object.freeze([
      0.93, 0.97, 1.03, 1.05, 0.98, 0.92, 0.99, 1.08, 1.04, 0.96, 0.95, 1.02, 1,
    ]),
    [METRIC_ID.MemoryRatio]: Object.freeze([
      0.98, 0.99, 1, 1.01, 1, 1.02, 1.03, 1.01, 1.04, 1.03, 1.04, 1.05, 1,
    ]),
  }),
  instances: INSTANCES,
  connections: Object.freeze([
    Object.freeze({
      id: MOCK_SYSTEM_SCENARIO.primarySource.id,
      provider: MOCK_SYSTEM_SCENARIO.primarySource.provider,
      state: fleetConnectionState,
      latencyMs: primaryConnection.latencyMs,
    }),
  ]),
});

export type MockObservationScenario = typeof MOCK_OBSERVATION_SCENARIO;
