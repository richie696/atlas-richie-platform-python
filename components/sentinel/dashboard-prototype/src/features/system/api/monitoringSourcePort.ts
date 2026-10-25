import type {
  MonitoringCredentialMaterial,
  MonitoringSourceCandidate,
  MonitoringSourceCheckReceipt,
  MonitoringSourceMutation,
  MonitoringSourceOperation,
  MonitoringSourceRecord,
  MonitoringSourcesSnapshot,
} from "../model/monitoringSource";

/** HTTP adapter boundary used by the monitoring-source management workflow. */
export interface MonitoringSourcePort {
  readSources(signal: AbortSignal): Promise<MonitoringSourcesSnapshot>;
  readSource(sourceId: string, signal: AbortSignal): Promise<MonitoringSourceRecord>;
  checkCandidate(
    source: MonitoringSourceCandidate,
    credentials: MonitoringCredentialMaterial,
    signal: AbortSignal,
  ): Promise<MonitoringSourceCheckReceipt>;
  mutate(input: MonitoringSourceMutation, signal: AbortSignal): Promise<MonitoringSourceOperation>;
  readOperation(requestKey: string, signal: AbortSignal): Promise<MonitoringSourceOperation>;
}
