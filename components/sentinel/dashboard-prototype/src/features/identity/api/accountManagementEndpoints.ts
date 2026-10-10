import { defineUrlCatalog, defineUrl, HttpMethod } from "@richie696/react-framework";
import { z } from "zod";
import type { ConsoleEndpoint } from "../../../core/api/transport/consoleEndpoint";
import {
  AccountPageSchema,
  AccountRecordSchema,
  AccountCommandObservationSchema,
  AccountOperationObservationSchema,
  validAccountRecord,
  validAccountPage,
} from "./accountManagementWire";

export const ACCOUNT_URLS = defineUrlCatalog({
  List: defineUrl("/api/v1/accounts"),
  Read: defineUrl("/api/v1/accounts/{accountId}"),
  Command: defineUrl("/api/v1/accounts/commands", { method: HttpMethod.POST }),
  Operation: defineUrl("/api/v1/accounts/operations/{requestKey}"),
});
const ReadPolicy = {
  successStatus: 200,
  command: false,
  idempotency: "none",
  csrf: false,
  expireOnUnauthorized: true,
  errors: ["invalid_request", "unauthenticated", "forbidden", "service_unavailable"],
} as const;
const List: ConsoleEndpoint<z.infer<typeof AccountPageSchema>> = {
  ...ReadPolicy,
  url: ACCOUNT_URLS.List,
  response: AccountPageSchema,
  accept: validAccountPage,
};
const Read: ConsoleEndpoint<z.infer<typeof AccountRecordSchema> | null> = {
  ...ReadPolicy,
  url: ACCOUNT_URLS.Read,
  response: AccountRecordSchema.nullable(),
  accept: (value) => value === null || validAccountRecord(value),
};
const Command: ConsoleEndpoint<z.infer<typeof AccountCommandObservationSchema>> = {
  url: ACCOUNT_URLS.Command,
  response: AccountCommandObservationSchema,
  successStatus: 200,
  command: true,
  idempotency: "required",
  csrf: true,
  expireOnUnauthorized: true,
  errors: [
    "invalid_request",
    "unauthenticated",
    "forbidden",
    "csrf_failed",
    "idempotency_conflict",
    "service_unavailable",
  ],
  accept: (value) => value.status !== "completed" || validAccountRecord(value.account),
};
const Operation: ConsoleEndpoint<z.infer<typeof AccountOperationObservationSchema>> = {
  ...ReadPolicy,
  url: ACCOUNT_URLS.Operation,
  response: AccountOperationObservationSchema,
  accept: (value) => value.status !== "completed" || validAccountRecord(value.account),
};
/** Account authorization and revisions belong to the server; transport policy cannot grant admin authority. */
export const ACCOUNT_ENDPOINTS = Object.freeze({ List, Read, Command, Operation });
