import { validProtocolObservationPage } from "./systemReadGuards";

export const INCIDENT_EVENT_BOUNDARY = "incident-events" as const;
export const INCIDENT_EVENT_COMPATIBILITY = Object.freeze({
  Compatible: "compatible",
  Incompatible: "incompatible",
  Unknown: "unknown",
} as const);
export type IncidentEventCompatibility =
  (typeof INCIDENT_EVENT_COMPATIBILITY)[keyof typeof INCIDENT_EVENT_COMPATIBILITY];

export interface IncidentEventWorkerObservation {
  readonly environmentId: string;
  readonly appId: string;
  readonly instanceId: string;
  readonly processId: string;
  readonly reporterId: string;
  readonly boundary: typeof INCIDENT_EVENT_BOUNDARY;
  readonly collectorSupported: readonly string[];
  readonly runtimeVersion: string | null;
  readonly compatibility: IncidentEventCompatibility;
  readonly observedAtMs: number | null;
}

export interface IncidentEventObservationPage {
  readonly asOfMs: number;
  readonly page: number;
  readonly pageSize: number;
  readonly total: number;
  readonly items: readonly IncidentEventWorkerObservation[];
}

export function validIncidentEventObservationPage(value: IncidentEventObservationPage): boolean {
  return validProtocolObservationPage(value, INCIDENT_EVENT_BOUNDARY);
}
