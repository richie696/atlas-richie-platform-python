import { AppError, AppErrorKind } from "@richie696/react-framework";
import {
  createOwnedQueryResource,
  type QueryAccessObserver,
} from "../../../shared/state/ownedQueryResource";
import type { IncidentPort } from "../api/incidentPort";
import {
  incidentQueryKey,
  incidentDetailKey,
  validIncidentQuery,
  validIncidentDetailQuery,
  validIncidentPage,
  validIncidentEvidence,
  type IncidentQuery,
  type IncidentPage,
  type IncidentDetailQuery,
  type IncidentEvidence,
} from "../model/incidentObservation";
const invalid = (status: number) =>
  new AppError(AppErrorKind.PROTOCOL, "Inconsistent incident observation", {
    status,
    code: status === 400 ? "invalid_incident_query" : "invalid_incident_observation",
  });
/** Independent list/detail owners share the one app-projected permission lifetime. No hidden selection fallback. */
export function createIncidentResources(
  port: IncidentPort,
  access: QueryAccessObserver,
  options: { readonly timeoutMs?: number } = {},
) {
  const timeline = createOwnedQueryResource<IncidentQuery, IncidentPage>(access, {
    keyOf: incidentQueryKey,
    timeoutMs: options.timeoutMs,
    async read(query, signal) {
      if (!validIncidentQuery(query)) throw invalid(400);
      const value = await port.readTimeline(query, signal);
      if (!validIncidentPage(value, query)) throw invalid(502);
      return value;
    },
    classify: (value) =>
      value.statistics.total === 0
        ? "empty"
        : value.items.length === 0
          ? "filtered-empty"
          : "ready",
  });
  const evidence = createOwnedQueryResource<IncidentDetailQuery, IncidentEvidence>(access, {
    keyOf: incidentDetailKey,
    timeoutMs: options.timeoutMs,
    async read(query, signal) {
      if (!validIncidentDetailQuery(query)) throw invalid(400);
      const value = await port.readEvidence(query, signal);
      if (!validIncidentEvidence(value, query)) throw invalid(502);
      return value;
    },
    classify: (value) => (value.completeness === "complete" ? "ready" : "partial"),
  });
  return Object.freeze({
    timeline,
    evidence,
    dispose() {
      timeline.dispose();
      evidence.dispose();
    },
  });
}
