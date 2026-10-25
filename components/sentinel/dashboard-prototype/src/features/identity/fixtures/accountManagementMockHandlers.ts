import { http, HttpResponse } from "msw";
import { CONSOLE_HEADER, parseIdempotencyKeyHeader } from "../../../core/api/protocol/common";
import {
  readMockPrincipal,
  writeMockPassword,
  writeMockPrincipal,
} from "../../../core/api/mock/mockRole";
import { ACCOUNT_STATUS, canonicalizeAccountUsername, IDENTITY_ROLE } from "../model/account";
import { AccountMutationSchema, AccountListQuerySchema } from "../api/accountManagementWire";
import { AccountPageSchema } from "../api/accountManagementWire";
import type { AccountMutation } from "../api/accountManagementPort";
import type { IdentityMockScenario } from "../mock";

interface MockAccount {
  id: string;
  username: string;
  roleId: "admin" | "view";
  status: "active" | "disabled";
  builtIn: boolean;
  lastLoginAt: string | null;
  revision: string;
  lastActiveAdmin: boolean;
}

/** Create isolated account-management handlers with state scoped to this Mock server. */
export function createAccountManagementMockHandlers(
  scenario: IdentityMockScenario,
  now: () => number = Date.now,
) {
  let nextRevision = 1;
  const state = {
    accounts: new Map<string, MockAccount>(
      scenario.accounts.map(({ lastLoginOffsetMs, ...account }) => [
        account.id,
        {
          ...account,
          lastLoginAt: new Date(now() + lastLoginOffsetMs).toISOString(),
          revision: String(nextRevision++),
          lastActiveAdmin: false,
        },
      ]),
    ),
    operations: new Map<string, { input: string; result: Record<string, unknown> }>(),
    revision: nextRevision,
    sequence: 0,
    deletedIds: new Set<string>(),
  };

  const responseHeaders = (requestId: string | null, includeCsrf = true) => {
    const headers = new Headers({ "Content-Type": "application/json" });
    if (requestId) headers.set(CONSOLE_HEADER.RequestId, requestId);
    if (includeCsrf) headers.set(CONSOLE_HEADER.Csrf, "M".repeat(48));
    return headers;
  };
  const json = (requestId: string | null, body: unknown, status = 200) =>
    new HttpResponse(JSON.stringify(body), { status, headers: responseHeaders(requestId) });
  const problem = (requestId: string | null, code: string, status: number) =>
    json(requestId, { error: { code, requestId } }, status);
  let fingerprintKey: Promise<CryptoKey> | undefined;
  async function commandFingerprint(input: AccountMutation): Promise<string> {
    // Mock idempotency compares opaque keyed digests, never the transient password body.
    fingerprintKey ??= crypto.subtle.generateKey({ name: "HMAC", hash: "SHA-256" }, false, [
      "sign",
    ]);
    const signature = await crypto.subtle.sign(
      "HMAC",
      await fingerprintKey,
      new TextEncoder().encode(JSON.stringify(input)),
    );
    return Array.from(new Uint8Array(signature), (byte) => byte.toString(16).padStart(2, "0")).join(
      "",
    );
  }
  const allRecords = () => [...state.accounts.values()];
  const records = () => allRecords().filter((account) => !state.deletedIds.has(account.id));
  const refreshLastAdmin = () => {
    const activeAdmins = records().filter(
      (account) =>
        account.status === ACCOUNT_STATUS.Active && account.roleId === IDENTITY_ROLE.Admin,
    );
    for (const account of records())
      account.lastActiveAdmin = activeAdmins.length === 1 && activeAdmins[0]?.id === account.id;
  };
  refreshLastAdmin();
  const isAdmin = () => readMockPrincipal() === IDENTITY_ROLE.Admin;
  const currentMockAccountId = () =>
    scenario.accounts.find((candidate) => candidate.roleId === readMockPrincipal())?.id;
  const forbidden = (requestId: string | null) => problem(requestId, "forbidden", 403);

  /** HTTP-level account command simulator. It never stores submitted password material. */
  return Object.freeze([
    http.get("*/api/v1/accounts", ({ request }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      if (!isAdmin()) return forbidden(requestId);
      const url = new URL(request.url);
      const raw = {
        page: Number(url.searchParams.get("page")),
        pageSize: Number(url.searchParams.get("pageSize")),
        search: url.searchParams.get("search") ?? "",
        ...(url.searchParams.has("status") ? { status: url.searchParams.get("status") } : {}),
      };
      const parsed = AccountListQuerySchema.safeParse(raw);
      if (!parsed.success) return problem(requestId, "invalid_request", 400);
      const normalizedSearch = canonicalizeAccountUsername(parsed.data.search);
      const filtered = records()
        .filter((account) => !parsed.data.status || account.status === parsed.data.status)
        .filter(
          (account) =>
            !normalizedSearch ||
            canonicalizeAccountUsername(account.username).includes(normalizedSearch),
        )
        .sort((left, right) => left.username.localeCompare(right.username));
      const start = (parsed.data.page - 1) * parsed.data.pageSize;
      const page = {
        items: filtered.slice(start, start + parsed.data.pageSize),
        page: parsed.data.page,
        pageSize: parsed.data.pageSize,
        total: filtered.length,
      };
      const valid = AccountPageSchema.safeParse(page);
      return valid.success
        ? json(requestId, valid.data)
        : problem(requestId, "dependency_unavailable", 503);
    }),
    http.get("*/api/v1/accounts/:accountId", ({ request, params }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      if (!isAdmin()) return forbidden(requestId);
      return json(
        requestId,
        state.deletedIds.has(String(params.accountId))
          ? null
          : (state.accounts.get(String(params.accountId)) ?? null),
      );
    }),
    http.post("*/api/v1/accounts/commands", async ({ request }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      if (!isAdmin()) return forbidden(requestId);
      if (!request.headers.get(CONSOLE_HEADER.Csrf)) return problem(requestId, "csrf_failed", 403);
      const parsed = AccountMutationSchema.safeParse(await request.json().catch(() => null));
      if (!parsed.success) return problem(requestId, "invalid_request", 400);
      const keyHeader = parseIdempotencyKeyHeader(request.headers);
      if (keyHeader.kind === "missing") return problem(requestId, "invalid_request", 400);
      if (keyHeader.kind !== "valid" || keyHeader.requestKey !== parsed.data.requestKey)
        return problem(requestId, "idempotency_conflict", 409);
      const input = parsed.data;
      const fingerprint = await commandFingerprint(input);
      const prior = state.operations.get(input.requestKey);
      if (prior)
        return prior.input === fingerprint
          ? json(requestId, prior.result)
          : problem(requestId, "idempotency_conflict", 409);

      state.sequence += 1;
      let result: Record<string, unknown>;
      if (input.kind === "create") {
        const username = input.input.username.trim();
        if (
          allRecords().some(
            (account) =>
              canonicalizeAccountUsername(account.username) ===
              canonicalizeAccountUsername(username),
          )
        ) {
          result = { status: "rejected", requestKey: input.requestKey, reason: "username_taken" };
        } else {
          const account: MockAccount = {
            id: `mock-account-${state.sequence}`,
            username,
            roleId: input.input.roleId,
            status: ACCOUNT_STATUS.Active,
            builtIn: false,
            lastLoginAt: null,
            revision: String(state.revision++),
            lastActiveAdmin: false,
          };
          state.accounts.set(account.id, account);
          refreshLastAdmin();
          result = { status: "completed", requestKey: input.requestKey, account };
        }
        // The command's password is intentionally not copied into state or operation history.
      } else {
        const account = state.accounts.get(input.accountId);
        if (!account || state.deletedIds.has(input.accountId))
          result = { status: "rejected", requestKey: input.requestKey, reason: "not_found" };
        else if (account.revision !== input.revision)
          result = { status: "rejected", requestKey: input.requestKey, reason: "conflict" };
        else if (input.kind === "delete" && account.id === currentMockAccountId())
          result = { status: "rejected", requestKey: input.requestKey, reason: "self_operation" };
        else if (
          account.builtIn &&
          !(input.kind === "reset_password" && account.id === currentMockAccountId())
        )
          result = { status: "rejected", requestKey: input.requestKey, reason: "built_in" };
        else if (
          account.lastActiveAdmin &&
          (input.kind === "delete" ||
            (input.kind === "status" && input.status !== "active") ||
            (input.kind === "role" && input.roleId !== "admin"))
        )
          result = { status: "rejected", requestKey: input.requestKey, reason: "last_admin" };
        else {
          if (input.kind === "status") account.status = input.status;
          else if (input.kind === "role") account.roleId = input.roleId;
          else if (input.kind === "delete") {
            account.status = ACCOUNT_STATUS.Disabled;
            state.deletedIds.add(account.id);
          }
          account.revision = String(state.revision++);
          refreshLastAdmin();
          result = { status: "completed", requestKey: input.requestKey, account: { ...account } };
        }
      }
      if (
        result.status === "completed" &&
        input.kind === "reset_password" &&
        input.accountId === currentMockAccountId()
      ) {
        const account = state.accounts.get(input.accountId);
        if (account) writeMockPassword(account.username, input.password);
        writeMockPrincipal(null);
      }
      state.operations.set(input.requestKey, { input: fingerprint, result });
      return json(requestId, result);
    }),
    http.get("*/api/v1/accounts/operations/:requestKey", ({ request, params }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      if (!isAdmin()) return forbidden(requestId);
      const requestKey = String(params.requestKey);
      return json(
        requestId,
        state.operations.get(requestKey)?.result ?? { status: "not-found", requestKey },
      );
    }),
    http.post("*/api/v1/auth/password", async ({ request }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      if (!readMockPrincipal()) return problem(requestId, "unauthenticated", 401);
      if (!request.headers.get(CONSOLE_HEADER.Csrf)) return problem(requestId, "csrf_failed", 403);
      const body: unknown = await request.json().catch(() => null);
      if (
        !body ||
        typeof body !== "object" ||
        !("currentPassword" in body) ||
        !("newPassword" in body)
      )
        return problem(requestId, "invalid_request", 400);
      return json(requestId, { sessionDisposition: "reauthenticate" });
    }),
  ]);
}
