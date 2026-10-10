import assert from "node:assert/strict";
import { test } from "node:test";
import { APP_CONSOLE_MOCK_HANDLERS } from "../../src/app/api/mockConsoleHandlers";
import { CONSOLE_OPERATIONS } from "../../src/app/api/consoleContract";

test("MOCK-OPERATION-COVERAGE: every Console method/path has an app-level HTTP mock", () => {
  const registered = new Set(
    APP_CONSOLE_MOCK_HANDLERS.map(({ info }) => `${info.method} ${info.path.replace(/^\*/, "")}`),
  );
  const missing = CONSOLE_OPERATIONS.flatMap(({ endpoint, operationId }) => {
    const path = endpoint.url.path.replace(/\{([^}]+)\}/g, ":$1");
    const operation = `${endpoint.url.method} ${path}`;
    return registered.has(operation) ? [] : [{ operationId, operation }];
  });

  assert.deepEqual(missing, [], "each Console operation must have an explicit MSW projection");
});
