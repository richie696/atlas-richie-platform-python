import assert from "node:assert/strict";
import { test } from "node:test";
import { resolveConsoleRuntimeConfiguration } from "../../src/core/api/runtime/consoleRuntimeConfiguration";
import { bootstrapConsoleApplication } from "../../src/core/api/runtime/bootstrapConsoleApplication";
import { requiresConsoleMockInterception } from "../../src/core/api/runtime/consoleRuntimeConfiguration";

test("RUNTIME-MOCK: demo profile defaults to same-origin mock and rejects live API override", () => {
  assert.deepEqual(resolveConsoleRuntimeConfiguration({}, "http://localhost:5173", "demo"), {
    mode: "mock",
    apiBaseUrl: "http://localhost:5173",
  });
  assert.throws(
    () =>
      resolveConsoleRuntimeConfiguration(
        { mode: "mock", apiBaseUrl: "https://production.example.com" },
        "http://localhost:5173",
        "demo",
      ),
    /not allowed in mock mode/,
  );
});

test("RUNTIME-LIVE: explicit live mode requires a safe absolute API origin", () => {
  assert.deepEqual(
    resolveConsoleRuntimeConfiguration(
      { mode: "live", apiBaseUrl: "https://console.example.com/" },
      "http://localhost:5173",
      "demo",
    ),
    { mode: "live", apiBaseUrl: "https://console.example.com" },
  );
  for (const apiBaseUrl of [
    undefined,
    "/api",
    "https://user:secret@console.example.com",
    "https://console.example.com/api",
  ]) {
    assert.throws(() =>
      resolveConsoleRuntimeConfiguration(
        { mode: "live", apiBaseUrl },
        "http://localhost:5173",
        "demo",
      ),
    );
  }
});

test("RUNTIME-MODE: live-only production defaults to same-origin and rejects Mock", () => {
  assert.deepEqual(
    resolveConsoleRuntimeConfiguration({}, "https://dashboard.example.com", "live-only"),
    { mode: "live", apiBaseUrl: "https://dashboard.example.com" },
  );
  assert.throws(
    () =>
      resolveConsoleRuntimeConfiguration({ mode: "mock" }, "http://localhost:5173", "live-only"),
    /unavailable in the live-only production build/,
  );
  assert.throws(
    () => resolveConsoleRuntimeConfiguration({ mode: "other" }, "http://localhost:5173", "demo"),
    /VITE_CONSOLE_MODE/,
  );
});

test("RUNTIME-BOOTSTRAP: request interception settles before services and pages can issue requests", async () => {
  const configuration = { mode: "mock", apiBaseUrl: "http://localhost:5173" };
  const calls = [];
  let releaseInterception;
  const interceptionReady = new Promise((resolve) => {
    releaseInterception = resolve;
  });
  const services = { request: () => calls.push("request") };
  const boot = bootstrapConsoleApplication(configuration, {
    startInterception: async () => {
      calls.push("interceptor-start");
      await interceptionReady;
      calls.push("interceptor-ready");
    },
    createServices: () => {
      calls.push("services-created");
      return services;
    },
    mount: (createdServices) => {
      assert.strictEqual(createdServices, services);
      calls.push("page-mounted");
      createdServices.request();
    },
  });

  await Promise.resolve();
  assert.deepEqual(calls, ["interceptor-start"]);
  releaseInterception();
  assert.strictEqual(await boot, services);
  assert.deepEqual(calls, [
    "interceptor-start",
    "interceptor-ready",
    "services-created",
    "page-mounted",
    "request",
  ]);
});

test("RUNTIME-BOOTSTRAP-FAIL-CLOSED: interceptor failure never creates services or mounts request-capable pages", async () => {
  const calls = [];
  await assert.rejects(
    bootstrapConsoleApplication(
      { mode: "mock", apiBaseUrl: "http://localhost:5173" },
      {
        startInterception: async () => {
          calls.push("interceptor-start");
          throw new Error("worker failed");
        },
        createServices: () => {
          calls.push("services-created");
          return {};
        },
        mount: () => calls.push("page-mounted"),
      },
    ),
    /worker failed/,
  );
  assert.deepEqual(calls, ["interceptor-start"]);
});

test("RUNTIME-INTERCEPTOR-POLICY: only mock mode requires the browser request interceptor", () => {
  assert.equal(requiresConsoleMockInterception("mock"), true);
  assert.equal(requiresConsoleMockInterception("live"), false);
});
