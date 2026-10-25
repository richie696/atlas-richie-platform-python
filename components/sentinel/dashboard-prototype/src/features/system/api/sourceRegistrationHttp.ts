import { defineUrl, HttpMethod } from "@richie696/react-framework";
import { z } from "zod";
import type {
  ConsoleEndpoint,
  ConsoleTransport,
} from "../../../core/api/transport/consoleEndpoint";
import type { ConsoleErrorCode } from "../../../core/api/protocol/common";
import { RequestKeySchema } from "../../../core/api/protocol/common";
import { parseConsoleInput } from "../../../core/api/protocol/parseInput";
import type { SourceRegistrationPort } from "./sourceRegistrationPort";
import {
  validRegisteredSource,
  validSourceCheck,
  validSourceRegistry,
} from "../model/sourceRegistration";
import {
  SourceCheckInputSchema,
  SourceCheckResultSchema,
  SourceCommandObservationSchema,
  SourceMutationSchema,
  SourceOperationObservationSchema,
  SourceRegistrySchema,
  SourceRecordSchema,
} from "./sourceRegistrationWire";
import {
  sourceCheckFromWire,
  sourceOperationFromWire,
  sourceRegistryFromWire,
} from "./sourceRegistrationMapper";

const readErrors = [
  "invalid_request",
  "unauthenticated",
  "forbidden",
  "not_found",
  "rate_limited",
  "service_unavailable",
] as const;
const registryErrors = [
  "invalid_request",
  "unauthenticated",
  "forbidden",
  "service_unavailable",
] as const;
const commandErrors = [
  "invalid_request",
  "unauthenticated",
  "forbidden",
  "csrf_failed",
  "idempotency_conflict",
  "validation_failed",
  "rate_limited",
  "service_unavailable",
] as const;
const checkErrors = [
  "invalid_request",
  "unauthenticated",
  "forbidden",
  "csrf_failed",
  "rate_limited",
  "service_unavailable",
] as const;
function endpoint<T>(
  path: string,
  response: z.ZodType<T>,
  options: {
    readonly command?: boolean;
    readonly method?: HttpMethod;
    readonly csrf?: boolean;
    readonly errors?: readonly ConsoleErrorCode[];
  } = {},
): ConsoleEndpoint<T> {
  const command = options.command ?? false;
  return {
    url: defineUrl(path, options.method ? { method: options.method } : undefined),
    response,
    successStatus: command ? 202 : 200,
    command,
    idempotency: command ? "required" : "none",
    csrf: options.csrf ?? command,
    expireOnUnauthorized: true,
    errors: options.errors ?? (command ? commandErrors : readErrors),
  };
}

export const SOURCE_REGISTRATION_ENDPOINTS = Object.freeze({
  Registry: endpoint("/api/v1/system/sources", SourceRegistrySchema, {
    errors: registryErrors,
  }),
  Check: endpoint("/api/v1/system/sources/check", SourceCheckResultSchema, {
    method: HttpMethod.POST,
    csrf: true,
    errors: checkErrors,
  }),
  Command: endpoint("/api/v1/system/sources/commands", SourceCommandObservationSchema, {
    command: true,
    method: HttpMethod.POST,
  }),
  Operation: endpoint(
    "/api/v1/system/sources/operations/{requestKey}",
    SourceOperationObservationSchema,
  ),
});

/** Source secrets are write-only. Reads and command observations contain only safe revision metadata. */
export function createSourceRegistrationHttp(transport: ConsoleTransport): SourceRegistrationPort {
  return Object.freeze({
    async readSources(signal) {
      const wire = await transport.send(
        {
          ...SOURCE_REGISTRATION_ENDPOINTS.Registry,
          accept: (value) => validSourceRegistry(sourceRegistryFromWire(value)),
        },
        { signal },
      );
      return sourceRegistryFromWire(wire);
    },
    async checkSource(input, signal) {
      const body = parseConsoleInput(SourceCheckInputSchema, input);
      const wire = await transport.send(
        {
          ...SOURCE_REGISTRATION_ENDPOINTS.Check,
          accept: (value) => validSourceCheck(sourceCheckFromWire(value)),
        },
        { signal, body },
      );
      return sourceCheckFromWire(wire);
    },
    async mutateSource(input, signal) {
      const body = parseConsoleInput(SourceMutationSchema, input);
      const wire = await transport.send(
        {
          ...SOURCE_REGISTRATION_ENDPOINTS.Command,
          accept: (value) => value.requestKey === body.requestKey && validOperationResult(value),
        },
        { signal, body, requestKey: body.requestKey },
      );
      return sourceOperationFromWire(wire);
    },
    async readSourceOperation(requestKey, signal) {
      const key = parseConsoleInput(RequestKeySchema, requestKey);
      const wire = await transport.send(
        {
          ...SOURCE_REGISTRATION_ENDPOINTS.Operation,
          accept: (value) => value.requestKey === key && validOperationResult(value),
        },
        { signal, pathParams: [key] },
      );
      return sourceOperationFromWire(wire);
    },
  } satisfies SourceRegistrationPort);
}

function validOperationResult(value: z.infer<typeof SourceOperationObservationSchema>): boolean {
  return (
    value.status !== "completed" ||
    ("record" in value ? validSourceRecord(value.record) : value.deletedSourceId.length > 0)
  );
}

function validSourceRecord(value: z.infer<typeof SourceRecordSchema>): boolean {
  return validRegisteredSource(value);
}
