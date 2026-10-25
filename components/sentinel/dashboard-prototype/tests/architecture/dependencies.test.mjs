import assert from "node:assert/strict";
import { test } from "node:test";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { classifyDependency, dependencySpecifiers, resolveDependency } from "./dependencies.mjs";

const root = fileURLToPath(new URL("../../src/", import.meta.url));

/** Inspect actual application files, never a parallel copied source graph. */
export function sourceViolations() {
  const violations = [];
  function walk(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const current = path.join(directory, entry.name);
      if (entry.isDirectory()) walk(current);
      else if (/\.tsx?$/.test(entry.name)) {
        const source = path.relative(root, current).split(path.sep).join("/");
        for (const specifier of dependencySpecifiers(readFileSync(current, "utf8"))) {
          const target = resolveDependency(source, specifier) ?? specifier;
          const rule = classifyDependency(source, target);
          if (rule) violations.push({ source, target, rule });
        }
      }
    }
  }
  walk(root);
  return violations;
}

/** Find production-source imports that bypass their feature's mock HTTP entry. */
export function fixtureImportViolations() {
  const violations = [];
  function walk(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const current = path.join(directory, entry.name);
      if (entry.isDirectory()) walk(current);
      else if (/\.tsx?$/.test(entry.name)) {
        const source = path.relative(root, current).split(path.sep).join("/");
        for (const specifier of dependencySpecifiers(readFileSync(current, "utf8"))) {
          const target = resolveDependency(source, specifier) ?? specifier;
          const fixture = /^features\/([^/]+)\/fixtures(?:\/|$)/.exec(target);
          if (!fixture) continue;

          const feature = fixture[1];
          const expectedMockEntry = `features/${feature}/mock.ts`;
          const isOwnedFixtureModule = source.startsWith(`features/${feature}/fixtures/`);
          if (source !== expectedMockEntry && !isOwnedFixtureModule) {
            violations.push({ source, target });
          }
        }
      }
    }
  }
  walk(root);
  return violations;
}

test("parses static, exported, type and lazy imports without losing multiline references", () => {
  assert.deepEqual(
    dependencySpecifiers(
      `import type { X } from '@/features/a/model/x'; export { Y } from './y'; const load = () => import('./lazy'); type T = import('./types').T;`,
    ),
    ["@/features/a/model/x", "./y", "./lazy", "./types"],
  );
});

test("rejects reverse and private dependencies, while allowing public feature entries", () => {
  assert.equal(classifyDependency("core/api/client.ts", "features/rules"), "core-reverse");
  assert.equal(classifyDependency("shared/ui/Filters.tsx", "app/router/routes"), "shared-reverse");
  assert.equal(
    classifyDependency("features/a/ui/Page.tsx", "core/api/transport/consoleEndpoint"),
    "feature-ui-transport",
  );
  assert.equal(
    classifyDependency("features/a/model/x.ts", "features/b/model/x"),
    "feature-private",
  );
  assert.equal(
    classifyDependency("features/a/model/x.ts", "shared/ui/charts/theme"),
    "model-effect-or-ui",
  );
  assert.equal(
    classifyDependency("features/rules/model/ruleSet.ts", "features/rules/editor/ruleDraft"),
    "model-form",
  );
  assert.equal(
    classifyDependency(
      "features/realtime/presentation/chartProjection.ts",
      "shared/ui/charts/chartTheme",
    ),
    "presentation-ui-token",
  );
  assert.equal(
    classifyDependency("features/rules/api/ruleSetHttp.ts", "features/rules/editor/ruleDraft"),
    "wire-form",
  );
  assert.equal(classifyDependency("features/a/model/x.ts", "react"), "model-effect-or-ui");
  assert.equal(classifyDependency("features/a/ui/Page.tsx", "features/b"), null);
  assert.equal(classifyDependency("features/a/ui/Page.tsx", "features/b/index.ts"), null);
  assert.equal(
    classifyDependency("app/router/routes.tsx", "features/identity/ui/LoginEntryPage"),
    "app-feature-private",
  );
  assert.equal(classifyDependency("app/router/routes.tsx", "features/identity/login"), null);
  assert.equal(
    resolveDependency("features/a/ui/Page.tsx", "@/shared/types/navigation"),
    "shared/types/navigation",
  );
  assert.equal(
    resolveDependency("shared/ui/X.tsx", "../../app/router/routes"),
    "app/router/routes",
  );
});

test("F1.6 keeps rule form/editor ownership out of domain model and chart UI tokens out of presentation", () => {
  const actual = sourceViolations();
  assert.deepEqual(
    actual.filter((edge) =>
      ["model-form", "presentation-ui-token", "wire-form"].includes(edge.rule),
    ),
    [],
  );
});

test("F1.7 keeps application imports on feature public entry points", () => {
  const actual = sourceViolations();
  assert.deepEqual(
    actual.filter((edge) => edge.rule === "app-feature-private"),
    [],
  );
});

test("F2.2 scopes route page owners to the resolved server session epoch", () => {
  const app = readFileSync(new URL("../../src/app/App.tsx", import.meta.url), "utf8");
  assert.match(app, /auth\.access\.phase === "resolved"/);
  assert.match(app, /auth\.access\.facts\.kind === "authenticated"/);
  assert.match(app, /auth\.access\.facts\.identity\.sessionEpoch/);
  assert.match(app, /resetKey=\{routePageOwnerKey\(currentRoute, sessionEpoch\)\}/);
});

test("F4.23 leaves login success and setup navigation to the login route owner", () => {
  const app = readFileSync(new URL("../../src/app/App.tsx", import.meta.url), "utf8");
  const loginRoute = readFileSync(
    new URL("../../src/app/router/IdentityRouteOwners.tsx", import.meta.url),
    "utf8",
  );
  const loginPage = readFileSync(
    new URL("../../src/features/identity/ui/LoginEntryPage.tsx", import.meta.url),
    "utf8",
  );

  assert.match(app, /if \(currentRoute === ROUTE\.Login\) return;/);
  assert.doesNotMatch(app, /routeAfterAuthentication|facts\.setupAvailable/);
  assert.match(loginRoute, /onAuthenticated=\{authenticated\}\s+onSetupRequired=\{setupRequired\}/);
  assert.match(loginPage, /onAuthenticated\(identity\)/);
  assert.match(loginPage, /onSetupRequired\(\)/);
});

test("F5.2 changing display locale does not replace rule draft or URL owners", () => {
  const app = readFileSync(new URL("../../src/app/App.tsx", import.meta.url), "utf8");
  const routeOwner = readFileSync(
    new URL("../../src/app/router/routeOwner.ts", import.meta.url),
    "utf8",
  );
  const header = readFileSync(new URL("../../src/app/shell/Header.tsx", import.meta.url), "utf8");
  const rules = readFileSync(
    new URL("../../src/features/rules/ui/RuleConsoleContainer.tsx", import.meta.url),
    "utf8",
  );

  // Locale is passed as presentation input, while only route/session identity resets a page.
  assert.match(app, /locale,\s*view,/);
  assert.match(app, /resetKey=\{routePageOwnerKey\(currentRoute, sessionEpoch\)\}/);
  assert.match(routeOwner, /JSON\.stringify\(\[route, sessionEpoch\]\)/);
  assert.doesNotMatch(routeOwner, /locale/i);

  // Language selection changes the i18n preference; it must not navigate or become rule state.
  assert.match(header, /const changeLanguage = \(next: string\) => \{/);
  assert.match(header, /setLocale\(next\)/);
  assert.doesNotMatch(
    header.slice(header.indexOf("const changeLanguage"), header.indexOf("return (")),
    /navigate\(/,
  );

  // Rule owners are keyed by rule context and keep the draft workflow in a stable memo owner.
  assert.match(
    rules,
    /key=\{`\$\{environmentId\}:\$\{page\.appId\}:\$\{page\.view\}:\$\{page\.bindingId \?\? "unselected"\}`\}/,
  );
  assert.match(
    rules,
    /createRuleDraftWorkflow\(binding, port, readAccess, writeAccess, operation\)/,
  );
  assert.doesNotMatch(rules, /locale/);
});

test("source graph introduces no new violation and retains no stale migration waiver", () => {
  const allowed = JSON.parse(
    readFileSync(new URL("./migration-edges.json", import.meta.url), "utf8"),
  );
  const actual = sourceViolations();
  const identity = ({ source, target, rule }) => JSON.stringify({ source, target, rule });
  for (const edge of allowed) {
    assert.ok(
      edge.ownerTask && edge.reason,
      "Every legacy edge needs a named retirement task/reason",
    );
    assert.ok(
      actual.some((item) => identity(item) === identity(edge)),
      `Stale waiver: ${identity(edge)}`,
    );
  }
  assert.deepEqual(
    actual.filter((edge) => !allowed.some((item) => identity(item) === identity(edge))),
    [],
  );
});

test("F1.4 feature route containers consume feature Ports while app routes assemble HTTP adapters", () => {
  const featureRoot = path.join(root, "features");
  const routeContainers = [];
  function collect(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const current = path.join(directory, entry.name);
      if (entry.isDirectory()) collect(current);
      else if (/\.tsx$/.test(entry.name) && current.includes(`${path.sep}ui${path.sep}`)) {
        const source = readFileSync(current, "utf8");
        if (/export function \w+Container\(/.test(source))
          routeContainers.push({ current, source });
      }
    }
  }
  collect(featureRoot);
  assert.ok(routeContainers.length >= 6, "expected the six production feature route containers");
  for (const { current, source } of routeContainers) {
    assert.equal(source.includes("core/api/transport/"), false, current);
    assert.doesNotMatch(source, /create[A-Z]\w*Http\(/, current);
  }

  const routeAssembly = readFileSync(
    new URL("../../src/app/router/routes.tsx", import.meta.url),
    "utf8",
  );
  for (const marker of [
    "createFleetHttp(transport)",
    "createInstanceHttp(transport)",
    "createRuleSetHttp(transport)",
    "createMetricsHttp(transport)",
    "createIncidentHttp(transport)",
    "fleetPort={fleetPort}",
    "instancePort={instancePort}",
    "ruleSetPort={ruleSetPort}",
    "metricsPort={metricsPort}",
    "incidentPort={incidentPort}",
  ])
    assert.ok(routeAssembly.includes(marker), `app route assembly must contain ${marker}`);

  const systemAssembly = readFileSync(
    new URL("../../src/app/router/ConsoleSystemRoute.tsx", import.meta.url),
    "utf8",
  );
  assert.ok(systemAssembly.includes("createSystemObservationHttp(services.transport)"));
  assert.ok(systemAssembly.includes("createSourceRegistrationHttp(services.transport)"));
});

test("F6.12 retires the synchronous fixture gateway instead of preserving a compatibility path", () => {
  const retired = [
    "core/api/GatewayProvider.tsx",
    "core/api/fixtureGateway.ts",
    "core/api/httpGateway.ts",
    "core/api/contracts.ts",
    "core/api/providers/consulAdapter.ts",
    "core/api/providers/errorMapper.ts",
    "core/api/providers/index.ts",
    "core/api/providers/nacosAdapter.ts",
    "core/api/providers/providerError.ts",
    "core/api/providers/registry.ts",
    "core/api/providers/types.ts",
    "features/identity/bootstrap.ts",
    "features/identity/state/useDemoAccountBootstrap.ts",
    "../tests/api/providers.test.mjs",
    "../tests/api/run.mjs",
  ];
  for (const path of retired) assert.equal(existsSync(`${root}/${path}`), false, path);

  const source = [];
  function collect(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const current = path.join(directory, entry.name);
      if (entry.isDirectory()) collect(current);
      else if (/\.tsx?$/.test(entry.name)) source.push(readFileSync(current, "utf8"));
    }
  }
  collect(root);
  const applicationSource = source.join("\n");
  for (const marker of [
    "FixtureGateway",
    "ConsoleGatewayProvider",
    "useConsoleGateway",
    "HttpConsoleGateway",
    "readApplicationsSync",
    "readFleetOverviewSync",
    "useDemoAccountBootstrap",
    "nacosAdapter",
    "consulAdapter",
    "RuleProviderAdapter",
  ])
    assert.equal(applicationSource.includes(marker), false, `application source retains ${marker}`);
});

test("F7.3 production code reaches feature fixtures only through its mock HTTP entry", () => {
  assert.deepEqual(fixtureImportViolations(), []);
});

test("F7.3 retires prototype-only panels after their HTTP-backed page replacements", () => {
  const retired = [
    "features/faults/ui/IncidentEvidence.tsx",
    "features/realtime/ui/RealtimeSummaryCards.tsx",
    "features/rules/ui/RuleCatalogPanel.tsx",
    "features/rules/ui/RuleInspectorPanel.tsx",
    "features/rules/ui/VersionPlan.tsx",
    "features/system/ui/ConnectionPanel.tsx",
    "features/system/ui/PermissionsPanel.tsx",
    "features/system/ui/ProtocolPanel.tsx",
  ];
  for (const sourcePath of retired)
    assert.equal(existsSync(`${root}/${sourcePath}`), false, sourcePath);
});

test("F7.3 removes the unused demo role-switching API from the session surface", () => {
  const sessionSource = readFileSync(`${root}/core/session/SessionProvider.tsx`, "utf8");
  const sessionEntry = readFileSync(`${root}/core/session/index.ts`, "utf8");

  assert.equal(sessionSource.includes("useSessionRoleSetter"), false);
  assert.equal(sessionEntry.includes("useSessionRoleSetter"), false);
});
