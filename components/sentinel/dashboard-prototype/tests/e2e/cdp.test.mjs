import assert from "node:assert/strict";
import { test } from "node:test";
import { connectE2EBrowser, Connection } from "./cdp.mjs";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

class FakeSocket extends EventTarget {
  sent = [];
  send(value) { this.sent.push(JSON.parse(value)); }
  close() { this.dispatchEvent(new Event("close")); }
  response(value) { this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify(value) })); }
}

test("CDP close rejects pending commands and refuses new work", async () => {
  const socket = new FakeSocket(), client = new Connection(socket);
  const pending = client.send("Page.navigate");
  const rejected = assert.rejects(pending, /connection closed/);
  client.close();
  await rejected;
  await assert.rejects(client.send("Page.enable"), /CDP 已关闭/);
});

test("CDP timeout rejects rather than leaving the test runner alive", async () => {
  const socket = new FakeSocket(), client = new Connection(socket, { timeoutMs: 5 });
  await assert.rejects(client.send("Runtime.evaluate"), /timed out/);
  client.close();
});

test("CDP response releases the timeout and transport errors reject immediately", async () => {
  const socket = new FakeSocket(), client = new Connection(socket);
  const result = client.send("Page.enable");
  socket.response({ id: socket.sent[0].id, result: { enabled: true } });
  assert.deepEqual(await result, { enabled: true });
  socket.send = () => { throw new Error("transport down"); };
  await assert.rejects(client.send("Page.enable"), /transport down/);
  client.close();
});

test("E2E browser connector refuses to run without an explicit endpoint", () => {
  const cdpModule = new URL("./cdp.mjs", import.meta.url).href;
  const { NODE_TEST_CONTEXT: _runnerContext, ...environment } = process.env;
  delete environment.SENTINEL_E2E_CDP_URL;
  const result = spawnSync(
    process.execPath,
    ["--input-type=module", "-e", `import { connectE2EBrowser } from ${JSON.stringify(cdpModule)}; await connectE2EBrowser();`],
    {
      env: {
        ...environment,
        EDGE_BIN: "/usr/bin/false",
      },
      encoding: "utf8",
      timeout: 5000,
    },
  );

  assert.equal(result.error, undefined);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /SENTINEL_E2E_CDP_URL is required/);
  assert.doesNotMatch(result.stderr, /ENOENT|Microsoft Edge/);
});

test("E2E and visual capture fail fast without the Edge DevTools endpoint", () => {
  const cwd = fileURLToPath(new URL("../../", import.meta.url));
  // A nested node:test child must not inherit the parent's IPC-only runner mode.
  const { NODE_TEST_CONTEXT: _runnerContext, ...environment } = process.env;
  delete environment.SENTINEL_E2E_CDP_URL;
  for (const arguments_ of [
    ["--test", "--test-reporter=spec", "tests/e2e/app.e2e.test.mjs"],
    ["tests/visual/capture-baseline.mjs", "capture", "/private/tmp/sentinel-tool-negative-unused"],
  ]) {
    const result = spawnSync(process.execPath, arguments_, {
      cwd, env: { ...environment, EDGE_BIN: "/usr/bin/false" }, encoding: "utf8", timeout: 10000,
    });
    assert.equal(result.error, undefined);
    assert.notEqual(result.status, 0, `E2E incorrectly accepted a missing endpoint: ${result.stdout}`);
    assert.match(result.stdout + result.stderr, /SENTINEL_E2E_CDP_URL is required/);
    assert.doesNotMatch(result.stdout + result.stderr, /Microsoft Edge 提前退出|ENOENT/);
  }
});
