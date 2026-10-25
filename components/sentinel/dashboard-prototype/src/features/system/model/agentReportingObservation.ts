import { validProtocolObservationPage } from "./systemReadGuards";

export const AGENT_REPORTING_BOUNDARY = "agent-reporting" as const;
export const MAX_PROTOCOL_OBSERVATIONS_PAGE = 1_000_000;
export const AGENT_REPORTING_COMPATIBILITY = Object.freeze({
  Compatible: "compatible",
  Incompatible: "incompatible",
  Unknown: "unknown",
} as const);
export type AgentReportingCompatibility =
  (typeof AGENT_REPORTING_COMPATIBILITY)[keyof typeof AGENT_REPORTING_COMPATIBILITY];

export interface AgentReportingWorkerObservation {
  readonly environmentId: string;
  readonly appId: string;
  readonly instanceId: string;
  readonly processId: string;
  readonly reporterId: string;
  readonly boundary: typeof AGENT_REPORTING_BOUNDARY;
  readonly collectorSupported: readonly string[];
  readonly runtimeVersion: string | null;
  readonly compatibility: AgentReportingCompatibility;
  readonly observedAtMs: number | null;
}

export interface AgentReportingObservationPage {
  readonly asOfMs: number;
  readonly page: number;
  readonly pageSize: number;
  readonly total: number;
  readonly items: readonly AgentReportingWorkerObservation[];
}

export function validAgentReportingObservationPage(value: AgentReportingObservationPage): boolean {
  return validProtocolObservationPage(value, AGENT_REPORTING_BOUNDARY);
}
