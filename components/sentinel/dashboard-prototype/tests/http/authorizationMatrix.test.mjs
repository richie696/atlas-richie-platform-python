import assert from "node:assert/strict";
import { test } from "node:test";
import { setupServer } from "msw/node";
import { APP_CONSOLE_MOCK_HANDLERS } from "../../src/app/api/mockConsoleHandlers";
import { MOCK_RULE_SCENARIO } from "../../src/app/api/mockRuleScenario";
import { createConsoleTransport } from "../../src/core/api/transport/consoleTransport";
import { MOCK_ROLE_STORAGE_KEY } from "../../src/core/api/mock/mockRole";
import { createAccountManagementHttp } from "../../src/features/identity/api/accountManagementHttp";
import { createMetricsHttp } from "../../src/features/realtime/api/metricsHttp";
import { createRuleSetHttp } from "../../src/features/rules/api/ruleSetHttp";
import { createSourceRegistrationHttp } from "../../src/features/system/api/sourceRegistrationHttp";
import { OPERATIONAL_METRICS } from "../../src/shared/model/observation";

const origin = "http://authorization-matrix.test";
const signal = () => new AbortController().signal;

test("APP-MOCK-AUTHORIZATION-MATRIX: viewer reads charts but cannot inspect admin data across features", async () => {
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  const storage = new Map([[MOCK_ROLE_STORAGE_KEY, "view"]]);
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      localStorage: {
        getItem: (key) => storage.get(key) ?? null,
        setItem: (key, value) => storage.set(key, value),
      },
    },
  });

  const server = setupServer(...APP_CONSOLE_MOCK_HANDLERS);
  server.listen({ onUnhandledRequest: "error" });
  let unauthorizedTransitions = 0;
  const transport = createConsoleTransport({
    baseUrl: origin,
    owner: () => "viewer-session",
    onUnauthorized: () => unauthorizedTransitions++,
  });

  try {
    const query = {
      context: {
        environmentId: "test-env",
        appId: "app-one",
        instanceId: null,
        resource: null,
        scope: "application",
        window: {
          fromMs: Date.parse("2026-10-06T23:55:00Z"),
          toMs: Date.parse("2026-10-07T00:10:00Z"),
        },
      },
      metrics: OPERATIONAL_METRICS,
      stepMs: 60_000,
    };
    const metrics = await createMetricsHttp(transport).readMetrics(query, signal());
    assert.deepEqual(metrics.query, query);
    assert.equal(metrics.summary.length, OPERATIONAL_METRICS.length);

    const deniedReads = [
      createAccountManagementHttp(transport).listAccounts(
        { page: 1, pageSize: 20, search: "" },
        signal(),
      ),
      createSourceRegistrationHttp(transport).readSources(signal()),
      createRuleSetHttp(transport).readDrafts(
        MOCK_RULE_SCENARIO.deployment.eventVersion.bindingId,
        signal(),
      ),
    ];
    for (const deniedRead of deniedReads) {
      await assert.rejects(deniedRead, (error) => {
        assert.equal(error.status, 403);
        assert.equal(error.code, "forbidden");
        return true;
      });
    }
    assert.equal(unauthorizedTransitions, 0, "403 must not be treated as expired authentication");
  } finally {
    transport.dispose();
    server.close();
    if (previousWindow) Object.defineProperty(globalThis, "window", previousWindow);
    else delete globalThis.window;
  }
});
