import { OpaqueIdentifierSchema } from "../../../core/api/protocol/common";
import {
  CONSOLE_ACCESS,
  type ConsoleOperationContract,
} from "../../../core/api/protocol/operationContract";
import { INCIDENT_ENDPOINTS } from "./incidentHttp";
import { IncidentDetailParametersSchema, IncidentQueryParametersSchema } from "./incidentWire";
import {
  FLEET_OBSERVATION_CONTEXT,
  OBSERVATION_EXAMPLE_TIME,
  PROCESS_OBSERVATION_CONTEXT,
  observationErrorExample,
} from "../../../shared/api/observationContractExamples";

const incidentTimelineParameters = {
  environmentId: "prod",
  scope: "fleet",
  from: OBSERVATION_EXAMPLE_TIME.from,
  to: OBSERVATION_EXAMPLE_TIME.to,
  pageSize: 20,
};
const incidentEvidenceParameters = {
  environmentId: "prod",
  appId: "checkout",
  instanceId: "checkout-1",
  scope: "process",
  from: OBSERVATION_EXAMPLE_TIME.from,
  to: OBSERVATION_EXAMPLE_TIME.to,
};
export const INCIDENT_HTTP_CONTRACT = Object.freeze([
  {
    operationId: "readIncidentTimeline",
    summary: "读取筛选后的故障时间线和全范围统计",
    tag: "incidents",
    security: "session",
    requiredAccess: CONSOLE_ACCESS.MetricsView,
    endpoint: INCIDENT_ENDPOINTS.Timeline,
    input: null,
    pathParameters: [],
    queryParameters: Object.entries(IncidentQueryParametersSchema.shape).map(([name, schema]) => ({
      name,
      schema,
    })),
    examples: [
      {
        name: "empty-timeline",
        summary: "所选范围无事件时仍返回独立的全范围统计与空页",
        kind: "positive",
        request: { queryParameters: incidentTimelineParameters },
        response: {
          status: 200,
          body: {
            query: {
              context: FLEET_OBSERVATION_CONTEXT,
              severity: null,
              category: null,
              cursor: null,
              pageSize: 20,
            },
            asOf: OBSERVATION_EXAMPLE_TIME.asOf,
            statistics: {
              total: 0,
              critical: 0,
              warning: 0,
              info: 0,
              ruleChanges: 0,
              affectedApplications: 0,
            },
            items: [],
            filteredTotal: 0,
            nextCursor: null,
          },
        },
      },
      {
        name: "metrics-forbidden",
        summary: "没有 metrics:view 时拒绝读取故障时间线",
        kind: "negative",
        request: { queryParameters: incidentTimelineParameters },
        response: { status: 403, body: observationErrorExample("forbidden") },
      },
    ],
    semanticRules: [
      "Requires metrics:view; severity/category/cursor/pageSize and observation context are query/cache identity.",
      "Whole-scope statistics are independent of filtered page/cursor; server order uses occurredAt then stable scalar ID descending.",
      "Incident queries accept only fleet, application and process scopes, with matching nullable appId/instanceId identities; host, container and resource filters are unsupported.",
      "Scope is explicit: fleet has no app/instance, application has an app and no instance, process has both app and instance; statistics match the selected scope and window.",
      "Events carry structured finite facts only; no traceback, arbitrary business log or inferred cause.",
      "occurredAt is inside the half-open requested window; receivedAt may be later due to collector delay/clock skew.",
      "Cursor is opaque and bounded; next cursor cannot repeat the current cursor.",
      "Configuration publication and instance application remain distinct event categories.",
    ],
  },
  {
    operationId: "readIncidentEvidence",
    summary: "读取指定事件的关联观测事实",
    tag: "incidents",
    security: "session",
    requiredAccess: CONSOLE_ACCESS.MetricsView,
    endpoint: INCIDENT_ENDPOINTS.Evidence,
    input: null,
    pathParameters: [{ name: "incidentId", schema: OpaqueIdentifierSchema }],
    queryParameters: Object.entries(IncidentDetailParametersSchema.shape).map(([name, schema]) => ({
      name,
      schema,
    })),
    examples: [
      {
        name: "structured-event-evidence",
        summary: "返回有界结构化资源压力事实，不包含堆栈或业务日志",
        kind: "positive",
        request: {
          pathParameters: { incidentId: "incident-cpu-1" },
          queryParameters: incidentEvidenceParameters,
        },
        response: {
          status: 200,
          body: {
            query: {
              context: PROCESS_OBSERVATION_CONTEXT,
              eventId: "incident-cpu-1",
              severity: null,
              category: null,
            },
            asOf: OBSERVATION_EXAMPLE_TIME.asOf,
            event: {
              id: "incident-cpu-1",
              environmentId: "prod",
              appId: "checkout",
              instanceId: "checkout-1",
              processEpoch: "process-epoch-1",
              occurredAt: OBSERVATION_EXAMPLE_TIME.occurredAt,
              receivedAt: OBSERVATION_EXAMPLE_TIME.asOf,
              severity: "warning",
              category: "resource",
              sourceEventId: "collector-event-1",
              publicationId: null,
              caption: {
                code: "resource_pressure",
                metric: "cpu_ratio",
                value: 0.91,
                threshold: 0.85,
              },
            },
            facts: [],
            completeness: "complete",
            suggestedViews: ["metrics"],
            relatedRule: null,
          },
        },
      },
      {
        name: "event-not-found",
        summary: "事件不属于所选范围或不存在时不返回跨范围证据",
        kind: "negative",
        request: {
          pathParameters: { incidentId: "missing-event" },
          queryParameters: incidentEvidenceParameters,
        },
        response: { status: 404, body: observationErrorExample("not_found") },
      },
    ],
    semanticRules: [
      "Path event ID, window, environment/application and active filters must identify the same event.",
      "Evidence is bounded and structured, with explicit complete/partial/unavailable status.",
      "Suggested views only navigate to available facts; they never execute commands or claim causality.",
      "Related rule identity is an explicit environment/application/binding/version/publication projection; identities are server-owned and never inferred from captions or display labels.",
      "A related-rule projection must match the event's publication identity and structured version fact; navigation opens the exact read-only version and publication audit views.",
      "All timestamps are UTC facts; evidence read time is not event or sample time.",
    ],
  },
] satisfies readonly ConsoleOperationContract[]);
