import {
  INCIDENT_CATEGORY,
  INCIDENT_FACT_CODE,
  INCIDENT_SEVERITY,
} from "../../features/faults/mock";
import type { IncidentObservationScenario } from "../../features/faults/mock";
import { METRIC_ID } from "../../shared/model/observation";
import { MOCK_OBSERVATION_SCENARIO } from "./mockObservationScenario";
import { MOCK_RULE_SCENARIO } from "./mockRuleScenario";
import { MOCK_SYSTEM_SCENARIO } from "./mockSystemScenario";

/** Canonical immutable incident and evidence seed for the explicitly enabled demo profile. */
export const MOCK_INCIDENT_SCENARIO: IncidentObservationScenario = Object.freeze({
  ...MOCK_OBSERVATION_SCENARIO,
  incidents: Object.freeze({
    primaryApplicationId: MOCK_SYSTEM_SCENARIO.applicationId,
    templates: Object.freeze([
      Object.freeze({
        id: "incident-resource-pressure",
        offset: 0.83,
        severity: INCIDENT_SEVERITY.Critical,
        category: INCIDENT_CATEGORY.Resource,
        instanceOffset: 0,
        fact: Object.freeze({
          code: INCIDENT_FACT_CODE.ResourcePressure,
          metric: METRIC_ID.CpuRatio,
          value: 0.94,
          threshold: 0.9,
        }),
      }),
      Object.freeze({
        id: "incident-response-time",
        offset: 0.64,
        severity: INCIDENT_SEVERITY.Warning,
        category: INCIDENT_CATEGORY.ResponseTime,
        instanceOffset: 1,
        fact: Object.freeze({
          code: INCIDENT_FACT_CODE.ResponseTime,
          valueMs: 310,
          thresholdMs: 250,
        }),
      }),
      Object.freeze({
        id: "incident-rule-published",
        offset: 0.38,
        severity: INCIDENT_SEVERITY.Info,
        category: INCIDENT_CATEGORY.RulePublished,
        instanceOffset: null,
        fact: Object.freeze({
          code: INCIDENT_FACT_CODE.RulePublished,
          versionId: MOCK_RULE_SCENARIO.deployment.eventVersion.id,
        }),
      }),
    ]),
    recurring: Object.freeze({
      idPrefix: "incident-demo",
      count: 9,
      baseOffset: 0.32,
      offsetStep: 0.03,
      applicationOffsetStep: 0.005,
      severities: Object.freeze([
        INCIDENT_SEVERITY.Critical,
        INCIDENT_SEVERITY.Warning,
        INCIDENT_SEVERITY.Info,
      ]),
      categories: Object.freeze([
        INCIDENT_CATEGORY.Resource,
        INCIDENT_CATEGORY.ResponseTime,
        INCIDENT_CATEGORY.RuleEffective,
      ]),
      resourceValueBase: 0.86,
      resourceValueStep: 0.02,
      resourceThreshold: 0.85,
      responseValueBaseMs: 280,
      responseValueStepMs: 5,
      responseThresholdMs: 250,
      ruleVersionPrefix: "rules-demo",
    }),
    timelineFailure: Object.freeze({
      applicationId: "app-three",
      failOnRead: 1,
      errorCode: "service_unavailable" as const,
    }),
    receivedDelayMs: 1_500,
    sourceEventIdPrefix: "source",
    evidence: Object.freeze([
      Object.freeze({
        id: "evidence-metric-sample",
        source: "metrics-collector",
        minutesBefore: 1,
      }),
      Object.freeze({
        id: "evidence-threshold-policy",
        source: "observation-policy",
        minutesBefore: 3,
      }),
    ] as const),
    resourcePressureValueDelta: 0.03,
    relatedRule: Object.freeze({
      appId: MOCK_SYSTEM_SCENARIO.applicationId,
      bindingId: MOCK_RULE_SCENARIO.deployment.eventVersion.bindingId,
      publicationId: MOCK_RULE_SCENARIO.deployment.eventPublication.id,
      versionId: MOCK_RULE_SCENARIO.deployment.eventVersion.id,
    }),
  }),
});
