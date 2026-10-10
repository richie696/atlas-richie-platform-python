import { MOCK_OBSERVATION_SCENARIO } from "./mockObservationScenario";
import { MOCK_RULE_SCENARIO } from "./mockRuleScenario";

/** Cross-page application facts composed from the canonical observation and rule scenarios. */
const deployment = MOCK_RULE_SCENARIO.deployment;
const eventBinding = MOCK_RULE_SCENARIO.bindings.find(
  (binding) => binding.id === deployment.eventVersion.bindingId,
);
if (!eventBinding) throw new Error("The demo application scenario requires the event rule binding");

const eventApplicationInstances = MOCK_OBSERVATION_SCENARIO.instances.filter(
  (instance) => instance.appId === eventBinding.appId,
);
const unknownRuleReceipt = Object.freeze({
  state: "unknown" as const,
  desiredVersionId: null,
  appliedVersionId: null,
  receivedOffsetMs: null,
});

const instances = Object.freeze(
  MOCK_OBSERVATION_SCENARIO.instances.map((instance) => {
    if (instance.appId !== eventBinding.appId)
      return Object.freeze({ ...instance, ruleReceipt: unknownRuleReceipt });

    const applied = instance.id === deployment.receipt.appliedInstanceId;
    return Object.freeze({
      ...instance,
      ruleReceipt: Object.freeze({
        state: applied ? deployment.receipt.appliedState : deployment.receipt.pendingState,
        desiredVersionId: deployment.eventVersion.id,
        appliedVersionId: applied ? deployment.eventVersion.id : deployment.baselineVersion.id,
        receivedOffsetMs: deployment.receipt.lastReportAtOffsetMs,
      }),
    });
  }),
);

const applications = Object.freeze(
  MOCK_OBSERVATION_SCENARIO.applications.map((application) => {
    const applicationInstances = instances.filter((instance) => instance.appId === application.id);
    return Object.freeze({
      ...application,
      ruleCoverage: Object.freeze({
        expected: applicationInstances.length,
        reporting: applicationInstances.filter(
          (instance) => instance.ruleReceipt.state === deployment.receipt.appliedState,
        ).length,
        inventorySource: MOCK_OBSERVATION_SCENARIO.inventorySource,
      }),
    });
  }),
);

export const MOCK_APPLICATION_SCENARIO = Object.freeze({
  ...MOCK_OBSERVATION_SCENARIO,
  applications,
  instances,
});
