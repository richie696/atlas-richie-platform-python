import { test } from "node:test";
import assert from "node:assert/strict";
import { AppError, AppErrorKind, StateStore } from "@richie696/react-framework";
import {
  prepareRuleBindingRegistration,
} from "../../src/features/rules/model/ruleBindingRegistration";
import { createRuleBindingRegistrationCommand } from "../../src/features/rules/application/ruleBindingRegistration";
import { ruleSet } from "../fixtures/ruleSets";

const source = {
  id: "source-one",
  revision: "source-revision-one",
  name: "Internal Nacos",
  provider: "nacos",
  namespace: "namespace-one",
};
const sourceCatalog = { asOfMs: 1_791_331_800_000, items: [source] };
const draft = {
  bindingId: "orders-flow",
  environmentId: "test-env",
  appId: "app-one",
  kind: ruleSet.binding.kind,
  profile: "sentinel-python-v1",
  sourceId: source.id,
  namespace: " namespace-one ",
  group: " DEFAULT_GROUP ",
  dataId: " flow-rules ",
  datacenter: "",
  key: "",
};
const accessState = () => {
  const state = new StateStore({ ownerKey: "admin-session", allowed: true });
  return { state, observer: { read: state.getSnapshot, subscribe: state.subscribe } };
};
const prepared = (patch = {}) =>
  prepareRuleBindingRegistration(
    { ...draft, ...patch },
    source,
    "request-one",
  );

test("RULE-BINDING-REGISTRATION-MODEL: capture the selected source revision and normalize only the active provider target", () => {
  assert.deepEqual(prepared(), {
    requestKey: "request-one",
    bindingId: "orders-flow",
    environmentId: "test-env",
    appId: "app-one",
    kind: ruleSet.binding.kind,
    profile: "sentinel-python-v1",
    sourceId: "source-one",
    sourceRevision: "source-revision-one",
    target: {
      provider: "nacos",
      namespace: "namespace-one",
      group: "DEFAULT_GROUP",
      dataId: "flow-rules",
    },
  });

  const consul = {
    id: "consul-one",
    revision: "consul-revision-one",
    name: "Internal Consul",
    provider: "consul",
    datacenter: "dc-one",
  };
  assert.deepEqual(
    prepareRuleBindingRegistration(
      {
        ...draft,
        sourceId: consul.id,
        namespace: "ignored",
        datacenter: " dc-one ",
        key: " services/rules ",
      },
      consul,
      "request-two",
    )?.target,
    { provider: "consul", datacenter: "dc-one", key: "services/rules" },
  );
  for (const invalid of [
    { ...draft, bindingId: " " },
    { ...draft, group: "" },
    { ...draft, dataId: "" },
  ]) assert.equal(prepared(invalid), null);
  assert.equal(
    prepareRuleBindingRegistration(draft, { ...source, revision: " " }, "request-one"),
    null,
  );
});

test("RULE-BINDING-REGISTRATION-COMMAND: stale source revision and denied owner never dispatch", async () => {
  const { state, observer } = accessState();
  let writes = 0;
  const command = createRuleBindingRegistrationCommand(
    { async registerBinding() { writes += 1; return ruleSet.binding; } },
    observer,
  );
  const registration = prepared();
  await assert.rejects(
    command.run({
      command: { ...registration, sourceRevision: "stale-revision" },
      sourceCatalog,
    }),
  );
  assert.equal(command.getSnapshot().status, "conflict");
  command.reset();

  state.set({ ownerKey: "admin-session", allowed: false });
  await assert.rejects(command.run({ command: registration, sourceCatalog }));
  assert.equal(command.getSnapshot().status, "error");
  assert.equal(writes, 0);
  command.dispose();
  state.complete();
});

test("RULE-BINDING-REGISTRATION-COMMAND: one matching receipt succeeds and malformed identity is rejected", async () => {
  const { state, observer } = accessState();
  const registration = prepared();
  let writes = 0;
  const command = createRuleBindingRegistrationCommand(
    {
      async registerBinding(input) {
        writes += 1;
        assert.deepEqual(input, registration);
        return {
          ...ruleSet.binding,
          id: input.bindingId,
          environmentId: input.environmentId,
          appId: input.appId,
          kind: input.kind,
          profile: input.profile,
          sourceId: input.sourceId,
        };
      },
    },
    observer,
  );
  const result = await command.run({ command: registration, sourceCatalog });
  assert.equal(result.id, registration.bindingId);
  assert.equal(command.getSnapshot().status, "success");
  assert.equal(writes, 1);
  command.dispose();

  const invalid = createRuleBindingRegistrationCommand(
    { async registerBinding() { return { ...ruleSet.binding, id: "foreign-binding" }; } },
    observer,
  );
  await assert.rejects(invalid.run({ command: registration, sourceCatalog }));
  assert.equal(invalid.getSnapshot().status, "error");
  assert.equal(invalid.getSnapshot().error.code, "rule_binding_receipt_invalid");
  invalid.dispose();
  state.complete();
});

test("RULE-BINDING-REGISTRATION-COMMAND: a second submit while pending is rejected without a second write", async () => {
  const { state, observer } = accessState();
  const registration = prepared();
  let release;
  let writes = 0;
  const command = createRuleBindingRegistrationCommand(
    {
      registerBinding(input) {
        writes += 1;
        return new Promise((resolve) => {
          release = () =>
            resolve({
              ...ruleSet.binding,
              id: input.bindingId,
              environmentId: input.environmentId,
              appId: input.appId,
              kind: input.kind,
              profile: input.profile,
              sourceId: input.sourceId,
            });
        });
      },
    },
    observer,
  );
  const first = command.run({ command: registration, sourceCatalog });
  await Promise.resolve();
  await assert.rejects(command.run({ command: registration, sourceCatalog }));
  assert.equal(command.getSnapshot().status, "pending");
  assert.equal(writes, 1);
  release();
  await first;
  assert.equal(command.getSnapshot().status, "success");
  command.dispose();
  state.complete();
});

test("RULE-BINDING-REGISTRATION-COMMAND: revoke during flight hides a late receipt and upstream detail", async () => {
  const { state, observer } = accessState();
  let release;
  const command = createRuleBindingRegistrationCommand(
    {
      registerBinding() {
        return new Promise((resolve) => {
          release = resolve;
        });
      },
    },
    observer,
  );
  const pending = command.run({ command: prepared(), sourceCatalog });
  await Promise.resolve();
  state.set({ ownerKey: "admin-session", allowed: false });
  release(ruleSet.binding);
  await assert.rejects(pending);
  assert.equal(command.getSnapshot().status, "error");
  assert.equal(command.getSnapshot().error.code, "rule_binding_receipt_invalid");
  assert.doesNotMatch(JSON.stringify(command.getSnapshot()), /PRIVATE|foreign/);
  command.dispose();
  state.complete();
});

test("RULE-BINDING-REGISTRATION-COMMAND: transport detail is redacted and uncertain outcome remains unknown", async () => {
  const { state, observer } = accessState();
  const command = createRuleBindingRegistrationCommand(
    {
      async registerBinding() {
        throw new AppError(AppErrorKind.NETWORK, "PRIVATE-CONFIGURATION-TOKEN");
      },
    },
    observer,
  );
  await assert.rejects(command.run({ command: prepared(), sourceCatalog }));
  assert.equal(command.getSnapshot().status, "result-unknown");
  assert.doesNotMatch(JSON.stringify(command.getSnapshot()), /PRIVATE-CONFIGURATION-TOKEN/);
  command.dispose();
  state.complete();
});
