import { SOURCE_CHECK_CAPABILITY } from "../../features/system/model";

const sourceCheckCapabilities = Object.freeze([
  SOURCE_CHECK_CAPABILITY.Read,
  SOURCE_CHECK_CAPABILITY.ConditionalWrite,
  SOURCE_CHECK_CAPABILITY.Watch,
]);

/** Canonical system-management facts for the explicitly enabled local Mock profile. */
export const MOCK_SYSTEM_SCENARIO = Object.freeze({
  environmentId: "test-env",
  applicationId: "app-one",
  bindingId: "binding-app-one",
  publicationId: "publication-20261007-01",
  primarySource: Object.freeze({
    id: "nacos-primary",
    revision: "source-revision-1",
    name: "Primary Nacos",
    provider: "nacos" as const,
    endpoint: "https://nacos.example.com",
    namespace: "sentinel",
    authenticationMode: "credential-reference" as const,
    credentialConfigured: true,
  }),
  sourceCheck: Object.freeze({
    unavailableHostname: "unreachable.example",
    validForMs: 30_000,
    capabilities: sourceCheckCapabilities,
  }),
  connections: Object.freeze([
    Object.freeze({
      id: "source-nacos-primary",
      kind: "config-center",
      sourceRef: "primary" as const,
      provider: "nacos",
      state: "available",
      checkedAtOffsetMs: -20_000,
      validForMs: 40_000,
      latencyMs: 12,
      capabilities: sourceCheckCapabilities,
      reason: null,
    }),
    Object.freeze({
      id: "metrics-main",
      kind: "metrics-backend",
      sourceRef: null,
      provider: null,
      state: "unconfigured",
      checkedAtOffsetMs: null,
      validForMs: null,
      latencyMs: null,
      capabilities: Object.freeze([]),
      reason: "not-configured",
    }),
    Object.freeze({
      id: "reporting-collector",
      kind: "reporting-collector",
      sourceRef: null,
      provider: null,
      state: "unknown",
      checkedAtOffsetMs: null,
      validForMs: null,
      latencyMs: null,
      capabilities: Object.freeze([]),
      reason: "no-probe",
    }),
  ]),
  protocols: Object.freeze([
    Object.freeze({
      kind: "rule-config",
      supported: Object.freeze(["rule-source-v1"]),
      active: "rule-source-v1",
      compatibility: "compatible",
      observedAtOffsetMs: -30_000,
    }),
    Object.freeze({
      kind: "agent-reporting",
      supported: Object.freeze(["agent-reporting-v1"]),
      active: null,
      compatibility: "unknown",
      observedAtOffsetMs: null,
    }),
    Object.freeze({
      kind: "cluster-token",
      supported: Object.freeze(["token-v1"]),
      active: "token-v1",
      compatibility: "compatible",
      observedAtOffsetMs: -15_000,
    }),
  ]),
  auditEvents: Object.freeze([
    Object.freeze({
      id: "audit-rule-publication",
      occurredAtOffsetMs: -60_000,
      actorRef: "administrator" as const,
      action: "rule-publish",
      targetRef: "application" as const,
      result: "success",
      requestId: "request-publication-1",
      scopeRef: "rule-publication" as const,
    }),
    Object.freeze({
      id: "audit-password-change",
      occurredAtOffsetMs: -300_000,
      actorRef: "administrator" as const,
      action: "password-change",
      targetRef: "administrator" as const,
      result: "success",
      requestId: "request-password-change-1",
      scopeRef: null,
    }),
  ]),
});

export type MockSystemScenario = typeof MOCK_SYSTEM_SCENARIO;
