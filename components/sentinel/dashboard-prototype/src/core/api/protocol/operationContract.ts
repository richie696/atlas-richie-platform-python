import type { z } from "zod";
import type { ConsoleEndpoint } from "../transport/consoleEndpoint";

export const CONSOLE_CAPABILITY = Object.freeze({
  MetricsView: "metrics:view",
  RulesWrite: "rules:write",
} as const);

export type ConsoleCapability = (typeof CONSOLE_CAPABILITY)[keyof typeof CONSOLE_CAPABILITY];

export const CONSOLE_REQUIRED_ROLE = Object.freeze({ Admin: "admin" } as const);

export type ConsoleRequiredRole =
  (typeof CONSOLE_REQUIRED_ROLE)[keyof typeof CONSOLE_REQUIRED_ROLE];

/** Explicit role/capability gates in addition to the endpoint's cookie/session security. */
export interface ConsoleAccessRequirement {
  readonly role: ConsoleRequiredRole | null;
  readonly capabilities: readonly ConsoleCapability[];
}

/** A schema-backed HTTP exchange example published with its operation contract. */
export interface ConsoleOperationExample {
  readonly name: string;
  readonly summary: string;
  readonly kind: "positive" | "negative";
  readonly request: {
    readonly pathParameters?: Readonly<Record<string, string>>;
    readonly queryParameters?: Readonly<Record<string, string | number | boolean>>;
    readonly body?: unknown;
    /** False only when this example intentionally demonstrates request-schema rejection. */
    readonly bodyConforms?: boolean;
  };
  readonly response: {
    readonly status: number;
    readonly body?: unknown;
  };
}

/** Reusable immutable access declarations; endpoint security separately describes credentials. */
export const CONSOLE_ACCESS = Object.freeze({
  None: Object.freeze({ role: null, capabilities: Object.freeze([]) }),
  Admin: Object.freeze({ role: CONSOLE_REQUIRED_ROLE.Admin, capabilities: Object.freeze([]) }),
  MetricsView: Object.freeze({
    role: null,
    capabilities: Object.freeze([CONSOLE_CAPABILITY.MetricsView]),
  }),
  RulesWrite: Object.freeze({
    role: null,
    capabilities: Object.freeze([CONSOLE_CAPABILITY.RulesWrite]),
  }),
  AdminRulesWrite: Object.freeze({
    role: CONSOLE_REQUIRED_ROLE.Admin,
    capabilities: Object.freeze([CONSOLE_CAPABILITY.RulesWrite]),
  }),
} satisfies Readonly<Record<string, ConsoleAccessRequirement>>);

/** Machine documentation inputs are projected from the same runtime endpoint/schema, never a competing DTO implementation. */
export interface ConsoleOperationContract {
  readonly operationId: string;
  readonly summary: string;
  readonly tag: string;
  /** Anonymous operations allow no session or an optional BrowserSession; CSRF is composed separately. */
  readonly security: "public" | "anonymous" | "session" | "bootstrap" | "optional-bootstrap";
  /** Extra server-side authorization gates; does not replace security or resource-level checks. */
  readonly requiredAccess: ConsoleAccessRequirement;
  readonly endpoint: Omit<ConsoleEndpoint<unknown>, "accept">;
  readonly input: z.ZodType | null;
  readonly pathParameters: readonly { readonly name: string; readonly schema: z.ZodType }[];
  readonly queryParameters?: readonly { readonly name: string; readonly schema: z.ZodType }[];
  readonly semanticRules: readonly string[];
  /** Optional concrete wire exchanges. The contract test validates each body against these schemas. */
  readonly examples?: readonly ConsoleOperationExample[];
}
