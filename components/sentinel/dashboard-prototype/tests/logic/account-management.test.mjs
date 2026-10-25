import assert from "node:assert/strict";
import { test } from "node:test";
import {
  ACCOUNT_SEARCH_MAX_LENGTH,
  boundAccountSearch,
  prepareAccountCreation,
  validateAccountQuery,
  accountStatusIssue,
  accountRoleIssue,
  createRoleDraft,
  createRoleDraftSnapshot,
  changeRoleDraft,
  reconcileRoleDraft,
  restoreRoleDraftSnapshot,
  roleDraftIsDirty,
} from "../../src/features/identity/model/accountManagement";
import {
  readRoleDraftSession,
  roleDraftSessionKey,
  writeRoleDraftSession,
} from "../../src/features/identity/state/roleDraftSession";
import { canonicalizeAccountUsername } from "../../src/features/identity/model/account";
import {
  PASSWORD_MAX_LENGTH,
  PASSWORD_MIN_LENGTH,
} from "../../src/features/identity/model/passwordPolicy";
import {
  roleEditRestrictionCopy,
  roleTargetFallbackCopy,
} from "../../src/features/identity/presentation/rolePresentation";
import { accountStatusRestrictionCopy } from "../../src/features/identity/presentation/accountStatusPresentation";
import {
  generateAccountPassword,
  GENERATED_ACCOUNT_PASSWORD_LENGTH,
} from "../../src/features/identity/application/generateAccountPassword";

const record = Object.freeze({
  id: "record-one",
  username: "operator",
  roleId: "admin",
  status: "active",
  builtIn: false,
  lastActiveAdmin: false,
  lastLoginAt: null,
  revision: "9007199254740993",
});
test("ACCOUNT-PASSWORD-GENERATOR: secure entropy produces policy-compliant editable passwords; unavailable randomness fails closed", () => {
  let calls = 0;
  const password = generateAccountPassword({
    getRandomValues(bytes) {
      calls++;
      assert.equal(bytes.length, GENERATED_ACCOUNT_PASSWORD_LENGTH);
      bytes.set(Array.from({ length: bytes.length }, (_, index) => index * 11));
      return bytes;
    },
  });
  assert.equal(calls, 1);
  assert.equal(password.length, 24);
  assert.match(password, /^[A-Za-z0-9_-]+$/);
  assert.equal(
    prepareAccountCreation({ username: "viewer", password, roleId: "view" }).status,
    "valid",
  );
  assert.throws(
    () =>
      generateAccountPassword({
        getRandomValues() {
          throw new Error("unavailable");
        },
      }),
    /unavailable/,
  );
  assert.notEqual(generateAccountPassword(), generateAccountPassword());
});

test("ACCOUNT-CREATE: username/password/role only, no generated ID/display/confirmation; password is exact", () => {
  const draft = Object.freeze({
    username: " viewer ",
    password: " SYNTHETIC-PASSWORD ",
    roleId: "view",
  });
  assert.deepEqual(prepareAccountCreation(draft), {
    status: "valid",
    input: { username: "viewer", password: draft.password, roleId: "view" },
  });
  for (const input of [
    { ...draft, username: " " },
    { ...draft, password: "" },
    { ...draft, password: "x".repeat(PASSWORD_MIN_LENGTH - 1) },
    { ...draft, roleId: "unknown" },
  ])
    assert.equal(prepareAccountCreation(input).status, "invalid");
  assert.equal(
    prepareAccountCreation({ ...draft, password: "x".repeat(PASSWORD_MIN_LENGTH) }).status,
    "valid",
    "the minimum wire length is inclusive",
  );
  assert.equal(
    prepareAccountCreation({ ...draft, password: "x".repeat(PASSWORD_MAX_LENGTH) }).status,
    "valid",
    "the maximum wire length is inclusive",
  );
  assert.deepEqual(
    prepareAccountCreation({ ...draft, password: "x".repeat(PASSWORD_MAX_LENGTH + 1) }),
    {
      status: "invalid",
      issues: [{ key: "account.passwordTooLong", params: { max: PASSWORD_MAX_LENGTH } }],
    },
  );
  assert.equal(
    prepareAccountCreation({ ...draft, password: "😀".repeat(PASSWORD_MAX_LENGTH / 2 + 1) }).status,
    "invalid",
    "JavaScript length uses UTF-16 code units, matching the wire limit",
  );
});
test("ACCOUNT-IDENTITY: browser mock normalization matches the Console trim/NFKC/lowercase identity contract", () => {
  const variants = [" Admin ", "admin", "Ａdmin"];
  assert.equal(new Set(variants.map(canonicalizeAccountUsername)).size, 1);
  assert.equal(canonicalizeAccountUsername("\uFEFF\u00A0Admin\u3000"), "admin");
  assert.equal(canonicalizeAccountUsername("A\u030A"), canonicalizeAccountUsername("Å"));
  assert.equal(canonicalizeAccountUsername("ΟΣ"), "ος");
  assert.equal("a".repeat(200).length, 200);
  assert.equal("😀".repeat(100).length, 200);
});
test("ACCOUNT-LIST: positive bounded pagination and stable filter values; malformed query is not clamped into another request", () => {
  assert.deepEqual(
    validateAccountQuery({ page: 1, pageSize: 20, search: "viewer", status: "active" }),
    [],
  );
  for (const query of [
    { page: 0, pageSize: 20, search: "" },
    { page: 1.5, pageSize: 20, search: "" },
    { page: 1, pageSize: 101, search: "" },
    { page: 1, pageSize: 20, search: "", status: "unknown" },
    { page: 1, pageSize: 20, search: "x".repeat(ACCOUNT_SEARCH_MAX_LENGTH + 1) },
  ])
    assert.ok(validateAccountQuery(query).length);
  assert.equal(
    boundAccountSearch("x".repeat(ACCOUNT_SEARCH_MAX_LENGTH)).length,
    ACCOUNT_SEARCH_MAX_LENGTH,
  );
  assert.equal(
    boundAccountSearch("x".repeat(ACCOUNT_SEARCH_MAX_LENGTH + 1)).length,
    ACCOUNT_SEARCH_MAX_LENGTH,
  );
  assert.equal(
    boundAccountSearch(`${"x".repeat(ACCOUNT_SEARCH_MAX_LENGTH - 1)}😀`),
    "x".repeat(ACCOUNT_SEARCH_MAX_LENGTH - 1),
    "truncation does not split a supplementary character at the UTF-16 boundary",
  );
});
test("ACCOUNT-STATUS: built-in/last-active-admin hints cannot be removed; unchanged and missing targets do not dispatch", () => {
  assert.equal(accountStatusIssue(record, "disabled"), null);
  assert.equal(accountStatusIssue({ ...record, builtIn: true }, "disabled"), "built_in");
  assert.equal(accountStatusIssue({ ...record, lastActiveAdmin: true }, "disabled"), "last_admin");
  assert.equal(accountStatusIssue(record, "active"), "unchanged");
  assert.equal(accountStatusIssue(null, "disabled"), "not_found");
  assert.equal(accountStatusIssue(record, "unknown"), "invalid_status");
});
test("ACCOUNT-STATUS-RESTRICTION-COPY: protected status actions explain the same rule that disables them", () => {
  assert.equal(accountStatusRestrictionCopy({ ...record, builtIn: true }), "management.builtIn");
  assert.equal(
    accountStatusRestrictionCopy({ ...record, lastActiveAdmin: true }),
    "management.lastAdmin",
  );
  assert.equal(accountStatusRestrictionCopy(record), null);
  assert.equal(
    accountStatusRestrictionCopy({ ...record, status: "disabled", builtIn: true }),
    null,
  );
});
test("ROLE-DRAFT: local role selection never mutates the record or advances the baseline revision", () => {
  const draft = createRoleDraft(record),
    changed = changeRoleDraft(draft, "view");
  assert.equal(draft.roleId, "admin");
  assert.equal(changed.roleId, "view");
  assert.equal(changed.revision, record.revision);
  assert.equal(record.roleId, "admin");
  assert.strictEqual(changeRoleDraft(draft, "unknown"), draft);
  assert.strictEqual(changeRoleDraft(draft, "admin"), draft);
});
test("ROLE-DRAFT-SNAPSHOT: restore only a strict dirty draft for the same authoritative target", () => {
  const dirty = changeRoleDraft(createRoleDraft(record), "view"),
    snapshot = createRoleDraftSnapshot(dirty);
  assert.deepEqual(restoreRoleDraftSnapshot(record.id, snapshot), dirty);
  assert.equal(restoreRoleDraftSnapshot("other", snapshot), null);
  assert.equal(restoreRoleDraftSnapshot(record.id, { ...snapshot, roleId: "admin" }), null);
  assert.equal(restoreRoleDraftSnapshot(record.id, { ...snapshot, schemaVersion: 2 }), null);
  assert.equal(restoreRoleDraftSnapshot(record.id, { ...snapshot, unexpected: true }), null);
  assert.equal(restoreRoleDraftSnapshot(record.id, { ...snapshot, revision: "" }), null);
  assert.equal(restoreRoleDraftSnapshot(record.id, { ...snapshot, roleId: "not-a-role" }), null);
});
test("ROLE-DRAFT-SESSION: a dirty role edit restores per session and target, then clean edits remove it", () => {
  const entries = new Map(),
    storage = {
      getItem: (key) => entries.get(key) ?? null,
      setItem: (key, value) => entries.set(key, value),
      removeItem: (key) => entries.delete(key),
    },
    epoch = "session-one",
    dirty = changeRoleDraft(createRoleDraft(record), "view");
  writeRoleDraftSession(storage, epoch, dirty);
  const restored = readRoleDraftSession(storage, epoch, record.id);
  assert.deepEqual(restored, dirty);
  const refreshed = reconcileRoleDraft({ ...record, revision: "9007199254740999" }, restored);
  assert.equal(refreshed.revision, record.revision);
  assert.equal(roleDraftIsDirty(refreshed), true);
  assert.equal(readRoleDraftSession(storage, "session-two", record.id), null);
  assert.notEqual(roleDraftSessionKey(epoch, record.id), roleDraftSessionKey(epoch, "record-two"));
  writeRoleDraftSession(storage, epoch, createRoleDraft(record));
  assert.equal(readRoleDraftSession(storage, epoch, record.id), null);
});
test("ROLE-DRAFT-SESSION: corrupt, oversized and unavailable storage cannot affect authoritative roles", () => {
  const entries = new Map(),
    storage = {
      getItem: (key) => entries.get(key) ?? null,
      setItem: (key, value) => entries.set(key, value),
      removeItem: (key) => entries.delete(key),
    },
    key = roleDraftSessionKey("session-one", record.id);
  entries.set(key, "not-json");
  assert.equal(readRoleDraftSession(storage, "session-one", record.id), null);
  assert.equal(entries.has(key), false);
  entries.set(key, "x".repeat(2049));
  assert.equal(readRoleDraftSession(storage, "session-one", record.id), null);
  const failingStorage = {
    getItem: () => null,
    setItem: () => {
      throw new Error("storage unavailable");
    },
    removeItem: () => {
      throw new Error("storage unavailable");
    },
  };
  const draft = changeRoleDraft(createRoleDraft(record), "view");
  assert.doesNotThrow(() => writeRoleDraftSession(failingStorage, "session-one", draft));
});
test("ROLE-REFRESH: a clean draft follows a new authoritative revision; a dirty draft keeps its old conflict baseline", () => {
  const original = createRoleDraft(record),
    remote = Object.freeze({ ...record, roleId: "view", revision: "9007199254740994" });
  assert.equal(roleDraftIsDirty(original), false);
  const reconciledClean = reconcileRoleDraft(remote, original);
  assert.equal(reconciledClean.roleId, "view");
  assert.equal(reconciledClean.baseRoleId, "view");
  assert.equal(reconciledClean.revision, remote.revision);
  const edited = changeRoleDraft(original, "view"),
    reconciledDirty = reconcileRoleDraft({ ...record, revision: "9007199254740995" }, edited);
  assert.equal(roleDraftIsDirty(reconciledDirty), true);
  assert.equal(reconciledDirty.revision, record.revision);
  assert.equal(reconciledDirty.roleId, "view");
  const otherAccount = reconcileRoleDraft({ ...remote, id: "record-two" }, edited);
  assert.equal(otherAccount.accountId, "record-two");
  assert.equal(roleDraftIsDirty(otherAccount), false);
});
test("ROLE-REFRESH: an authoritative reread matching the requested role resolves the local draft", () => {
  const dirty = changeRoleDraft(createRoleDraft(record), "view"),
    confirmed = reconcileRoleDraft(
      { ...record, roleId: "view", revision: "9007199254740996" },
      dirty,
    );
  assert.equal(confirmed.roleId, "view");
  assert.equal(confirmed.baseRoleId, "view");
  assert.equal(confirmed.revision, "9007199254740996");
  assert.equal(roleDraftIsDirty(confirmed), false);
});
test("ROLE-COMMIT: exactly admin/view; explicit target/revision, disabled or protected records cannot be silently edited", () => {
  assert.equal(accountRoleIssue(record, "view"), null);
  assert.equal(accountRoleIssue({ ...record, builtIn: true }, "view"), "built_in");
  assert.equal(accountRoleIssue({ ...record, lastActiveAdmin: true }, "view"), "last_admin");
  assert.equal(accountRoleIssue({ ...record, status: "disabled" }, "admin"), "inactive");
  assert.equal(accountRoleIssue(record, "unknown"), "invalid_role");
  assert.equal(accountRoleIssue(null, "view"), "not_found");
  assert.equal(accountRoleIssue(record, "admin"), "unchanged");
});
test("ROLE-TARGET-COPY: only an empty detail result is reported as missing; read failure and stale URL targets stay distinct", () => {
  assert.equal(roleTargetFallbackCopy({ status: "empty" }), "management.read.empty");
  assert.equal(
    roleTargetFallbackCopy({ status: "error", key: "target-b", error: {} }),
    "management.read.failed",
  );
  assert.equal(
    roleTargetFallbackCopy({ status: "denied", key: "target-b", error: {} }),
    "management.denied",
  );
  assert.equal(
    roleTargetFallbackCopy({
      status: "stale",
      key: "target-a",
      data: record,
      receivedAt: 1,
      error: {},
    }),
    "management.read.stale",
  );
  for (const status of ["idle", "loading", "refreshing", "ready", "filtered-empty"]) {
    assert.equal(
      roleTargetFallbackCopy({ status, key: "previous-target", data: record, receivedAt: 1 }),
      "management.read.loading",
    );
  }
});
test("ROLE-RESTRICTION-COPY: disabled, built-in and last-active-admin records explain the locked editor", () => {
  assert.equal(
    roleEditRestrictionCopy({ ...record, status: "disabled" }),
    "roles.restriction.disabled",
  );
  assert.equal(roleEditRestrictionCopy({ ...record, builtIn: true }), "roles.restriction.builtIn");
  assert.equal(
    roleEditRestrictionCopy({ ...record, lastActiveAdmin: true }),
    "roles.restriction.lastAdmin",
  );
  assert.equal(roleEditRestrictionCopy(record), null);
  assert.equal(
    roleEditRestrictionCopy({ ...record, status: "disabled", builtIn: true }),
    "roles.restriction.disabled",
  );
});
