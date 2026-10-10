import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const featureRoot = fileURLToPath(new URL("../../src/features/", import.meta.url));
const sourceRoot = fileURLToPath(new URL("../../src/", import.meta.url));

/** Walk actual feature UI source; this guard must not rely on a copied architecture manifest. */
function uiOwnershipViolations() {
  const violations = [];
  function walk(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const current = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        walk(current);
        continue;
      }
      if (!/\.tsx?$/.test(entry.name) || !current.split(path.sep).includes("ui")) continue;
      const source = readFileSync(current, "utf8");
      const relative = path.relative(featureRoot, current).split(path.sep).join("/");
      const imports = [...source.matchAll(/\b(?:from\s*|import\s*\()\s*["']([^"']+)["']/g)].map(
        (match) => match[1],
      );
      if (imports.some((specifier) => /(?:^|\/)fixtures(?:\/|$)/.test(specifier)))
        violations.push({ file: relative, rule: "ui-fixture-import" });
      if (imports.some((specifier) => /(?:^|\/)api\/[^/]*Http$/.test(specifier)))
        violations.push({ file: relative, rule: "ui-http-adapter-import" });
      if (/\bfetch\s*\(/.test(source)) violations.push({ file: relative, rule: "ui-fetch" });
      if (/\bcreate[A-Z]\w*Http\s*\(/.test(source))
        violations.push({ file: relative, rule: "ui-http-adapter-construction" });
    }
  }
  walk(featureRoot);
  return violations;
}

test("F2.7 feature UI delegates IO to its owner and never imports fixtures or HTTP adapters", () => {
  assert.deepEqual(uiOwnershipViolations(), []);
});

test("F6.4 keeps demo seed ownership in app scenarios and exposes handlers through feature mock entries", () => {
  const fixtureImports = [];
  const reservedSeedOwners = new Map([
    ["mock-forbidden-application", "app/api/mockObservationScenario.ts"],
    ["mock-recovering-application", "app/api/mockObservationScenario.ts"],
    ["test-env", "app/api/mockSystemScenario.ts"],
    ["app-one", "app/api/mockSystemScenario.ts"],
    ["演示环境", "app/api/mockObservationScenario.ts"],
    ["Primary Nacos", "app/api/mockSystemScenario.ts"],
    ["unreachable.example", "app/api/mockSystemScenario.ts"],
    ["incident-resource-pressure", "app/api/mockIncidentScenario.ts"],
    ["incident-response-time", "app/api/mockIncidentScenario.ts"],
    ["incident-rule-published", "app/api/mockIncidentScenario.ts"],
    ["incident-demo", "app/api/mockIncidentScenario.ts"],
    ["evidence-metric-sample", "app/api/mockIncidentScenario.ts"],
    ["evidence-threshold-policy", "app/api/mockIncidentScenario.ts"],
  ]);
  const reservedSeedOccurrences = new Map([...reservedSeedOwners.keys()].map((seed) => [seed, []]));

  function walk(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const current = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        walk(current);
        continue;
      }
      if (!/\.tsx?$/.test(entry.name)) continue;

      const source = readFileSync(current, "utf8");
      const relative = path.relative(sourceRoot, current).split(path.sep).join("/");
      const imports = [...source.matchAll(/\b(?:from\s*|import\s*\()\s*["']([^"']+)["']/g)].map(
        (match) => match[1],
      );
      for (const specifier of imports) {
        if (!/(?:^|\/)fixtures(?:\/|$)/.test(specifier)) continue;
        fixtureImports.push({ source: relative, specifier });
      }

      for (const [seed, files] of reservedSeedOccurrences)
        if (source.includes(seed)) files.push(relative);
    }
  }
  walk(sourceRoot);

  assert.deepEqual(
    fixtureImports.filter(({ source, specifier }) => {
      const feature = source.match(/^features\/([^/]+)\/mock\.ts$/)?.[1];
      return !feature || !specifier.startsWith("./fixtures/");
    }),
    [],
    "feature handler fixtures must only be reachable through that feature's explicit mock entry",
  );
  const instanceProjection = readFileSync(
    path.join(sourceRoot, "features/applications/fixtures/instanceObservationFixtures.ts"),
    "utf8",
  );
  assert.doesNotMatch(
    instanceProjection,
    /version-one|state:\s*"applied"\s*,/,
    "instance rule receipt projections must consume app-owned publication facts",
  );
  for (const [seed, files] of reservedSeedOccurrences)
    assert.deepEqual(files, [reservedSeedOwners.get(seed)], `${seed} belongs to app scenario`);

  const instanceScenario = readFileSync(
    path.join(sourceRoot, "app/api/mockObservationScenario.ts"),
    "utf8",
  );
  const applicationModelEntry = readFileSync(
    path.join(sourceRoot, "features/applications/model.ts"),
    "utf8",
  );
  assert.match(instanceScenario, /features\/applications\/model"/);
  assert.doesNotMatch(applicationModelEntry, /ui\/|\.tsx/);
  const systemModelEntry = readFileSync(path.join(sourceRoot, "features/system/model.ts"), "utf8");
  const sourceRegistrationProjection = readFileSync(
    path.join(sourceRoot, "features/system/fixtures/sourceRegistrationMockHandlers.ts"),
    "utf8",
  );
  const identityScenario = readFileSync(
    path.join(sourceRoot, "app/api/mockIdentityScenario.ts"),
    "utf8",
  );
  const accountProjection = readFileSync(
    path.join(sourceRoot, "features/identity/fixtures/accountManagementMockHandlers.ts"),
    "utf8",
  );
  const mockAssembly = readFileSync(
    path.join(sourceRoot, "app/api/mockConsoleHandlers.ts"),
    "utf8",
  );
  assert.doesNotMatch(systemModelEntry, /ui\/|\.tsx/);
  assert.doesNotMatch(sourceRegistrationProjection, /unreachable\.example|30_000/);
  assert.match(sourceRegistrationProjection, /checkScenario\.unavailableHostname/);
  assert.match(sourceRegistrationProjection, /checkScenario\.validForMs/);
  assert.match(sourceRegistrationProjection, /checkScenario\.capabilities/);
  assert.match(identityScenario, /lastLoginOffsetMs:/);
  assert.doesNotMatch(identityScenario, /lastLoginAt:/);
  assert.match(accountProjection, /new Date\(now\(\) \+ lastLoginOffsetMs\)/);
  assert.match(mockAssembly, /createAccountManagementMockHandlers\(identityScenario, mockClock\)/);
  assert.match(mockAssembly, /createMockScenarioClock\(nowMs\)/);
  assert.match(mockAssembly, /export function createAppConsoleMockAssembly\(/);
  assert.match(instanceScenario, /containerId: "container-1"/);
  assert.match(instanceScenario, /processId: "pid-1"/);
  assert.match(instanceScenario, /supportedScopes: Object\.freeze\(\[INSTANCE_LAYER\.Process\]\)/);
  assert.match(instanceScenario, /lastReportOffsetMs: 120_000/);
  assert.doesNotMatch(instanceProjection, /containerId:\s*`container-/);
  assert.doesNotMatch(instanceProjection, /processId:\s*`pid-/);
  assert.doesNotMatch(instanceProjection, /supportedScopes:\s*\[INSTANCE_LAYER\.Process\]/);
  assert.doesNotMatch(
    instanceProjection,
    /lastReportAtMs:\s*input\.context\.window\.fromMs\s*\+\s*120_000/,
  );
});

test("F6.4.17 keeps synthetic metric curves in the app scenario and projects them through HTTP mock builders", () => {
  const scenario = readFileSync(
    path.join(sourceRoot, "app/api/mockObservationScenario.ts"),
    "utf8",
  );
  assert.match(scenario, /trendProfiles:\s*Object\.freeze\(/);

  for (const relative of [
    "features/overview/fixtures/observationFixtures.ts",
    "features/realtime/fixtures/metricObservationFixtures.ts",
    "features/applications/fixtures/instanceObservationFixtures.ts",
  ]) {
    const projection = readFileSync(path.join(sourceRoot, relative), "utf8");
    assert.match(projection, /scenario\.trendProfiles/);
    assert.doesNotMatch(
      projection,
      /trendProfiles:\s*(?:Object\.freeze\(|\[)/,
      `${relative} must not define its own synthetic curve seed`,
    );
  }
});

test("F6.4.23 keeps transient metric failure plans in the app scenario", () => {
  const scenario = readFileSync(
    path.join(sourceRoot, "app/api/mockObservationScenario.ts"),
    "utf8",
  );
  const handler = readFileSync(
    path.join(sourceRoot, "features/realtime/fixtures/metricsMockHandlers.ts"),
    "utf8",
  );

  assert.match(scenario, /metricFailures:\s*Object\.freeze\(/);
  assert.match(scenario, /networkFailure:\s*Object\.freeze\(/);
  assert.match(scenario, /failOnRead:\s*\d+/);
  assert.match(handler, /scenario\.readScenarios\.metricFailures/);
  assert.match(handler, /scenario\.readScenarios\.networkFailure/);
  assert.doesNotMatch(handler, /FAILURE_ATTEMPT|RecoveringTransient|RetryableInitial/);
});

test("F6.4.24 keeps fleet recovery failure timing in the app scenario", () => {
  const scenario = readFileSync(
    path.join(sourceRoot, "app/api/mockObservationScenario.ts"),
    "utf8",
  );
  const handler = readFileSync(
    path.join(sourceRoot, "features/overview/fixtures/fleetMockHandlers.ts"),
    "utf8",
  );

  assert.match(scenario, /fleetFailure:\s*Object\.freeze\(/);
  assert.match(scenario, /failOnRead:\s*\d+/);
  assert.match(handler, /scenario\.readScenarios\.fleetFailure/);
  assert.doesNotMatch(handler, /attempts\s*===\s*0|fleetRecoveringApplicationId/);
});

test("F6.4.25 keeps incident evidence variation in the app scenario", () => {
  const scenario = readFileSync(path.join(sourceRoot, "app/api/mockIncidentScenario.ts"), "utf8");
  const handler = readFileSync(
    path.join(sourceRoot, "features/faults/fixtures/incidentMockHandlers.ts"),
    "utf8",
  );

  assert.match(scenario, /resourcePressureValueDelta:\s*0\.03/);
  assert.match(handler, /scenario\.incidents\.resourcePressureValueDelta/);
  assert.doesNotMatch(handler, /event\.caption\.value\s*-\s*0\.03/);
});

test("F6.9 keeps incident outage timing and code in the app scenario", () => {
  const scenario = readFileSync(path.join(sourceRoot, "app/api/mockIncidentScenario.ts"), "utf8");
  const handler = readFileSync(
    path.join(sourceRoot, "features/faults/fixtures/incidentMockHandlers.ts"),
    "utf8",
  );

  assert.match(scenario, /timelineFailure:\s*Object\.freeze\(/);
  assert.match(scenario, /applicationId:\s*"app-three"/);
  assert.match(scenario, /failOnRead:\s*1/);
  assert.match(scenario, /errorCode:\s*"service_unavailable"/);
  assert.match(handler, /scenario\.incidents\.timelineFailure/);
  assert.doesNotMatch(handler, /timelineReadCount\s*===\s*0/);
});
