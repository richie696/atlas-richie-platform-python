/** Test-only facade binding feature fixture builders to the app-owned demo scenario. */
import { MOCK_APPLICATION_SCENARIO } from "../../src/app/api/mockApplicationScenario";
import {
  catalogFor as buildCatalog,
  detailFor as buildDetail,
  instanceFor as buildInstance,
} from "../../src/features/applications/fixtures/instanceObservationFixtures";
import type {
  InstanceCatalogQuery,
  InstanceDetailQuery,
} from "../../src/features/applications/model/instanceObservation";
import { instanceSelection } from "../../src/features/applications/model/instanceObservation";

export const catalogQuery: InstanceCatalogQuery = Object.freeze({
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
  attentionOnly: false,
});

export const instanceFor = (index: number, input = catalogQuery) =>
  buildInstance(index, input, MOCK_APPLICATION_SCENARIO);
export const catalogFor = (input = catalogQuery) => buildCatalog(input, MOCK_APPLICATION_SCENARIO);
export const detailFor = (
  input: InstanceDetailQuery = instanceSelection(instanceFor(1), catalogQuery.context),
) => buildDetail(input, MOCK_APPLICATION_SCENARIO);
