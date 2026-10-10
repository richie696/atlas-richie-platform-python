/** Application composition entry: authentication only, without eagerly importing five route pages. */
export {
  createAuthenticationWorkflow,
  type AuthenticationWorkflow,
} from "./application/authenticationWorkflow";
export { AuthenticationProvider, useAuthentication } from "./state/AuthenticationProvider";
export {
  decideControlPlaneAccess,
  isAdministrator,
  type AccessRequirement,
} from "./model/controlPlaneAccess";
export type {
  IdentityAccessPort,
  IdentitySessionObserver,
  IdentitySessionOwner,
  IdentitySessionRevalidator,
} from "./api/identityAccessPort";
export { IDENTITY_ROLE } from "./model/account";
export type { ControlPlaneAccessState, SessionIdentity } from "./model/controlPlaneAccess";
