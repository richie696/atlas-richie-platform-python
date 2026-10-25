/**
 * Setup route entry. Inject one stable {@link InitializationPort} into the workflow factory;
 * the workflow owns async read/write uncertainty and must be disposed by its app-level owner.
 * The page consumes that workflow, keeps credentials transient, and reports failures through
 * its redacted snapshot rather than raw transport errors.
 */
export {
  createInitializationWorkflow,
  type InitializationWorkflow,
} from "./application/initializationWorkflow";
export type { InitializationPort } from "./api/initializationPort";
export { InitializationPage } from "./ui/InitializationPage";
export { BootstrapAuthorizationGate } from "./ui/BootstrapAuthorizationGate";
