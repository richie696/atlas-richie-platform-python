import { http, HttpResponse } from "msw";
import { CONSOLE_HEADER, parseIdempotencyKeyHeader } from "../../../core/api/protocol/common";
import {
  readMockPassword,
  readMockPrincipal,
  writeMockPrincipal,
} from "../../../core/api/mock/mockRole";
import { canonicalizeAccountUsername, IDENTITY_ROLE } from "../model/account";
import {
  BootstrapAuthorizationInputSchema,
  InitializeCommandSchema,
  SetupStorageSchema,
} from "../api/identityWire";
import { ConfigurationSourceInputSchema } from "../../../shared/api/configurationSourceWire";
import type { IdentityMockScenario } from "../mock";

function setupFacts(scenario: IdentityMockScenario) {
  const storedInitialization = window.localStorage.getItem(scenario.storageKeys.initialized);
  const initialized =
    storedInitialization === null
      ? scenario.bootstrap.initializedByDefault
      : storedInitialization !== "false";
  if (initialized) return { initialized: true as const };
  const storedOperatorAuthorization = window.localStorage.getItem(
    scenario.storageKeys.operatorAuthorized,
  );
  return {
    initialized: false as const,
    setupAvailable: true,
    operatorAuthorized:
      storedOperatorAuthorization === null
        ? scenario.bootstrap.operatorAuthorizedByDefault
        : storedOperatorAuthorization === "true",
  };
}

function consumeMockFailure(key: string, scenario: IdentityMockScenario): boolean {
  if (window.localStorage.getItem(key) !== scenario.failureMode.failOnce) return false;
  window.localStorage.removeItem(key);
  return true;
}

function dependencyUnavailable(requestId: string | null) {
  return HttpResponse.json(
    { error: { code: "service_unavailable", requestId } },
    { status: 503, headers: headers(requestId, false) },
  );
}

async function setupFingerprint(key: Promise<CryptoKey>, value: unknown): Promise<string> {
  const output = await crypto.subtle.sign(
    "HMAC",
    await key,
    new TextEncoder().encode(JSON.stringify(value)),
  );
  return Array.from(new Uint8Array(output), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

const headers = (requestId: string | null, csrf = true) => {
  const result = new Headers({ "Content-Type": "application/json" });
  if (requestId) result.set(CONSOLE_HEADER.RequestId, requestId);
  if (csrf) result.set(CONSOLE_HEADER.Csrf, "M".repeat(48));
  return result;
};

function sessionFor(role: "admin" | "view", scenario: IdentityMockScenario) {
  const account = scenario.accounts.find((candidate) => candidate.roleId === role);
  if (!account) throw new Error("Mock identity seed is missing a role account");
  return {
    accountId: account.id,
    username: account.username,
    roleId: role,
    capabilities: role === IDENTITY_ROLE.Admin ? ["metrics:view", "rules:write"] : ["metrics:view"],
    sessionEpoch: `mock-session-${role}`,
  };
}

/** Create isolated identity HTTP handlers for the explicit local Mock profile. */
export function createIdentityMockHandlers(scenario: IdentityMockScenario) {
  const setupOperations = new Map<
    string,
    {
      readonly fingerprint: string;
      readonly receipt: {
        readonly status: "completed";
        readonly requestKey: string;
        readonly operationId: string;
      };
    }
  >();
  let setupFingerprintKey: Promise<CryptoKey> | undefined;
  const getSetupFingerprint = (value: unknown) => {
    setupFingerprintKey ??= crypto.subtle.generateKey({ name: "HMAC", hash: "SHA-256" }, false, [
      "sign",
    ]);
    return setupFingerprint(setupFingerprintKey, value);
  };
  return Object.freeze([
    http.get("*/api/v1/system/bootstrap", ({ request }) =>
      HttpResponse.json(setupFacts(scenario), {
        headers: headers(request.headers.get(CONSOLE_HEADER.RequestId)),
      }),
    ),
    http.post("*/api/v1/system/bootstrap/authorize", async ({ request }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      const input = BootstrapAuthorizationInputSchema.safeParse(
        await request.json().catch(() => null),
      );
      const facts = setupFacts(scenario);
      const setupAvailable = !facts.initialized && facts.setupAvailable;
      if (!input.success || !setupAvailable)
        return HttpResponse.json(
          { error: { code: setupAvailable ? "invalid_request" : "conflict", requestId } },
          { status: setupAvailable ? 400 : 409, headers: headers(requestId, false) },
        );
      window.localStorage.setItem(scenario.storageKeys.operatorAuthorized, "true");
      return HttpResponse.json({ authorized: true }, { headers: headers(requestId) });
    }),
    http.post("*/api/v1/system/bootstrap/authorize-local", async ({ request }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      const facts = setupFacts(scenario);
      const setupAvailable = !facts.initialized && facts.setupAvailable;
      if (!setupAvailable)
        return HttpResponse.json(
          { error: { code: "conflict", requestId } },
          { status: 409, headers: headers(requestId, false) },
        );
      window.localStorage.setItem(scenario.storageKeys.operatorAuthorized, "true");
      return HttpResponse.json({ authorized: true }, { headers: headers(requestId) });
    }),
    http.post("*/api/v1/system/bootstrap/database-check", async ({ request }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      const input = SetupStorageSchema.safeParse(await request.json().catch(() => null));
      if (!input.success)
        return HttpResponse.json(
          { error: { code: "invalid_request", requestId } },
          { status: 400, headers: headers(requestId, false) },
        );
      return consumeMockFailure(scenario.storageKeys.databaseCheckFailure, scenario)
        ? dependencyUnavailable(requestId)
        : HttpResponse.json({ status: "reachable" }, { headers: headers(requestId) });
    }),
    http.post("*/api/v1/system/bootstrap/source-check", async ({ request }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      const input = ConfigurationSourceInputSchema.safeParse(
        await request.json().catch(() => null),
      );
      if (!input.success)
        return HttpResponse.json(
          { error: { code: "invalid_request", requestId } },
          { status: 400, headers: headers(requestId, false) },
        );
      return consumeMockFailure(scenario.storageKeys.sourceCheckFailure, scenario)
        ? dependencyUnavailable(requestId)
        : HttpResponse.json({ status: "reachable" }, { headers: headers(requestId) });
    }),
    http.post("*/api/v1/system/bootstrap/initialize", async ({ request }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      const parsed = InitializeCommandSchema.safeParse(await request.json().catch(() => null));
      const facts = setupFacts(scenario);
      if (!parsed.success)
        return HttpResponse.json(
          { error: { code: "invalid_request", requestId } },
          { status: 400, headers: headers(requestId, false) },
        );
      const keyHeader = parseIdempotencyKeyHeader(request.headers);
      if (keyHeader.kind === "missing")
        return HttpResponse.json(
          { error: { code: "invalid_request", requestId } },
          { status: 400, headers: headers(requestId, false) },
        );
      if (keyHeader.kind !== "valid" || keyHeader.requestKey !== parsed.data.requestKey)
        return HttpResponse.json(
          { error: { code: "idempotency_conflict", requestId } },
          { status: 409, headers: headers(requestId, false) },
        );
      if (facts.initialized || !facts.operatorAuthorized)
        return HttpResponse.json(
          { error: { code: "bootstrap_unauthorized", requestId } },
          { status: 403, headers: headers(requestId, false) },
        );
      const { requestKey, input } = parsed.data;
      const requestFingerprint = await getSetupFingerprint(input);
      const existing = setupOperations.get(requestKey);
      if (existing)
        return HttpResponse.json(
          existing.fingerprint === requestFingerprint
            ? existing.receipt
            : { error: { code: "idempotency_conflict", requestId } },
          {
            status: existing.fingerprint === requestFingerprint ? 200 : 409,
            headers: headers(requestId, existing.fingerprint === requestFingerprint),
          },
        );
      const receipt = {
        status: "completed" as const,
        requestKey,
        operationId: `mock-initialization-${setupOperations.size + 1}`,
      };
      setupOperations.set(requestKey, { fingerprint: requestFingerprint, receipt });
      // Mock state keeps no submitted DB/source/admin secret or full initialization body.
      window.localStorage.setItem(scenario.storageKeys.initialized, "true");
      window.localStorage.removeItem(scenario.storageKeys.operatorAuthorized);
      return HttpResponse.json(receipt, { headers: headers(requestId) });
    }),
    http.get("*/api/v1/system/bootstrap/operations/:requestKey", ({ request, params }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      const requestKey = String(params.requestKey);
      const operation = setupOperations.get(requestKey);
      return HttpResponse.json(operation?.receipt ?? { status: "not-found", requestKey }, {
        headers: headers(requestId, false),
      });
    }),
    http.get("*/api/v1/auth/me", ({ request }) => {
      const role = readMockPrincipal();
      return HttpResponse.json(role ? sessionFor(role, scenario) : null, {
        headers: headers(request.headers.get(CONSOLE_HEADER.RequestId)),
      });
    }),
    http.post("*/api/v1/auth/login", async ({ request }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      const body: unknown = await request.json().catch(() => null);
      if (
        !body ||
        typeof body !== "object" ||
        !("username" in body) ||
        typeof body.username !== "string" ||
        !body.username.trim() ||
        !("password" in body) ||
        typeof body.password !== "string" ||
        !body.password
      )
        return HttpResponse.json(
          { error: { code: "unauthenticated", requestId } },
          { status: 401, headers: headers(requestId, false) },
        );
      const username = canonicalizeAccountUsername(body.username);
      const account = scenario.accounts.find(
        (candidate) => canonicalizeAccountUsername(candidate.username) === username,
      );
      if (!account || body.password !== readMockPassword(account.username, scenario.password))
        return HttpResponse.json(
          { error: { code: "unauthenticated", requestId } },
          { status: 401, headers: headers(requestId, false) },
        );
      writeMockPrincipal(account.roleId);
      return HttpResponse.json(sessionFor(account.roleId, scenario), {
        headers: headers(requestId),
      });
    }),
    http.post("*/api/v1/auth/logout", ({ request }) => {
      writeMockPrincipal(null);
      return new HttpResponse(null, {
        status: 204,
        headers: headers(request.headers.get(CONSOLE_HEADER.RequestId), false),
      });
    }),
  ]);
}
