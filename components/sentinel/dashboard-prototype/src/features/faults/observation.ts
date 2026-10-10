/** Internal incident-observation assembly; the demo handler remains opt-in through the mock entry. */
export { createIncidentResources } from "./application/incidentResources";
export { IncidentObservationContainer } from "./ui/IncidentObservationContainer";
export { IncidentObservationPage } from "./ui/IncidentObservationPage";
export type { IncidentPort } from "./api/incidentPort";
export type {
  IncidentQuery,
  IncidentDetailQuery,
  IncidentPage,
  IncidentEvidence,
} from "./model/incidentObservation";
