import assert from "node:assert/strict";
import { test } from "node:test";
import { setupServer } from "msw/node";
import { createConsoleTransport } from "../../src/core/api/transport/consoleTransport";
import { APP_CONSOLE_MOCK_HANDLERS } from "../../src/app/api/mockConsoleHandlers";
import { MOCK_APPLICATION_SCENARIO } from "../../src/app/api/mockApplicationScenario";
import { MOCK_RULE_SCENARIO } from "../../src/app/api/mockRuleScenario";
import { createInstanceHttp } from "../../src/features/applications/api/instanceHttp";
import {
  INSTANCE_LAYER,
  instanceSelection,
} from "../../src/features/applications/model/instanceObservation";
import { catalogQuery } from "../fixtures/instances";

test("INSTANCE-MOCK: real HTTP adapters reach explicit catalog and selected-instance mock handlers", async () => {
  const origin = "http://instance-mock.test";
  const server = setupServer(...APP_CONSOLE_MOCK_HANDLERS);
  server.listen({ onUnhandledRequest: "error" });
  const transport = createConsoleTransport({
    baseUrl: origin,
    owner: () => "synthetic-instance-session",
    onUnauthorized: () => {},
  });
  try {
    const port = createInstanceHttp(transport);
    const query = { ...catalogQuery, pageSize: 20 };
    const catalog = await port.readCatalog(query, new AbortController().signal);
    assert.deepEqual(
      catalog.items.map((item) => item.instanceId),
      ["instance-1", "instance-2", "instance-3", "instance-4"],
    );
    const deployment = MOCK_RULE_SCENARIO.deployment;
    const eventAppId = MOCK_RULE_SCENARIO.bindings.find(
      (binding) => binding.id === deployment.eventVersion.bindingId,
    ).appId;
    assert.deepEqual(
      catalog.items.map((instance) => [
        instance.instanceId,
        instance.ruleReceipt.state,
        instance.ruleReceipt.desiredVersionId,
        instance.ruleReceipt.appliedVersionId,
      ]),
      MOCK_APPLICATION_SCENARIO.instances.map((instance) => [
        instance.id,
        instance.ruleReceipt.state,
        instance.ruleReceipt.desiredVersionId,
        instance.ruleReceipt.appliedVersionId,
      ]),
    );
    assert.deepEqual(
      catalog.items
        .filter((instance) => instance.appId === eventAppId)
        .map((instance) => [instance.instanceId, instance.ruleReceipt.state]),
      [
        [deployment.receipt.appliedInstanceId, deployment.receipt.appliedState],
        [
          MOCK_APPLICATION_SCENARIO.instances.find(
            (instance) =>
              instance.appId === eventAppId && instance.id !== deployment.receipt.appliedInstanceId,
          ).id,
          deployment.receipt.pendingState,
        ],
      ],
    );
    for (const scope of [INSTANCE_LAYER.Host, INSTANCE_LAYER.Container, INSTANCE_LAYER.Process]) {
      const selection = instanceSelection(catalog.items[0], query.context, scope);
      const detail = await port.readInstance(selection, new AbortController().signal);
      assert.equal(detail.instance.processEpoch, selection.processEpoch);
      assert.equal(detail.instance.ruleReceipt.processEpoch, selection.processEpoch);
      assert.equal(detail.query.context.scope, scope);
      assert.equal(detail.metrics !== null, scope === INSTANCE_LAYER.Process);
      if (detail.metrics) assert.equal(detail.metrics.query.context.instanceId, "instance-1");
    }
  } finally {
    transport.dispose();
    server.close();
  }
});

test("INSTANCE-MOCK-RETIREMENT: missing identities and retired process epochs are explicit HTTP failures", async () => {
  const origin = "http://instance-retirement.test";
  const server = setupServer(...APP_CONSOLE_MOCK_HANDLERS);
  server.listen({ onUnhandledRequest: "error" });
  const transport = createConsoleTransport({
    baseUrl: origin,
    owner: () => "synthetic-instance-session",
    onUnauthorized: () => {},
  });
  try {
    const port = createInstanceHttp(transport);
    const query = { ...catalogQuery, pageSize: 20 };
    const catalog = await port.readCatalog(query, new AbortController().signal);
    const selection = instanceSelection(catalog.items[0], query.context, INSTANCE_LAYER.Process);
    const missing = {
      ...selection,
      context: { ...selection.context, instanceId: "missing-instance" },
    };
    await assert.rejects(port.readInstance(missing, new AbortController().signal), (error) => {
      assert.equal(error.status, 404);
      return true;
    });
    const retired = { ...selection, processEpoch: "retired-incarnation" };
    await assert.rejects(port.readInstance(retired, new AbortController().signal), (error) => {
      assert.equal(error.status, 409);
      assert.equal(error.code, "instance_incarnation_changed");
      return true;
    });
  } finally {
    transport.dispose();
    server.close();
  }
});
