import assert from "node:assert/strict";
import { test } from "node:test";
import { AppError, AppErrorKind, StateStore } from "@richie696/react-framework";
import { createSourceRegistrationWorkflow } from "../../src/features/system/application/sourceRegistrationWorkflow";
import { sourceRegistrationDraft } from "../../src/features/system/model/sourceRegistration";

const now = Date.parse("2026-10-10T00:00:00Z");
const source = Object.freeze({
  id: "synthetic-source",
  revision: "source-revision-one",
  name: "Synthetic config source",
  provider: "nacos",
  endpoint: "https://config.example.test",
  namespace: "synthetic-namespace",
  authenticationMode: "none",
  credentialConfigured: false,
});

test("SOURCE-INSPECT-CONCURRENCY: unknown source write permits one correlated lookup and no resubmit", async () => {
  let resolveLookup;
  let writes = 0;
  let lookups = 0;
  let requestKey;
  const access = new StateStore({ ownerKey: "source-owner", allowed: true });
  const workflow = createSourceRegistrationWorkflow(
    {
      readSources: async () => ({ asOfMs: now, items: [source] }),
      checkSource: async () => ({
        status: "reachable",
        capabilities: ["read"],
        checkedAtMs: now,
        expiresAtMs: now + 60_000,
      }),
      mutateSource: async (mutation) => {
        writes++;
        requestKey = mutation.requestKey;
        throw new AppError(AppErrorKind.NETWORK, "PRIVATE-CREDENTIAL-ERROR");
      },
      readSourceOperation: async (key) => {
        lookups++;
        return new Promise((resolve) => {
          resolveLookup = resolve;
          assert.equal(key, requestKey);
        });
      },
    },
    { read: access.getSnapshot, subscribe: access.subscribe },
    () => "source-operation-one",
  );

  await workflow.registry.load(null);
  await assert.rejects(
    workflow.submit(sourceRegistrationDraft(source), source),
    (error) => !error.message.includes("PRIVATE-CREDENTIAL"),
  );
  assert.equal(workflow.getSnapshot().command.status, "result-unknown");
  assert.doesNotMatch(JSON.stringify(workflow.getSnapshot()), /PRIVATE-CREDENTIAL/);

  const inspection = workflow.inspect();
  await Promise.resolve();
  assert.equal(workflow.getSnapshot().inspecting, true);
  await assert.rejects(workflow.inspect(), (error) => error.kind === AppErrorKind.DUPLICATE);
  await assert.rejects(
    workflow.submit(sourceRegistrationDraft(source), source),
    (error) => error.kind === AppErrorKind.DUPLICATE,
  );
  assert.equal(writes, 1);
  assert.equal(lookups, 1);

  resolveLookup({ status: "pending", requestKey });
  await inspection;
  assert.equal(workflow.getSnapshot().inspecting, false);
  assert.equal(workflow.getSnapshot().command.status, "result-unknown");
  assert.equal(workflow.getSnapshot().operation.requestKey, requestKey);
  await assert.rejects(
    workflow.submit(sourceRegistrationDraft(source), source),
    (error) => error.kind === AppErrorKind.DUPLICATE,
  );

  const completion = workflow.inspect();
  await Promise.resolve();
  assert.equal(lookups, 2);
  resolveLookup({ status: "completed", requestKey, record: source });
  await completion;
  assert.equal(workflow.getSnapshot().command.status, "success");
  assert.equal(writes, 1);
  workflow.dispose();
});

test("SOURCE-INSPECT-OWNER: revoked owner cannot publish a late operation lookup", async () => {
  let releaseLookup;
  let lookupStarted;
  const lookupStart = new Promise((resolve) => (lookupStarted = resolve));
  let writes = 0;
  let requestKey;
  const access = new StateStore({ ownerKey: "source-owner", allowed: true });
  const workflow = createSourceRegistrationWorkflow(
    {
      readSources: async () => ({ asOfMs: now, items: [source] }),
      checkSource: async () => ({
        status: "reachable",
        capabilities: ["read"],
        checkedAtMs: now,
        expiresAtMs: now + 60_000,
      }),
      mutateSource: async (mutation) => {
        writes++;
        requestKey = mutation.requestKey;
        throw new AppError(AppErrorKind.NETWORK, "PRIVATE-CREDENTIAL-ERROR");
      },
      readSourceOperation: (key) => {
        assert.equal(key, requestKey);
        return new Promise((resolve) => {
          releaseLookup = resolve;
          lookupStarted();
        });
      },
    },
    { read: access.getSnapshot, subscribe: access.subscribe },
    () => "source-operation-one",
  );

  await workflow.registry.load(null);
  await assert.rejects(workflow.submit(sourceRegistrationDraft(source), source));
  assert.equal(workflow.getSnapshot().command.status, "result-unknown");
  const inspection = workflow.inspect();
  await lookupStart;
  assert.equal(workflow.getSnapshot().inspecting, true);

  access.set({ ownerKey: "source-owner-next", allowed: true });
  await assert.rejects(inspection, (error) => error.kind === AppErrorKind.CANCELLED);
  assert.equal(workflow.getSnapshot().authorized, false);
  assert.equal(workflow.getSnapshot().operation, null);
  assert.equal(workflow.getSnapshot().command.status, "idle");
  assert.equal(workflow.getSnapshot().inspecting, false);

  releaseLookup({ status: "completed", requestKey, record: source });
  await new Promise(setImmediate);
  assert.equal(workflow.getSnapshot().authorized, false);
  assert.equal(workflow.getSnapshot().operation, null);
  assert.equal(workflow.getSnapshot().command.status, "idle");
  assert.equal(writes, 1);
  await assert.rejects(
    workflow.submit(sourceRegistrationDraft(source), source),
    (error) => error.kind === AppErrorKind.FORBIDDEN,
  );
  assert.doesNotMatch(JSON.stringify(workflow.getSnapshot()), /PRIVATE-CREDENTIAL/);
  workflow.dispose();
});
