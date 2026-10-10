import { z } from "zod";
import {
  OpaqueIdentifierSchema,
  RequestKeySchema,
  UtcInstantSchema,
  utf16BoundedString,
} from "../../../core/api/protocol/common";
import {
  ConfigurationSourceInputSchema,
  ConfigurationEndpointSchema,
  WriteOnlySecretSchema,
} from "../../../shared/api/configurationSourceWire";
import { SOURCE_CHECK_CAPABILITY } from "../model/sourceRegistration";

const KeepSourceSchema = z.discriminatedUnion("provider", [
  z.strictObject({
    provider: z.literal("nacos"),
    endpoint: ConfigurationEndpointSchema,
    namespace: utf16BoundedString(200),
    authentication: z.strictObject({ mode: z.literal("keep") }),
  }),
  z.strictObject({
    provider: z.literal("consul"),
    endpoint: ConfigurationEndpointSchema,
    datacenter: utf16BoundedString(200),
    authentication: z.strictObject({ mode: z.literal("keep") }),
  }),
]);
const SourceRecordFacts = {
  id: OpaqueIdentifierSchema,
  revision: OpaqueIdentifierSchema,
  name: OpaqueIdentifierSchema,
  endpoint: ConfigurationEndpointSchema,
  authenticationMode: z.enum(["none", "credential-reference", "direct"]),
  credentialConfigured: z.boolean(),
};
export const SourceRecordSchema = z.discriminatedUnion("provider", [
  z.strictObject({
    ...SourceRecordFacts,
    provider: z.literal("nacos"),
    namespace: utf16BoundedString(200),
  }),
  z.strictObject({
    ...SourceRecordFacts,
    provider: z.literal("consul"),
    datacenter: utf16BoundedString(200),
  }),
]);
export const SourceRegistrySchema = z.strictObject({
  asOf: UtcInstantSchema,
  items: z.array(SourceRecordSchema).max(500),
});
export const SourceCheckInputSchema = z.strictObject({
  sourceId: OpaqueIdentifierSchema.nullable(),
  expectedRevision: OpaqueIdentifierSchema.nullable(),
  source: z.union([ConfigurationSourceInputSchema, KeepSourceSchema]),
});
export const SourceCheckResultSchema = z.discriminatedUnion("status", [
  z.strictObject({
    status: z.literal("reachable"),
    checkedAt: UtcInstantSchema,
    expiresAt: UtcInstantSchema,
    capabilities: z.array(z.enum(SOURCE_CHECK_CAPABILITY)).max(3),
  }),
  z.strictObject({
    status: z.literal("unreachable"),
    checkedAt: UtcInstantSchema,
    expiresAt: UtcInstantSchema,
    reason: z.enum(["connection", "authentication", "unsupported"]),
  }),
]);
export const SourceMutationSchema = z.discriminatedUnion("kind", [
  z.strictObject({
    kind: z.literal("register"),
    requestKey: RequestKeySchema,
    name: OpaqueIdentifierSchema,
    source: ConfigurationSourceInputSchema,
  }),
  z.strictObject({
    kind: z.literal("update"),
    requestKey: RequestKeySchema,
    sourceId: OpaqueIdentifierSchema,
    expectedRevision: OpaqueIdentifierSchema,
    name: OpaqueIdentifierSchema,
    source: z.union([ConfigurationSourceInputSchema, KeepSourceSchema]),
  }),
]);
const SourceReceipts = [
  z.strictObject({ status: z.literal("pending"), requestKey: RequestKeySchema }),
  z.strictObject({
    status: z.literal("completed"),
    requestKey: RequestKeySchema,
    record: SourceRecordSchema,
  }),
  z.strictObject({
    status: z.literal("rejected"),
    requestKey: RequestKeySchema,
    reason: z.enum(["validation", "conflict", "not_found", "unavailable"]),
  }),
] as const;
export const SourceCommandObservationSchema = z.discriminatedUnion("status", SourceReceipts);
export const SourceOperationObservationSchema = z.discriminatedUnion("status", [
  z.strictObject({ status: z.literal("not_found"), requestKey: RequestKeySchema }),
  ...SourceReceipts,
]);
export const SourceWireSecretSchema = WriteOnlySecretSchema;
