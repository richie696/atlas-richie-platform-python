import { z } from "zod";
import {
  ConsoleErrorSchema,
  CONSOLE_ERROR_STATUS,
  CONSOLE_HEADER,
  CsrfNonceSchema,
  CONSOLE_WIRE_LIMIT,
  RequestKeySchema,
} from "../../core/api/protocol/common";
import type { ConsoleOperationContract } from "../../core/api/protocol/operationContract";
import {
  CONSOLE_CAPABILITY,
  CONSOLE_REQUIRED_ROLE,
} from "../../core/api/protocol/operationContract";
import {
  IDENTITY_HTTP_CONTRACT,
  ACCOUNT_HTTP_CONTRACT,
  OWN_PASSWORD_HTTP_CONTRACT,
} from "../../features/identity/http";
import { METRICS_HTTP_CONTRACT } from "../../features/realtime/http";
import { FLEET_HTTP_CONTRACT } from "../../features/overview/http";
import {
  INSTANCE_HTTP_CONTRACT,
  OBSERVATION_CATALOG_HTTP_CONTRACT,
} from "../../features/applications/http";
import { INCIDENT_HTTP_CONTRACT } from "../../features/faults/http";
import {
  SOURCE_REGISTRATION_HTTP_CONTRACT,
  SYSTEM_OBSERVATION_HTTP_CONTRACT,
} from "../../features/system/http";
import { RULE_SET_HTTP_CONTRACT } from "../../features/rules/http";

export const CONSOLE_OPERATIONS: readonly ConsoleOperationContract[] = Object.freeze([
  ...IDENTITY_HTTP_CONTRACT,
  ...ACCOUNT_HTTP_CONTRACT,
  ...OWN_PASSWORD_HTTP_CONTRACT,
  ...METRICS_HTTP_CONTRACT,
  ...FLEET_HTTP_CONTRACT,
  ...INSTANCE_HTTP_CONTRACT,
  ...OBSERVATION_CATALOG_HTTP_CONTRACT,
  ...INCIDENT_HTTP_CONTRACT,
  ...SYSTEM_OBSERVATION_HTTP_CONTRACT,
  ...SOURCE_REGISTRATION_HTTP_CONTRACT,
  ...RULE_SET_HTTP_CONTRACT,
]);
const annotateUtf16Limits = (value: unknown): unknown => {
  if (Array.isArray(value)) return value.map(annotateUtf16Limits);
  if (value === null || typeof value !== "object") return value;

  const schema: Record<string, unknown> = {};
  for (const [key, nested] of Object.entries(value)) {
    schema[key] = annotateUtf16Limits(nested);
  }
  if (schema.type === "string" && typeof schema.maxLength === "number") {
    schema["x-max-utf16-code-units"] = schema.maxLength;
  }
  return schema;
};

const schemaFor = (schema: z.ZodType) =>
  annotateUtf16Limits(
    z.toJSONSchema(schema, { target: "draft-2020-12", unrepresentable: "throw" }),
  );

interface OpenApiParameter {
  name: string;
  in: "header" | "path" | "query";
  required: boolean;
  schema: unknown;
  examples?: Record<string, { summary: string; value: unknown }>;
}

const securityRequirements = (operation: ConsoleOperationContract) => {
  const alternatives: Record<string, string[]>[] =
    operation.security === "public"
      ? []
      : operation.security === "optional-bootstrap"
        ? [{}, { BootstrapOperator: [] }]
        : operation.security === "anonymous"
          ? [{}, { BrowserSession: [] }]
          : [{ [operation.security === "bootstrap" ? "BootstrapOperator" : "BrowserSession"]: [] }];
  if (!operation.endpoint.csrf) return alternatives;
  return alternatives.length === 0
    ? [{ CsrfCookie: [] }]
    : alternatives.map((requirement) => ({ ...requirement, CsrfCookie: [] }));
};

/** Generate from runtime declarations. No unknown-to-any conversion or assertion of complete semantic validation. */
export function createConsoleOpenApi(operations = CONSOLE_OPERATIONS) {
  const paths: Record<string, Record<string, unknown>> = {};
  const names = new Set<string>();
  const allowedRoles = new Set<string>(Object.values(CONSOLE_REQUIRED_ROLE));
  const allowedCapabilities = new Set<string>(Object.values(CONSOLE_CAPABILITY));
  for (const operation of operations) {
    const endpoint = operation.endpoint,
      method = endpoint.url.method.toLowerCase();
    const access = operation.requiredAccess;
    if (
      (access.role !== null && !allowedRoles.has(access.role)) ||
      access.capabilities.some((capability) => !allowedCapabilities.has(capability)) ||
      new Set(access.capabilities).size !== access.capabilities.length
    )
      throw new Error("Unknown or duplicate Console access requirement");
    if (
      (access.role !== null || access.capabilities.length > 0) &&
      operation.security !== "session"
    )
      throw new Error("Role/capability access requires a session-protected operation");
    const parameterNames = [...endpoint.url.path.matchAll(/\{([^}]+)\}/g)].map((match) => match[1]);
    if (
      names.has(operation.operationId) ||
      parameterNames.join("|") !== operation.pathParameters.map((value) => value.name).join("|")
    )
      throw new Error("Duplicate operation or missing path parameter contract");
    names.add(operation.operationId);
    const path = (paths[endpoint.url.path] ??= {});
    if (path[method]) throw new Error("Duplicate Console method/path contract");
    const examples = operation.examples ?? [];
    const requestExamples = Object.fromEntries(
      examples
        .filter((example) => Object.hasOwn(example.request, "body"))
        .map((example) => [
          example.name,
          { summary: example.summary, value: example.request.body },
        ]),
    );
    const responseExamples = new Map<number, Record<string, unknown>>();
    for (const example of examples) {
      if (!Object.hasOwn(example.response, "body")) continue;
      const entries = responseExamples.get(example.response.status) ?? {};
      entries[example.name] = { summary: example.summary, value: example.response.body };
      responseExamples.set(example.response.status, entries);
    }
    const parameters: OpenApiParameter[] = [
      {
        name: CONSOLE_HEADER.RequestId,
        in: "header" as const,
        required: true,
        schema: schemaFor(RequestKeySchema),
      },
      ...operation.pathParameters.map((value) => ({
        name: value.name,
        in: "path" as const,
        required: true,
        schema: schemaFor(value.schema),
      })),
      ...(operation.queryParameters ?? []).map((value) => ({
        name: value.name,
        in: "query" as const,
        required: !value.schema.isOptional(),
        schema: schemaFor(value.schema),
      })),
    ];
    if (endpoint.csrf)
      parameters.push({
        name: CONSOLE_HEADER.Csrf,
        in: "header" as const,
        required: true,
        schema: schemaFor(CsrfNonceSchema),
      });
    if (endpoint.idempotency === "required")
      parameters.push({
        name: CONSOLE_HEADER.IdempotencyKey,
        in: "header" as const,
        required: true,
        schema: schemaFor(RequestKeySchema),
      });
    const successExamples = responseExamples.get(endpoint.successStatus);
    const success = {
      description:
        endpoint.successStatus === 204
          ? "Confirmed empty response; no body"
          : "Typed response fact; not a declaration of end-to-end completion",
      headers: {
        [CONSOLE_HEADER.RequestId]: { required: true, schema: schemaFor(RequestKeySchema) },
        [CONSOLE_HEADER.Csrf]: {
          description: "Optional rotated private CSRF nonce. Never an authentication credential.",
          schema: schemaFor(CsrfNonceSchema),
        },
      },
      ...(endpoint.successStatus !== 204
        ? {
            content: {
              "application/json": {
                schema: schemaFor(endpoint.response),
                ...(successExamples ? { examples: successExamples } : {}),
              },
            },
          }
        : {}),
    };
    const byStatus = new Map<number, string[]>();
    for (const code of endpoint.errors) {
      const status = CONSOLE_ERROR_STATUS[code];
      const codes = byStatus.get(status) ?? [];
      codes.push(code);
      byStatus.set(status, codes);
    }
    const errors = Object.fromEntries(
      [...byStatus].map(([status, codes]) => [
        String(status),
        {
          description: "Finite safe rejection",
          "x-allowed-error-codes": codes,
          headers: {
            [CONSOLE_HEADER.RequestId]: { required: true, schema: schemaFor(RequestKeySchema) },
          },
          content: {
            "application/json": {
              schema: schemaFor(
                ConsoleErrorSchema.extend({
                  error: ConsoleErrorSchema.shape.error.extend({ code: z.enum(codes) }),
                }),
              ),
              ...(responseExamples.get(status) ? { examples: responseExamples.get(status) } : {}),
            },
          },
        },
      ]),
    );
    const security = securityRequirements(operation);
    for (const parameter of parameters) {
      const matching = examples.filter((example) => {
        const values =
          parameter.in === "path"
            ? example.request.pathParameters
            : parameter.in === "query"
              ? example.request.queryParameters
              : undefined;
        return values !== undefined && Object.hasOwn(values, parameter.name);
      });
      if (matching.length > 0) {
        parameter.examples = Object.fromEntries(
          matching.map((example) => {
            const values =
              parameter.in === "path"
                ? example.request.pathParameters
                : example.request.queryParameters;
            return [example.name, { summary: example.summary, value: values?.[parameter.name] }];
          }),
        );
      }
    }
    const requestBody = operation.input
      ? {
          required: true,
          content: {
            "application/json": {
              schema: schemaFor(operation.input),
              ...(Object.keys(requestExamples).length > 0 ? { examples: requestExamples } : {}),
            },
          },
        }
      : undefined;
    path[method] = {
      operationId: operation.operationId,
      summary: operation.summary,
      tags: [operation.tag],
      security,
      parameters,
      ...(requestBody ? { requestBody } : {}),
      responses: { [endpoint.successStatus]: success, ...errors },
      "x-required-access": {
        role: operation.requiredAccess.role,
        capabilities: [...operation.requiredAccess.capabilities],
      },
      "x-semantic-rules": operation.semanticRules,
      "x-unknown-outcome": endpoint.command,
      ...(examples.length > 0 ? { "x-contract-examples": examples } : {}),
    };
  }
  return {
    openapi: "3.1.0",
    info: {
      title: "Atlas Richie Sentinel Console API",
      version: "0.4.0-draft",
      description:
        "Generated from runtime DTOs. Bounded string schemas pair JSON Schema maxLength with x-max-utf16-code-units because JavaScript and Python enforce UTF-16 code units. Partial F6 implementation; not a frozen/released backend contract.",
    },
    "x-contract-status": "draft-partial",
    "x-max-body-bytes": CONSOLE_WIRE_LIMIT.BodyBytes,
    "x-error-status": CONSOLE_ERROR_STATUS,
    "x-covered-capabilities": [
      "authentication",
      "bootstrap",
      "accounts",
      "own-password",
      "metrics",
      "fleet",
      "instances",
      "incidents",
      "system-observation",
      "system-sources",
      "observation-catalog",
      "rulesets",
    ],
    "x-pending-capabilities": [],
    servers: [{ url: "/" }],
    paths,
    components: {
      securitySchemes: {
        BrowserSession: {
          type: "apiKey",
          in: "cookie",
          name: "sentinel_session",
          description:
            "HttpOnly server session; may be anonymous only on explicitly anonymous endpoints. Role/capability checked per request.",
        },
        BootstrapOperator: {
          type: "apiKey",
          in: "cookie",
          name: "sentinel_bootstrap",
          description:
            "HttpOnly bounded operator grant; not an administrator session. Original safe lookup only after completion.",
        },
        CsrfCookie: {
          type: "apiKey",
          in: "cookie",
          name: "__Host-sentinel_csrf",
          description:
            "Double-submit CSRF proof only; must match the required x-sentinel-csrf header and grants no identity.",
        },
      },
    },
  };
}
