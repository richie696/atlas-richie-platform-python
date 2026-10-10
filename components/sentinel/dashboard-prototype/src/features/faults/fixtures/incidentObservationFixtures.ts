import { INCIDENT_CATEGORY } from "../model/incident";
import type { IncidentCategory, IncidentSeverity } from "../model/incident";
import {
  INCIDENT_FACT_CODE,
  type IncidentFact,
  type ObservedIncident,
} from "../model/incidentObservation";

export type IncidentObservationScenario = {
  readonly environment: { readonly id: string };
  readonly applications: readonly { readonly id: string }[];
  readonly instances: readonly {
    readonly id: string;
    readonly appId: string;
    readonly processEpoch: string;
  }[];
  readonly incidents: {
    readonly primaryApplicationId: string;
    readonly templates: readonly {
      readonly id: string;
      readonly offset: number;
      readonly severity: IncidentSeverity;
      readonly category: IncidentCategory;
      readonly instanceOffset: number | null;
      readonly fact: IncidentFact;
    }[];
    readonly recurring: {
      readonly idPrefix: string;
      readonly count: number;
      readonly baseOffset: number;
      readonly offsetStep: number;
      readonly applicationOffsetStep: number;
      readonly severities: readonly IncidentSeverity[];
      readonly categories: readonly IncidentCategory[];
      readonly resourceValueBase: number;
      readonly resourceValueStep: number;
      readonly resourceThreshold: number;
      readonly responseValueBaseMs: number;
      readonly responseValueStepMs: number;
      readonly responseThresholdMs: number;
      readonly ruleVersionPrefix: string;
    };
    readonly timelineFailure: {
      readonly applicationId: string;
      readonly failOnRead: number;
      readonly errorCode: "service_unavailable";
    };
    readonly receivedDelayMs: number;
    readonly sourceEventIdPrefix: string;
    readonly evidence: readonly [
      { readonly id: string; readonly source: string; readonly minutesBefore: number },
      { readonly id: string; readonly source: string; readonly minutesBefore: number },
    ];
    readonly resourcePressureValueDelta: number;
    readonly relatedRule: {
      readonly appId: string;
      readonly bindingId: string;
      readonly publicationId: string;
      readonly versionId: string;
    };
  };
};

/** Build bounded, query-scoped sample facts; demo timestamps track the requested window. */
export function incidentFixturesFor(
  input: {
    readonly environmentId: string;
    readonly appId: string | null;
    readonly fromMs: number;
    readonly toMs: number;
  },
  scenario: IncidentObservationScenario,
): readonly ObservedIncident[] {
  if (input.environmentId !== scenario.environment.id) return Object.freeze([]);
  const span = input.toMs - input.fromMs;
  const appIds = scenario.applications
    .map(({ id }) => id)
    .filter((id) => input.appId === null || id === input.appId);
  const instancesFor = (appId: string) => scenario.instances.filter((item) => item.appId === appId);
  const instanceFor = (appId: string, index: number) => {
    const instances = instancesFor(appId);
    return instances.length === 0 ? null : instances[index % instances.length];
  };
  const { incidents } = scenario;
  const events = appIds.flatMap((appId, appIndex) => {
    const appOffset = appIndex * incidents.recurring.applicationOffsetStep;
    const appRows = incidents.templates.map((row) => {
      const target = row.instanceOffset === null ? null : instanceFor(appId, row.instanceOffset);
      return {
        ...row,
        id: appId === incidents.primaryApplicationId ? row.id : `${row.id}-${appId}`,
        offset: row.offset - appOffset,
        instanceId: target?.id ?? null,
        processEpoch: target?.processEpoch ?? null,
      };
    });
    const recurringRows = Array.from({ length: incidents.recurring.count }, (_, index) => {
      const severity =
        incidents.recurring.severities[index % incidents.recurring.severities.length];
      const category =
        incidents.recurring.categories[index % incidents.recurring.categories.length];
      const target = instanceFor(appId, index % 2);
      const instanceId = target?.id ?? null;
      const fact: IncidentFact =
        category === INCIDENT_CATEGORY.Resource
          ? {
              code: INCIDENT_FACT_CODE.ResourcePressure,
              metric: "cpu_ratio",
              value:
                incidents.recurring.resourceValueBase +
                (index % incidents.recurring.severities.length) *
                  incidents.recurring.resourceValueStep,
              threshold: incidents.recurring.resourceThreshold,
            }
          : category === INCIDENT_CATEGORY.ResponseTime
            ? {
                code: INCIDENT_FACT_CODE.ResponseTime,
                valueMs:
                  incidents.recurring.responseValueBaseMs +
                  index * incidents.recurring.responseValueStepMs,
                thresholdMs: incidents.recurring.responseThresholdMs,
              }
            : {
                code: INCIDENT_FACT_CODE.RuleApplied,
                versionId: `${incidents.recurring.ruleVersionPrefix}-${index + 1}`,
              };
      return {
        id: `${incidents.recurring.idPrefix}-${appId}-${index + 1}`,
        offset: incidents.recurring.baseOffset - index * incidents.recurring.offsetStep - appOffset,
        severity,
        category,
        instanceId,
        processEpoch: target?.processEpoch ?? null,
        fact,
      };
    });
    return [...appRows, ...recurringRows].map((row) => {
      const occurredAtMs = input.fromMs + Math.floor(span * row.offset);
      return Object.freeze({
        id: row.id,
        environmentId: input.environmentId,
        appId,
        instanceId: row.instanceId,
        processEpoch: row.processEpoch,
        occurredAtMs,
        receivedAtMs: occurredAtMs + incidents.receivedDelayMs,
        severity: row.severity,
        category: row.category,
        sourceEventId: `${incidents.sourceEventIdPrefix}-${row.id}`,
        publicationId:
          appId === incidents.relatedRule.appId && row.category === INCIDENT_CATEGORY.RulePublished
            ? incidents.relatedRule.publicationId
            : null,
        caption:
          appId === incidents.relatedRule.appId && row.category === INCIDENT_CATEGORY.RulePublished
            ? { code: INCIDENT_FACT_CODE.RulePublished, versionId: incidents.relatedRule.versionId }
            : row.fact,
      });
    });
  });
  return Object.freeze(events.sort((left, right) => right.occurredAtMs - left.occurredAtMs));
}
