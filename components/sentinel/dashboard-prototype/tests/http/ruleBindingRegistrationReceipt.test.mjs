import assert from "node:assert/strict";
import { test } from "node:test";
import { http, HttpResponse } from "msw/http";
import { setupServer } from "msw/node";
import { AppError, AppErrorKind, StateStore } from "@richie696/react-framework";
import { createConsoleTransport } from "../../src/core/api/transport/consoleTransport";
import { createRuleSetHttp } from "../../src/features/rules/api/ruleSetHttp";
import {
  createRuleBindingRegistrationCommand,
  createRuleBindingRegistrationReceiptResource,
} from "../../src/features/rules/application/ruleBindingRegistration";
import { validRuleBindingRegistrationReceipt } from "../../src/features/rules/model/ruleBindingRegistration";
import { ruleSet } from "../fixtures/ruleSets";

const origin = "http://binding-receipt.test";
const requestKey = "binding-create-receipt-1";
const registration = {
  requestKey,
  bindingId: ruleSet.binding.id,
  environmentId: ruleSet.binding.environmentId,
  appId: ruleSet.binding.appId,
  kind: ruleSet.binding.kind,
  profile: ruleSet.binding.profile,
  sourceId: ruleSet.binding.sourceId,
  sourceRevision: "source-revision-1",
  target: {
    provider: "nacos",
    namespace: "namespace-one",
    group: "DEFAULT_GROUP",
    dataId: "flow-rules.json",
  },
};
const completed = {
  requestKey,
  bindingId: registration.bindingId,
  status: "completed",
  binding: ruleSet.binding,
};
const accessState = () => {
  const state = new StateStore({ ownerKey: "admin-session-current", allowed: true });
  return { state, observer: { read: state.getSnapshot, subscribe: state.subscribe } };
};
async function withPort(handlers, run) {
  const server = setupServer(...handlers);
  server.listen({ onUnhandledRequest: "error" });
  let sequence = 0;
  const transport = createConsoleTransport({
    baseUrl: origin,
    owner: () => "admin-session-current",
    onUnauthorized: () => {},
    requestId: () => `binding-receipt-${++sequence}`,
  });
  try {
    await run(createRuleSetHttp(transport));
  } finally {
    transport.dispose();
    server.close();
  }
}

test("RULE-BINDING-RECEIPT-HTTP: exact path is a no-store read and validates the original safe binding", async () => {
  let observedUrl = "";
  await withPort(
    [
      http.get(
        `${origin}/api/v1/rulesets/:bindingId/registration-operations/:requestKey`,
        ({ request }) => {
          observedUrl = request.url;
          return HttpResponse.json(completed, {
            headers: {
              "x-request-id": request.headers.get("x-request-id"),
              "cache-control": "no-store",
              vary: "Cookie",
            },
          });
        },
      ),
    ],
    async (port) => {
      const receipt = await port.readBindingRegistration(
        registration.bindingId,
        requestKey,
        new AbortController().signal,
      );
      assert.deepEqual(receipt, completed);
    },
  );
  assert.match(observedUrl, /registration-operations\/binding-create-receipt-1$/);
});

test("RULE-BINDING-RECEIPT-UNKNOWN: inspect is read-only; not-found never unlocks or replays create", async () => {
  const { observer } = accessState();
  let writes = 0;
  let reads = 0;
  let receipt = {
    requestKey,
    bindingId: registration.bindingId,
    status: "not_found",
    binding: null,
  };
  const port = {
    async registerBinding() {
      writes += 1;
      throw new AppError(AppErrorKind.SERVER, "private failure", { status: 503 });
    },
    async readBindingRegistration(bindingId, key) {
      reads += 1;
      assert.equal(bindingId, registration.bindingId);
      assert.equal(key, requestKey);
      return receipt;
    },
  };
  const catalog = {
    asOfMs: 1,
    items: [
      {
        id: registration.sourceId,
        revision: registration.sourceRevision,
        name: "Nacos",
        provider: "nacos",
        namespace: "namespace-one",
      },
    ],
  };
  const command = createRuleBindingRegistrationCommand(port, observer);
  const input = { command: registration, sourceCatalog: catalog };
  await assert.rejects(command.run(input));
  assert.equal(command.getSnapshot().status, "result-unknown");
  assert.equal(writes, 1);

  const inspection = createRuleBindingRegistrationReceiptResource(port, observer);
  const missing = await inspection.load({
    bindingId: registration.bindingId,
    requestKey,
  });
  assert.equal(missing.status, "not_found");
  assert.equal(command.getSnapshot().status, "result-unknown");
  assert.equal(writes, 1);

  receipt = completed;
  const found = await inspection.load({ bindingId: registration.bindingId, requestKey });
  assert.equal(found.status, "completed");
  assert.equal(command.getSnapshot().status, "result-unknown");
  assert.equal(writes, 1);
  assert.equal(reads, 2);
  assert.equal(
    validRuleBindingRegistrationReceipt(
      { ...completed, requestKey: "another-request" },
      requestKey,
      registration.bindingId,
    ),
    false,
  );
  inspection.dispose();
  command.dispose();
});
