/** Test-only facade binding feature fixture builders to the app-owned demo scenario. */
import { MOCK_APPLICATION_SCENARIO } from "../../src/app/api/mockApplicationScenario";
import {
  bundleFor as buildBundle,
  snapshotFor as buildSnapshot,
} from "../../src/features/overview/fixtures/observationFixtures";
import type { FleetQuery } from "../../src/features/overview/model/fleet";

export const fromMs = MOCK_APPLICATION_SCENARIO.window.fromMs;
export const toMs = MOCK_APPLICATION_SCENARIO.window.toMs;
export const query: FleetQuery = Object.freeze({
  context: Object.freeze({
    environmentId: MOCK_APPLICATION_SCENARIO.environment.id,
    appId: null,
    instanceId: null,
    resource: null,
    scope: "fleet",
    window: MOCK_APPLICATION_SCENARIO.window,
  }),
  page: 1,
  pageSize: 2,
  search: "",
  stepMs: 60_000,
});

export const bundleFor = (context = query.context, stepMs = query.stepMs) =>
  buildBundle(context, MOCK_APPLICATION_SCENARIO, stepMs);
export const snapshotFor = (input = query) => buildSnapshot(input, MOCK_APPLICATION_SCENARIO);
