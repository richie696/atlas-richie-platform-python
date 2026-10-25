import { z } from "zod";
import {
  NON_BLANK_WIRE_CONTENT,
  OpaqueIdentifierSchema,
  RequestKeySchema,
  utf16BoundedString,
} from "../../../core/api/protocol/common";
import { NO_WIRE_BOUNDARY_BLANK } from "../../../core/api/protocol/wireString";
import { ConfigurationSourceInputSchema } from "../../../shared/api/configurationSourceWire";
import { WriteOnlySecretSchema } from "../../../shared/api/writeOnlySecretWire";
import { PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH } from "../model/passwordPolicy";
import { UsernameSchema } from "./identityAccessWire";

export const BootstrapAuthorizationInputSchema = z.strictObject({
  operatorCode: utf16BoundedString(1024)
    .regex(/^[A-Za-z0-9_-]{32,1024}$/)
    .meta({ writeOnly: true }),
});
export const LocalBootstrapAuthorizationInputSchema = z.strictObject({});
export const BootstrapAuthorizationSchema = z.strictObject({ authorized: z.literal(true) });
const DatabaseIdentity = {
  host: utf16BoundedString(253).min(1).regex(NO_WIRE_BOUNDARY_BLANK),
  port: z.int().min(1).max(65535),
  database: utf16BoundedString(200).min(1),
  username: utf16BoundedString(200).min(1).regex(NON_BLANK_WIRE_CONTENT),
  password: WriteOnlySecretSchema,
};
export const SetupStorageSchema = z.discriminatedUnion("kind", [
  z.strictObject({ kind: z.literal("sqlite") }),
  z.strictObject({ kind: z.literal("postgresql"), ...DatabaseIdentity }),
  z.strictObject({ kind: z.literal("mysql"), ...DatabaseIdentity }),
]);
export const SetupSubmissionSchema = z.strictObject({
  database: SetupStorageSchema,
  admin: z.strictObject({
    username: UsernameSchema,
    password: WriteOnlySecretSchema.min(PASSWORD_MIN_LENGTH).max(PASSWORD_MAX_LENGTH),
  }),
  source: ConfigurationSourceInputSchema,
});
export const InitializeCommandSchema = z.strictObject({
  requestKey: RequestKeySchema,
  input: SetupSubmissionSchema,
});
export const ConnectionCheckSchema = z.discriminatedUnion("status", [
  z.strictObject({ status: z.literal("reachable") }),
  z.strictObject({
    status: z.literal("unreachable"),
    reason: z.enum(["authentication", "connection", "unsupported"]),
  }),
]);
const INITIALIZATION_RECEIPTS = [
  z.strictObject({
    status: z.literal("pending"),
    requestKey: RequestKeySchema,
    operationId: OpaqueIdentifierSchema,
  }),
  z.strictObject({
    status: z.literal("completed"),
    requestKey: RequestKeySchema,
    operationId: OpaqueIdentifierSchema,
  }),
  z.strictObject({
    status: z.literal("rejected"),
    requestKey: RequestKeySchema,
    operationId: OpaqueIdentifierSchema,
    reason: z.enum(["validation", "setup-closed", "dependency"]),
  }),
] as const;
export const InitializationCommandObservationSchema = z.discriminatedUnion(
  "status",
  INITIALIZATION_RECEIPTS,
);
export const InitializationObservationSchema = z.discriminatedUnion("status", [
  z.strictObject({ status: z.literal("not-found"), requestKey: RequestKeySchema }),
  ...INITIALIZATION_RECEIPTS,
]);
