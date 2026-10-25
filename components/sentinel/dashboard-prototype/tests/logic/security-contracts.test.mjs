import assert from "node:assert/strict";
import { test } from "node:test";
import { createAuthenticationWorkflow } from "../../src/features/identity/application/authenticationWorkflow";
import { pathFor, ROUTE } from "../../src/app/router/route.constants";

test("F7.2 authentication secrets stay out of browser storage, snapshots, and generated routes", async () => {
  const localStorageWrites = [];
  const sessionStorageWrites = [];
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  const createStorage = (writes) => ({
    getItem: () => null,
    setItem: (key, value) => writes.push([key, value]),
    removeItem: () => {},
    clear: () => {},
  });
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      localStorage: createStorage(localStorageWrites),
      sessionStorage: createStorage(sessionStorageWrites),
    },
  });

  let dispatchedCredentials;
  let authenticated = false;
  const identity = {
    accountId: "account-security-test",
    username: "synthetic-viewer",
    roleId: "view",
    capabilities: ["metrics:view"],
    sessionEpoch: "synthetic-session-epoch",
  };
  const workflow = createAuthenticationWorkflow({
    readBootstrap: async () => ({ initialized: true }),
    readSession: async () => (authenticated ? identity : null),
    login: async (credentials) => {
      dispatchedCredentials = credentials;
      authenticated = true;
      return identity;
    },
    logout: async () => {},
  });

  try {
    await workflow.restore();
    await workflow.login({ username: identity.username, password: "F7.2-SYNTHETIC-PASSWORD" });

    assert.equal(dispatchedCredentials.password, "F7.2-SYNTHETIC-PASSWORD");
    assert.deepEqual(
      localStorageWrites,
      [],
      "submitted credentials are not written to localStorage",
    );
    assert.deepEqual(
      sessionStorageWrites,
      [],
      "submitted credentials are not written to sessionStorage",
    );
    assert.doesNotMatch(JSON.stringify(workflow.getSnapshot()), /F7\.2-SYNTHETIC-PASSWORD/);

    const loginPath = pathFor(ROUTE.Login, {
      returnTo: ROUTE.Rules,
      username: identity.username,
      password: "F7.2-SYNTHETIC-PASSWORD",
      token: "F7.2-SYNTHETIC-TOKEN",
    });
    assert.equal(loginPath, "#/login?returnTo=rules");
    assert.doesNotMatch(loginPath, /synthetic-viewer|F7\.2-SYNTHETIC/);
  } finally {
    workflow.dispose();
    if (previousWindow) Object.defineProperty(globalThis, "window", previousWindow);
    else delete globalThis.window;
  }
});
