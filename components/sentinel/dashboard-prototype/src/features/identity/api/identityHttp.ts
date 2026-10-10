/** Compatibility exports for contract tests and external integrations; app routes import narrow adapters directly. */
export { createIdentityHttp } from "./identityAccessHttp";
export { createInitializationHttp, createBootstrapAuthorizationHttp } from "./bootstrapSetupHttp";
