import assert from "node:assert/strict";
import { test } from "node:test";
import { createRouteSnapshotReader } from "../../src/app/router/routeSnapshot";
import {
  mayPreserveAuthorizedSetupRoute,
  navigationItemsForAccess,
  routeAfterAuthentication,
  sessionShortcutRoute,
} from "../../src/app/router/navigation";
import {
  accessFor,
  isMainNavRouteId,
  isRouteId,
  pathFor,
  routeFromPath,
  ROUTE,
} from "../../src/app/router/route.constants";
import { resolveRuleKindFilter, RULE_KIND_ALL } from "../../src/features/rules/model/ruleKinds";

const options = Object.freeze({
  applicationScopeIds: ["orders", "payments"],
  defaultAccountId: "me",
});
test("F2 route cache includes defaults and catalog, not only the hash", () => {
  const read = createRouteSnapshotReader();
  const first = read("#/applications", options);
  assert.equal(first.appId, "all");
  assert.equal(first.accountId, "me");
  assert.strictEqual(
    read("#/applications", { ...options, applicationScopeIds: ["orders", "payments"] }),
    first,
  );
  assert.equal(
    read("#/applications", { ...options, defaultAccountId: "other-session" }).accountId,
    "other-session",
  );
  assert.equal(
    read("#/applications", { ...options, applicationScopeIds: ["new-app"] }).appId,
    "all",
  );
  assert.equal(read("#/rules", options).appId, "all");
  assert.equal(read("#/rules", { ...options, applicationScopeIds: ["new-app"] }).appId, "all");
});

test("F6.4.01 app assembly does not synthesize a demo application scope", () => {
  const read = createRouteSnapshotReader();
  assert.equal(read("#/applications", { defaultAccountId: "me" }).appId, "all");
  assert.equal(read("#/applications?app=orders", { defaultAccountId: "me" }).appId, "orders");
});

test("F2 observation context round-trips without credentials or protocol label substitution", () => {
  const context = {
    environmentId: "prod",
    appId: "orders",
    range: "15m",
    accountId: "user-a",
    view: "flow",
    instanceId: "i/1",
    resource: "POST /orders?state=ready",
    eventId: "event 1",
    versionId: "v/2",
    metricScope: "container",
    search: "qps > 100",
  };
  const encoded = pathFor(ROUTE.Rules, { ...context, password: "secret", token: "secret" });
  assert.deepEqual(routeFromPath(encoded).context, context);
  assert.ok(!encoded.includes("secret"));
  assert.deepEqual(routeFromPath("#/rules?password=secret&token=secret").context, {});
  assert.equal(routeFromPath("#/rules?resource=GET%20/a?b=c").context.resource, "GET /a?b=c");
});
test("F2 local route guards reject prototype names and distinguish primary destinations", () => {
  assert.equal(isRouteId(ROUTE.Rules), true);
  assert.equal(isRouteId("constructor"), false);
  assert.equal(isRouteId(null), false);
  assert.equal(isMainNavRouteId(ROUTE.Rules), true);
  assert.equal(isMainNavRouteId(ROUTE.Accounts), false);
});
test("F4.23 authentication return route is local, allow-listed, and re-authorized for the confirmed role", () => {
  const context = { appId: "orders", range: "15m", returnTo: ROUTE.Rules };
  const encoded = pathFor(ROUTE.Login, context);
  assert.deepEqual(routeFromPath(encoded).context, context);
  assert.equal(
    routeFromPath("#/login?returnTo=https%3A%2F%2Fevil.example").context.returnTo,
    undefined,
  );
  assert.equal(pathFor(ROUTE.Overview, context).includes("returnTo"), false);
  assert.equal(routeFromPath("#/overview?returnTo=accounts").context.returnTo, undefined);
  assert.equal(
    routeAfterAuthentication(ROUTE.Accounts, {
      accountId: "admin-1",
      username: "operator",
      roleId: "admin",
      capabilities: ["metrics:view", "rules:write"],
      sessionEpoch: "session-1",
    }),
    ROUTE.Accounts,
  );
  assert.equal(
    routeAfterAuthentication(ROUTE.Accounts, {
      accountId: "viewer-1",
      username: "viewer",
      roleId: "view",
      capabilities: ["metrics:view"],
      sessionEpoch: "session-2",
    }),
    ROUTE.Overview,
  );
  assert.equal(
    routeAfterAuthentication(ROUTE.Setup, {
      accountId: "admin-1",
      username: "operator",
      roleId: "admin",
      capabilities: ["metrics:view", "rules:write"],
      sessionEpoch: "session-1",
    }),
    ROUTE.Overview,
  );
});

test("F4.20 setup route preservation requires a previously confirmed open and authorized gate", () => {
  const facts = {
    kind: "uninitialized",
    setupAvailable: true,
    operatorAuthorized: true,
  };
  assert.equal(mayPreserveAuthorizedSetupRoute({ phase: "checking", previousFacts: facts }), true);
  assert.equal(mayPreserveAuthorizedSetupRoute({ phase: "checking" }), false);
  assert.equal(
    mayPreserveAuthorizedSetupRoute({
      phase: "checking",
      previousFacts: { ...facts, setupAvailable: false },
    }),
    false,
  );
  assert.equal(
    mayPreserveAuthorizedSetupRoute({
      phase: "checking",
      previousFacts: { ...facts, operatorAuthorized: false },
    }),
    false,
  );
  assert.equal(
    mayPreserveAuthorizedSetupRoute({
      phase: "checking",
      previousFacts: { kind: "anonymous" },
    }),
    false,
  );
});
test("F4.13 incident filters and opaque cursors round-trip only on the faults route", () => {
  const incidentContext = {
    appId: "app-one",
    range: "15m",
    incidentSeverity: "critical",
    incidentCategory: "resource",
    incidentCursor: "cursor/opaque+value",
  };
  const encoded = pathFor(ROUTE.Faults, incidentContext);
  assert.deepEqual(routeFromPath(encoded).context, incidentContext);
  assert.ok(!pathFor(ROUTE.Overview, incidentContext).includes("severity"));
  assert.ok(!pathFor(ROUTE.Overview, incidentContext).includes("cursor"));
  assert.equal(
    routeFromPath(`#/faults?cursor=${"x".repeat(513)}`).context.incidentCursor,
    undefined,
  );
});
test("F2.5 rule kind is a stable feature-owned URL view and invalid kinds fail closed to all", () => {
  const path = pathFor(ROUTE.Rules, { view: "flow" });
  assert.equal(routeFromPath(path).context.view, "flow");
  assert.equal(resolveRuleKindFilter(routeFromPath(path).context.view), "flow");
  assert.equal(resolveRuleKindFilter("param"), "param");
  assert.equal(resolveRuleKindFilter("made-up-kind"), RULE_KIND_ALL);
  assert.equal(resolveRuleKindFilter(undefined), RULE_KIND_ALL);
});
test("F2.6 route metadata distinguishes metrics viewers from administrative destinations", () => {
  for (const route of [
    ROUTE.Overview,
    ROUTE.Applications,
    ROUTE.Rules,
    ROUTE.Realtime,
    ROUTE.Faults,
  ])
    assert.equal(accessFor(route), "metrics");
  for (const route of [ROUTE.Accounts, ROUTE.Roles, ROUTE.System])
    assert.equal(accessFor(route), "admin");
  assert.equal(accessFor(ROUTE.ChangePassword), "session");
  assert.equal(accessFor(ROUTE.Login), "public");
  assert.equal(accessFor(ROUTE.Setup), "setup");
  const viewerNavigation = navigationItemsForAccess(false).map(({ id }) => id);
  assert.ok(!viewerNavigation.includes(ROUTE.System));
  assert.ok(viewerNavigation.includes(ROUTE.Rules));
  assert.ok(navigationItemsForAccess(true).some(({ id }) => id === ROUTE.System));
  assert.equal(sessionShortcutRoute(false), ROUTE.ChangePassword);
  assert.equal(sessionShortcutRoute(true), ROUTE.Accounts);
});
test("F2 route readers isolate owners, explicit invalid targets and empty catalogs", () => {
  const read = createRouteSnapshotReader(),
    other = createRouteSnapshotReader();
  const target = read("#/roles?account=missing", options);
  assert.equal(target.accountId, "missing");
  assert.notStrictEqual(other("#/roles?account=missing", options), target);
  assert.equal(read("#/applications?app=missing", options).appId, "missing");
  assert.equal(read("#/applications", { ...options, applicationScopeIds: [] }).appId, "all");
  assert.equal(read("#/applications?app=all", options).appId, "all");
});
