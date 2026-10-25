/**
 * System-management capability's application composition entry. Observation/source factories
 * take their feature Ports and are owned/disposed by the app route; the exported tab identifiers
 * are stable URL values, not translated labels. UI props and transport failures are documented
 * at their declarations; the feature never chooses a concrete transport or stores credentials.
 */
export { SystemPage } from "./ui/SystemPage";
export { SystemObservationContainer } from "./ui/SystemObservationContainer";
export { SYSTEM_TAB, SYSTEM_TABS, type SystemTab } from "./model/systemStatus";
export { createSourceRegistrationWorkflow } from "./application/sourceRegistrationWorkflow";
export { createMonitoringSourceWorkflow } from "./application/monitoringSourceWorkflow";
export { createSourceRegistrationHttp } from "./api/sourceRegistrationHttp";
export { createMonitoringSourceHttp } from "./api/monitoringSourceHttp";
export { createSystemObservationHttp } from "./api/systemObservationHttp";
export type { SourceRegistrationPort } from "./api/sourceRegistrationPort";
export type { MonitoringSourcePort } from "./api/monitoringSourcePort";
export type { SystemObservationPorts } from "./api/systemObservationPort";
export { createSystemSettingsHttp } from "./api/systemSettingsHttp";
export type { SystemSettingsPort } from "./api/systemSettingsPort";
export { SourceRegistryPanel } from "./ui/SourceRegistryPanel";
