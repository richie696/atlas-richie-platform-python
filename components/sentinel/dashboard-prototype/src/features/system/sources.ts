/** Formal internal source-management entry. Production HTTP adaptation is wired at the app composition root. */
export { createSourceRegistrationWorkflow } from "./application/sourceRegistrationWorkflow";
export { SourceRegistryPanel } from "./ui/SourceRegistryPanel";
export type { SourceRegistrationPort } from "./api/sourceRegistrationPort";
export type {
  RegisteredSource,
  SourceRegistrySnapshot,
  SourceCheckInput,
  SourceCheckResult,
  SourceMutation,
  SourceOperationObservation,
} from "./model/sourceRegistration";
