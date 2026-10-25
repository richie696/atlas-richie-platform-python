import type {
  IncidentQuery,
  IncidentPage,
  IncidentDetailQuery,
  IncidentEvidence,
} from "../model/incidentObservation";
/** Console incident read model, not the Agent Reporting ingestion wire or a write-capable diagnostic agent. */
export interface IncidentPort {
  readonly readTimeline: (query: IncidentQuery, signal: AbortSignal) => Promise<IncidentPage>;
  readonly readEvidence: (
    query: IncidentDetailQuery,
    signal: AbortSignal,
  ) => Promise<IncidentEvidence>;
}
