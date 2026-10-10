import assert from "node:assert/strict";
import { test } from "node:test";
import { setupServer } from "msw/node";
import {
  createAccountManagementMockHandlers,
  createIdentityMockHandlers,
} from "../../src/features/identity/mock";
import { MOCK_IDENTITY_SCENARIO } from "../../src/app/api/mockIdentityScenario";
import { MOCK_ROLE_STORAGE_KEY } from "../../src/core/api/mock/mockRole";

test("ACCOUNT-MOCK-IDENTITY: HTTP mock rejects trimmed, case and NFKC duplicate usernames", async () => {
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      localStorage: {
        getItem: (key) => (key === MOCK_ROLE_STORAGE_KEY ? "admin" : null),
      },
    },
  });
  const server = setupServer(...createAccountManagementMockHandlers(MOCK_IDENTITY_SCENARIO));
  server.listen({ onUnhandledRequest: "error" });
  try {
    for (const [index, username] of [" Admin ", "Ａdmin"].entries()) {
      const response = await fetch("http://identity-mock.test/api/v1/accounts/commands", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-request-id": `account-identity-${index}`,
          "x-sentinel-csrf": "C".repeat(48),
          "idempotency-key": `identity-${index}`,
        },
        body: JSON.stringify({
          kind: "create",
          requestKey: `identity-${index}`,
          input: { username, password: "SYNTHETIC-PRIVATE-PASSWORD", roleId: "view" },
        }),
      });
      const receipt = await response.json();
      assert.equal(response.status, 200);
      assert.deepEqual(receipt, {
        status: "rejected",
        requestKey: `identity-${index}`,
        reason: "username_taken",
      });
      assert.equal(JSON.stringify(receipt).includes("SYNTHETIC-PRIVATE-PASSWORD"), false);
    }
  } finally {
    server.close();
    if (previousWindow) Object.defineProperty(globalThis, "window", previousWindow);
    else delete globalThis.window;
  }
});

test("ACCOUNT-MOCK-IDENTITY: missing or malformed browser role storage cannot authorize admin reads", async () => {
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  let stored = null;
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      localStorage: {
        getItem: (key) => (key === MOCK_ROLE_STORAGE_KEY ? stored : null),
      },
    },
  });
  const server = setupServer(...createAccountManagementMockHandlers(MOCK_IDENTITY_SCENARIO));
  server.listen({ onUnhandledRequest: "error" });
  try {
    for (const value of [null, "administrator", "unexpected-role"]) {
      stored = value;
      const response = await fetch("http://identity-mock.test/api/v1/accounts?page=1&pageSize=20", {
        headers: { "x-request-id": "missing-role" },
      });
      assert.equal(response.status, 403);
    }
  } finally {
    server.close();
    if (previousWindow) Object.defineProperty(globalThis, "window", previousWindow);
    else delete globalThis.window;
  }
});

test("ACCOUNT-MOCK-QUERY: search, status filters and page boundaries are applied by the HTTP mock", async () => {
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      localStorage: {
        getItem: (key) => (key === MOCK_ROLE_STORAGE_KEY ? "admin" : null),
      },
    },
  });
  const server = setupServer(...createAccountManagementMockHandlers(MOCK_IDENTITY_SCENARIO));
  server.listen({ onUnhandledRequest: "error" });
  try {
    const readPage = async (query, requestId) => {
      const response = await fetch(`http://identity-mock.test/api/v1/accounts?${query}`, {
        headers: { "x-request-id": requestId },
      });
      return { status: response.status, page: await response.json() };
    };

    const first = await readPage("page=1&pageSize=1&search=&status=active", "account-page-one");
    const second = await readPage("page=2&pageSize=1&search=&status=active", "account-page-two");
    const searched = await readPage(
      "page=1&pageSize=20&search=VIEW&status=active",
      "account-search",
    );
    const disabled = await readPage(
      "page=1&pageSize=20&search=&status=disabled",
      "account-disabled-filter",
    );

    assert.equal(first.status, 200);
    assert.equal(first.page.total, 2);
    assert.deepEqual(
      [first.page.page, first.page.pageSize, first.page.items[0].username],
      [1, 1, "admin"],
    );
    assert.deepEqual([second.page.page, second.page.pageSize, second.page.total], [2, 1, 2]);
    assert.equal(second.page.items[0].username, "viewer");
    assert.deepEqual([searched.page.total, searched.page.items[0].username], [1, "viewer"]);
    assert.deepEqual([disabled.page.total, disabled.page.items.length], [0, 0]);
  } finally {
    server.close();
    if (previousWindow) Object.defineProperty(globalThis, "window", previousWindow);
    else delete globalThis.window;
  }
});

test("ACCOUNT-MOCK-COMMAND-STATE: role/status writes update the directory and replay idempotently", async () => {
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      localStorage: {
        getItem: (key) => (key === MOCK_ROLE_STORAGE_KEY ? "admin" : null),
      },
    },
  });
  const server = setupServer(...createAccountManagementMockHandlers(MOCK_IDENTITY_SCENARIO));
  server.listen({ onUnhandledRequest: "error" });
  try {
    const mutate = async (input) => {
      const response = await fetch("http://identity-mock.test/api/v1/accounts/commands", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-request-id": `account-mutation-${input.requestKey}`,
          "x-sentinel-csrf": "C".repeat(48),
          "idempotency-key": input.requestKey,
        },
        body: JSON.stringify(input),
      });
      return { status: response.status, result: await response.json() };
    };
    const promote = {
      kind: "role",
      requestKey: "mock-promote-viewer",
      accountId: "account-view",
      revision: "2",
      roleId: "admin",
    };
    const promoted = await mutate(promote);
    assert.equal(promoted.status, 200);
    assert.equal(promoted.result.status, "completed");
    assert.equal(promoted.result.account.roleId, "admin");
    assert.deepEqual(await mutate(promote), promoted);

    const disable = {
      kind: "status",
      requestKey: "mock-disable-viewer",
      accountId: "account-view",
      revision: promoted.result.account.revision,
      status: "disabled",
    };
    const disabled = await mutate(disable);
    assert.equal(disabled.result.status, "completed");
    assert.equal(disabled.result.account.status, "disabled");
    assert.equal(disabled.result.account.lastActiveAdmin, false);

    const pageResponse = await fetch(
      "http://identity-mock.test/api/v1/accounts?page=1&pageSize=20&search=&status=disabled",
      { headers: { "x-request-id": "account-disabled-read" } },
    );
    const page = await pageResponse.json();
    assert.equal(page.total, 1);
    assert.deepEqual(
      [page.items[0].id, page.items[0].roleId, page.items[0].status],
      ["account-view", "admin", "disabled"],
    );
  } finally {
    server.close();
    if (previousWindow) Object.defineProperty(globalThis, "window", previousWindow);
    else delete globalThis.window;
  }
});

test("IDENTITY-MOCK-SEED: login, session restoration, and account directory share canonical identities", async () => {
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  const values = new Map([
    ["sentinel.mock.initialized", "true"],
    [MOCK_ROLE_STORAGE_KEY, "anonymous"],
  ]);
  const scenarioNow = Date.parse("2026-10-09T00:00:00.000Z");
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      localStorage: {
        getItem: (key) => values.get(key) ?? null,
        setItem: (key, value) => values.set(key, value),
        removeItem: (key) => values.delete(key),
      },
    },
  });
  const server = setupServer(
    ...createIdentityMockHandlers(MOCK_IDENTITY_SCENARIO),
    ...createAccountManagementMockHandlers(MOCK_IDENTITY_SCENARIO, () => scenarioNow),
  );
  server.listen({ onUnhandledRequest: "error" });
  try {
    let requestId = 0;
    const send = (path, init = {}) =>
      fetch(`http://identity-mock.test${path}`, {
        ...init,
        headers: {
          "x-request-id": `identity-seed-${++requestId}`,
          ...(init.body ? { "content-type": "application/json" } : {}),
          ...init.headers,
        },
      });
    const administrator = MOCK_IDENTITY_SCENARIO.accounts[0];
    const login = await send("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({
        username: administrator.username,
        password: MOCK_IDENTITY_SCENARIO.password,
      }),
    });
    assert.equal(login.status, 200);
    const administratorSession = await login.json();
    assert.deepEqual(administratorSession, {
      accountId: administrator.id,
      username: administrator.username,
      roleId: administrator.roleId,
      capabilities: ["metrics:view", "rules:write"],
      sessionEpoch: "mock-session-admin",
    });
    assert.deepEqual(await (await send("/api/v1/auth/me")).json(), administratorSession);

    const directory = await send("/api/v1/accounts?page=1&pageSize=20");
    assert.equal(directory.status, 200);
    const listed = await directory.json();
    assert.deepEqual(
      listed.items.map(({ id, username, roleId, status, builtIn }) => ({
        id,
        username,
        roleId,
        status,
        builtIn,
      })),
      MOCK_IDENTITY_SCENARIO.accounts.map(({ id, username, roleId, status, builtIn }) => ({
        id,
        username,
        roleId,
        status,
        builtIn,
      })),
    );
    assert.deepEqual(
      listed.items.map(({ lastLoginAt }) => lastLoginAt),
      MOCK_IDENTITY_SCENARIO.accounts.map(({ lastLoginOffsetMs }) =>
        new Date(scenarioNow + lastLoginOffsetMs).toISOString(),
      ),
    );
    assert.equal(JSON.stringify(listed).includes(MOCK_IDENTITY_SCENARIO.password), false);

    const viewer = MOCK_IDENTITY_SCENARIO.accounts[1];
    const viewerLogin = await send("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({
        username: viewer.username,
        password: MOCK_IDENTITY_SCENARIO.password,
      }),
    });
    assert.equal(viewerLogin.status, 200);
    assert.deepEqual(await viewerLogin.json(), {
      accountId: viewer.id,
      username: viewer.username,
      roleId: viewer.roleId,
      capabilities: ["metrics:view"],
      sessionEpoch: "mock-session-view",
    });
    assert.equal((await send("/api/v1/accounts?page=1&pageSize=20")).status, 403);
  } finally {
    server.close();
    if (previousWindow) Object.defineProperty(globalThis, "window", previousWindow);
    else delete globalThis.window;
  }
});

test("ACCOUNT-MOCK-ISOLATION: account state and idempotency history belong to one handler factory", async () => {
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: { localStorage: { getItem: (key) => (key === MOCK_ROLE_STORAGE_KEY ? "admin" : null) } },
  });
  try {
    const firstServer = setupServer(...createAccountManagementMockHandlers(MOCK_IDENTITY_SCENARIO));
    firstServer.listen({ onUnhandledRequest: "error" });
    try {
      const created = await fetch("http://identity-mock.test/api/v1/accounts/commands", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-request-id": "isolated-account-create",
          "x-sentinel-csrf": "C".repeat(48),
          "idempotency-key": "isolated-account-operation",
        },
        body: JSON.stringify({
          kind: "create",
          requestKey: "isolated-account-operation",
          input: {
            username: "temporary-operator",
            password: "SYNTHETIC-PRIVATE-PASSWORD",
            roleId: "view",
          },
        }),
      });
      assert.equal(created.status, 200);
      assert.equal((await created.json()).status, "completed");
      const directory = await fetch(
        "http://identity-mock.test/api/v1/accounts?page=1&pageSize=20&search=temporary-operator&status=active",
        { headers: { "x-request-id": "isolated-account-no-secret" } },
      );
      const serialized = JSON.stringify(await directory.json());
      assert.match(serialized, /temporary-operator/);
      assert.doesNotMatch(serialized, /SYNTHETIC-PRIVATE-PASSWORD/);
      const receipt = await fetch(
        "http://identity-mock.test/api/v1/accounts/operations/isolated-account-operation",
        { headers: { "x-request-id": "isolated-account-receipt" } },
      );
      assert.doesNotMatch(await receipt.text(), /SYNTHETIC-PRIVATE-PASSWORD/);
    } finally {
      firstServer.close();
    }

    const secondServer = setupServer(
      ...createAccountManagementMockHandlers(MOCK_IDENTITY_SCENARIO),
    );
    secondServer.listen({ onUnhandledRequest: "error" });
    try {
      const response = await fetch("http://identity-mock.test/api/v1/accounts?page=1&pageSize=20", {
        headers: { "x-request-id": "isolated-account-read" },
      });
      const page = await response.json();
      assert.equal(response.status, 200);
      assert.equal(page.total, MOCK_IDENTITY_SCENARIO.accounts.length);
      assert.equal(
        page.items.some(({ username }) => username === "temporary-operator"),
        false,
      );
    } finally {
      secondServer.close();
    }
  } finally {
    if (previousWindow) Object.defineProperty(globalThis, "window", previousWindow);
    else delete globalThis.window;
  }
});
