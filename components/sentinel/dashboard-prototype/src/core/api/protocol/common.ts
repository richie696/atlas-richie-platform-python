import { z } from "zod";
import { hasOnlyUnicodeScalarValues, NON_BLANK_WIRE_CONTENT } from "./wireString";
export {
  hasNonBlankWireContent,
  hasOnlyUnicodeScalarValues,
  NON_BLANK_WIRE_CONTENT,
} from "./wireString";

/** Wire bounds are shared by validators, generated schemas and the transport; never silently truncate. */
export const CONSOLE_WIRE_LIMIT = Object.freeze({
  BodyBytes: 1_048_576,
  Identifier: 200,
  RequestKey: 128,
  PageSize: 100,
  Issues: 32,
  RetryAfterMs: 300_000,
  JsonDepth: 50,
});
export const CONSOLE_HEADER = Object.freeze({
  Csrf: "x-sentinel-csrf",
  RequestId: "x-request-id",
  IdempotencyKey: "idempotency-key",
} as const);
export const CsrfNonceSchema = z.string().regex(/^[A-Za-z0-9_-]{32,256}$/);
/** Create a bounded UTF-16 wire-string schema that rejects unpaired surrogates. */
export function utf16BoundedString(maximum: number): z.ZodString {
  if (!Number.isSafeInteger(maximum) || maximum < 0)
    throw new RangeError("UTF-16 string limit must be a non-negative safe integer");
  const codeUnitLimit = new RegExp(`^(?![\\s\\S]{${maximum + 1}})`);
  return z
    .string()
    .max(maximum)
    .regex(codeUnitLimit)
    .refine(hasOnlyUnicodeScalarValues, "String must contain Unicode scalar values");
}

export const OpaqueIdentifierSchema = utf16BoundedString(CONSOLE_WIRE_LIMIT.Identifier)
  .min(1)
  .regex(NON_BLANK_WIRE_CONTENT);
export const RequestKeySchema = utf16BoundedString(CONSOLE_WIRE_LIMIT.RequestKey)
  .min(1)
  .regex(/^[A-Za-z0-9._:-]+$/);
export const UtcInstantSchema = z.iso
  .datetime({ offset: false, local: false, precision: 3 })
  .regex(/^(?:19[7-9]\d|[2-9]\d{3})-/);
export const PageNumberSchema = z.int().min(1).max(1_000_000);
export const PageSizeSchema = z.int().min(1).max(CONSOLE_WIRE_LIMIT.PageSize);
export const TotalCountSchema = z.int().min(0).max(Number.MAX_SAFE_INTEGER);
export const InventoryCoverageSchema = z.union([
  z.strictObject({ expected: z.null(), inventorySource: z.null() }),
  z.strictObject({ expected: TotalCountSchema, inventorySource: OpaqueIdentifierSchema }),
]);
/** Only UTC string conversion is allowed here. Durations and opaque native revisions stay unchanged. */
export function instantToMilliseconds(value: string): number {
  const result = UtcInstantSchema.safeParse(value);
  if (!result.success) throw new Error("Invalid Console UTC instant");
  const milliseconds = Date.parse(result.data);
  if (!Number.isSafeInteger(milliseconds) || milliseconds < 0)
    throw new Error("Invalid Console instant");
  return milliseconds;
}
export function millisecondsToInstant(value: number): string {
  if (!Number.isSafeInteger(value) || value < 0) throw new Error("Invalid Console instant");
  const result = new Date(value).toISOString();
  return UtcInstantSchema.parse(result);
}

/** Enumerable, stable rejection codes. Raw server messages and provider exceptions are not a wire field. */
export const CONSOLE_ERROR_STATUS = Object.freeze({
  invalid_request: 400,
  current_password_invalid: 400,
  unauthenticated: 401,
  forbidden: 403,
  csrf_failed: 403,
  bootstrap_unauthorized: 403,
  not_found: 404,
  target_retired: 410,
  conflict: 409,
  idempotency_conflict: 409,
  validation_failed: 422,
  unsupported_profile: 422,
  rate_limited: 429,
  service_unavailable: 503,
  dependency_unavailable: 503,
} as const);
export type ConsoleErrorCode = keyof typeof CONSOLE_ERROR_STATUS;
const FieldIssueSchema = z.strictObject({
  field: utf16BoundedString(160)
    .min(1)
    .regex(/^[A-Za-z0-9_.\[\]-]+$/),
  reason: z.enum(["required", "invalid", "out_of_range", "unsupported", "conflict"]),
});
export const ConsoleErrorSchema = z.strictObject({
  error: z.strictObject({
    code: z.enum(Object.keys(CONSOLE_ERROR_STATUS) as [ConsoleErrorCode, ...ConsoleErrorCode[]]),
    requestId: RequestKeySchema,
    issues: z.array(FieldIssueSchema).max(CONSOLE_WIRE_LIMIT.Issues).optional(),
    retryAfterMs: z.int().min(0).max(CONSOLE_WIRE_LIMIT.RetryAfterMs).optional(),
  }),
});
