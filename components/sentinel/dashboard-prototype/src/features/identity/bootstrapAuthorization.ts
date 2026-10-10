/**
 * One-time setup authorization entry. The factory accepts a {@link BootstrapAuthorizationPort};
 * authorization is confirmed by a subsequent gate read and rejects on denied, failed, or
 * unconfirmed outcomes. The app owner must call `dispose()` when the setup route owner ends;
 * submitted codes are not retained in snapshots.
 */
export {
  createBootstrapAuthorizationWorkflow,
  type BootstrapAuthorizationWorkflow,
} from "./application/bootstrapAuthorizationWorkflow";
export type { BootstrapAuthorizationPort } from "./api/bootstrapAuthorizationPort";
