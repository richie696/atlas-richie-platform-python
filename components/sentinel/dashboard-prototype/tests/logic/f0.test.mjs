import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { createAccountStore } from "../../src/features/identity/state/accountStore";
import { ACCOUNT_STATUS, IDENTITY_ROLE } from "../../src/features/identity/model/account";
import {
  findApplication,
  findInstance,
} from "../../src/features/applications/model/instancePolicy";
import {
  resolveAppIdForRoute,
  ROUTE,
  ALL_APPLICATIONS,
} from "../../src/app/router/route.constants";

const admin = Object.freeze({
  id: "test-admin",
  username: "admin",
  roleId: IDENTITY_ROLE.Admin,
  status: ACCOUNT_STATUS.Active,
  builtIn: true,
  lastLoginAt: "sample",
});

describe("F0.3 account initialization and mutation ownership", () => {
  it("does not overwrite creates, role changes or status changes on repeated initialization", () => {
    const store = createAccountStore();
    const owner = {};
    store.initialize(owner, [admin]);
    store.add({ ...admin, id: "test-view", username: "viewer", builtIn: false });
    store.setRole("test-view", IDENTITY_ROLE.View);
    store.setStatus("test-view", ACCOUNT_STATUS.Disabled);
    const changed = store.getSnapshot();
    store.initialize(owner, [admin]);
    assert.strictEqual(store.getSnapshot(), changed);
    assert.equal(changed.accounts[1].roleId, IDENTITY_ROLE.View);
    assert.equal(changed.accounts[1].status, ACCOUNT_STATUS.Disabled);
  });

  it("reinitializes only when the owner changes, and still allows explicit refresh", () => {
    const store = createAccountStore();
    store.initialize({}, [admin]);
    store.initialize({}, []);
    assert.deepEqual(store.getSnapshot().accounts, []);
    store.load([admin]);
    assert.equal(store.getSnapshot().accounts.length, 1);
  });

  it("keeps empty initialization idempotent rather than using length as an initialization flag", () => {
    const store = createAccountStore();
    const owner = {};
    store.initialize(owner, []);
    const snapshot = store.getSnapshot();
    store.initialize(owner, [admin]);
    assert.strictEqual(store.getSnapshot(), snapshot);
  });

  it("unknown/no-op writes keep the same snapshot and unsubscribe is idempotent", () => {
    const store = createAccountStore();
    store.initialize({}, [admin]);
    const snapshot = store.getSnapshot();
    let notifications = 0;
    const unsubscribe = store.subscribe(() => notifications++);
    store.setStatus("missing", ACCOUNT_STATUS.Disabled);
    store.setRole(admin.id, admin.roleId);
    assert.strictEqual(store.getSnapshot(), snapshot);
    assert.equal(notifications, 0);
    store.setStatus(admin.id, ACCOUNT_STATUS.Disabled);
    assert.equal(notifications, 1);
    unsubscribe();
    unsubscribe();
    store.setStatus(admin.id, ACCOUNT_STATUS.Active);
    assert.equal(notifications, 1);
  });
});

describe("F0.4 selection is not an implicit permission to use another target", () => {
  it("empty directories and explicit missing targets remain missing", () => {
    assert.equal(findApplication([], "missing"), null);
    assert.equal(findApplication([{ id: "present" }], "missing"), null);
    assert.equal(findInstance([{ id: "present" }], "missing"), null);
  });
  it("application observations use the authorized catalog; only single-target routes resolve a default", () => {
    assert.equal(
      resolveAppIdForRoute(ROUTE.Applications, ALL_APPLICATIONS, ["present"]),
      ALL_APPLICATIONS,
    );
    assert.equal(resolveAppIdForRoute(ROUTE.Applications, "missing", ["present"]), "missing");
    assert.equal(resolveAppIdForRoute(ROUTE.Rules, ALL_APPLICATIONS, ["present"]), ALL_APPLICATIONS);
    assert.equal(resolveAppIdForRoute(ROUTE.Rules, ALL_APPLICATIONS, []), ALL_APPLICATIONS);
  });
});
