import { defineUrlCatalog, defineUrl, HttpMethod } from "@richie696/react-framework";
import { z } from "zod";
import type { ConsoleEndpoint } from "../../../core/api/transport/consoleEndpoint";
import {
  BootstrapSnapshotSchema,
  SessionReadSchema,
  SessionIdentitySchema,
  validSessionWire,
} from "./identityAccessWire";

export const IDENTITY_ACCESS_URLS = defineUrlCatalog({
  Bootstrap: defineUrl("/api/v1/system/bootstrap"),
  Session: defineUrl("/api/v1/auth/me"),
  Login: defineUrl("/api/v1/auth/login", { method: HttpMethod.POST }),
  Logout: defineUrl("/api/v1/auth/logout", { method: HttpMethod.POST }),
});

const Bootstrap: ConsoleEndpoint<z.infer<typeof BootstrapSnapshotSchema>> = {
  url: IDENTITY_ACCESS_URLS.Bootstrap,
  response: BootstrapSnapshotSchema,
  successStatus: 200,
  command: false,
  idempotency: "none",
  csrf: false,
  expireOnUnauthorized: false,
  errors: ["invalid_request", "service_unavailable"],
  accept: (value) => value.initialized || value.setupAvailable || !value.operatorAuthorized,
};
const Session: ConsoleEndpoint<z.infer<typeof SessionReadSchema>> = {
  url: IDENTITY_ACCESS_URLS.Session,
  response: SessionReadSchema,
  successStatus: 200,
  command: false,
  idempotency: "none",
  csrf: false,
  expireOnUnauthorized: true,
  errors: ["invalid_request", "service_unavailable"],
  accept: (value) => value === null || validSessionWire(value),
};
const Login: ConsoleEndpoint<z.infer<typeof SessionIdentitySchema>> = {
  url: IDENTITY_ACCESS_URLS.Login,
  response: SessionIdentitySchema,
  successStatus: 200,
  command: true,
  idempotency: "none",
  csrf: true,
  expireOnUnauthorized: false,
  errors: [
    "invalid_request",
    "unauthenticated",
    "csrf_failed",
    "rate_limited",
    "service_unavailable",
  ],
  accept: validSessionWire,
};
const Logout: ConsoleEndpoint<undefined> = {
  url: IDENTITY_ACCESS_URLS.Logout,
  response: z.undefined(),
  successStatus: 204,
  command: true,
  idempotency: "none",
  csrf: true,
  // A 401 is a definitive logout rejection, not an unknown command. The
  // authentication workflow already drops the trusted facts before dispatch
  // and keeps access unavailable until explicit session inspection. Let the
  // command observe the typed response instead of expiring/cancelling itself.
  expireOnUnauthorized: false,
  errors: ["invalid_request", "unauthenticated", "csrf_failed", "service_unavailable"],
};

/** Only authentication/bootstrap-read endpoints belong to the eager application entry. */
export const IDENTITY_ACCESS_ENDPOINTS = Object.freeze({ Bootstrap, Session, Login, Logout });
