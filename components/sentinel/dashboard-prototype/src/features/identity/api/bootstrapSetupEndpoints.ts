import { defineUrlCatalog, defineUrl, HttpMethod } from "@richie696/react-framework";
import { z } from "zod";
import type { ConsoleEndpoint } from "../../../core/api/transport/consoleEndpoint";
import { IDENTITY_ACCESS_ENDPOINTS } from "./identityAccessEndpoints";
import {
  BootstrapAuthorizationSchema,
  ConnectionCheckSchema,
  InitializationObservationSchema,
  InitializationCommandObservationSchema,
} from "./bootstrapSetupWire";

export const BOOTSTRAP_SETUP_URLS = defineUrlCatalog({
  AuthorizeBootstrap: defineUrl("/api/v1/system/bootstrap/authorize", { method: HttpMethod.POST }),
  AuthorizeLocalBootstrap: defineUrl("/api/v1/system/bootstrap/authorize-local", {
    method: HttpMethod.POST,
  }),
  CheckDatabase: defineUrl("/api/v1/system/bootstrap/database-check", { method: HttpMethod.POST }),
  CheckSource: defineUrl("/api/v1/system/bootstrap/source-check", { method: HttpMethod.POST }),
  Initialize: defineUrl("/api/v1/system/bootstrap/initialize", { method: HttpMethod.POST }),
  Initialization: defineUrl("/api/v1/system/bootstrap/operations/{requestKey}"),
});

const AuthorizeBootstrap: ConsoleEndpoint<z.infer<typeof BootstrapAuthorizationSchema>> = {
  url: BOOTSTRAP_SETUP_URLS.AuthorizeBootstrap,
  response: BootstrapAuthorizationSchema,
  successStatus: 200,
  command: true,
  idempotency: "none",
  csrf: true,
  expireOnUnauthorized: false,
  errors: [
    "invalid_request",
    "forbidden",
    "csrf_failed",
    "conflict",
    "rate_limited",
    "service_unavailable",
  ],
};
const AuthorizeLocalBootstrap: ConsoleEndpoint<z.infer<typeof BootstrapAuthorizationSchema>> = {
  url: BOOTSTRAP_SETUP_URLS.AuthorizeLocalBootstrap,
  response: BootstrapAuthorizationSchema,
  successStatus: 200,
  command: true,
  idempotency: "none",
  csrf: true,
  expireOnUnauthorized: false,
  errors: ["invalid_request", "forbidden", "csrf_failed", "conflict", "service_unavailable"],
};
const check = (
  url: typeof BOOTSTRAP_SETUP_URLS.CheckDatabase,
): ConsoleEndpoint<z.infer<typeof ConnectionCheckSchema>> => ({
  url,
  response: ConnectionCheckSchema,
  successStatus: 200,
  command: false,
  idempotency: "none",
  csrf: true,
  expireOnUnauthorized: false,
  errors: ["invalid_request", "bootstrap_unauthorized", "csrf_failed", "service_unavailable"],
});
const Initialize: ConsoleEndpoint<z.infer<typeof InitializationCommandObservationSchema>> = {
  url: BOOTSTRAP_SETUP_URLS.Initialize,
  response: InitializationCommandObservationSchema,
  successStatus: 200,
  command: true,
  idempotency: "required",
  csrf: true,
  expireOnUnauthorized: false,
  errors: [
    "invalid_request",
    "bootstrap_unauthorized",
    "csrf_failed",
    "idempotency_conflict",
    "service_unavailable",
  ],
};
const Initialization: ConsoleEndpoint<z.infer<typeof InitializationObservationSchema>> = {
  url: BOOTSTRAP_SETUP_URLS.Initialization,
  response: InitializationObservationSchema,
  successStatus: 200,
  command: false,
  idempotency: "none",
  csrf: false,
  expireOnUnauthorized: false,
  errors: ["invalid_request", "bootstrap_unauthorized", "service_unavailable"],
};

/** Endpoint metadata used only by the lazy first-run setup workflow. */
export const BOOTSTRAP_SETUP_ENDPOINTS = Object.freeze({
  AuthorizeBootstrap,
  AuthorizeLocalBootstrap,
  CheckDatabase: check(BOOTSTRAP_SETUP_URLS.CheckDatabase),
  CheckSource: check(BOOTSTRAP_SETUP_URLS.CheckSource),
  Initialize,
  Initialization,
});

/** Setup needs the shared bootstrap snapshot gate, but no other authentication endpoint. */
export const BOOTSTRAP_GATE_ENDPOINT = IDENTITY_ACCESS_ENDPOINTS.Bootstrap;
