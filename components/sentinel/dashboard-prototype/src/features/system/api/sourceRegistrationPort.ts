import type {
  SourceRegistrySnapshot,
  SourceCheckInput,
  SourceCheckResult,
  SourceMutation,
  SourceOperationObservation,
} from "../model/sourceRegistration";
/** Normal administrative source management, never a re-opened setup endpoint. Python owns credential resolution, SSRF and conditional persistence. */
export interface SourceRegistrationPort {
  readSources(signal: AbortSignal): Promise<SourceRegistrySnapshot>;
  checkSource(input: SourceCheckInput, signal: AbortSignal): Promise<SourceCheckResult>;
  mutateSource(input: SourceMutation, signal: AbortSignal): Promise<SourceOperationObservation>;
  readSourceOperation(requestKey: string, signal: AbortSignal): Promise<SourceOperationObservation>;
}
