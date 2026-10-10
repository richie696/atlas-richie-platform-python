import assert from "node:assert/strict";
import { test } from "node:test";
import { assertSupportedBrowserExecutable, Connection } from "./cdp.mjs";
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

test("browser launcher rejects Microsoft Edge executable paths", () => {
  for (const executable of [
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    "/usr/bin/microsoft-edge-stable",
  ]) {
    assert.throws(() => assertSupportedBrowserExecutable(executable), /Microsoft Edge is blocked/);
  }

  const chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
  assert.equal(assertSupportedBrowserExecutable(chrome), chrome);
});

test("launchBrowser refuses an Edge override before starting any browser process", () => {
  const cdpModule = new URL("./cdp.mjs", import.meta.url).href;
  const { NODE_TEST_CONTEXT: _runnerContext, ...environment } = process.env;
  const result = spawnSync(
    process.execPath,
    ["--input-type=module", "-e", `import { launchBrowser } from ${JSON.stringify(cdpModule)}; await launchBrowser();`],
    {
      env: {
        ...environment,
        CHROME_BIN: "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
      },
      encoding: "utf8",
      timeout: 5000,
    },
  );

  assert.equal(result.error, undefined);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /Microsoft Edge is blocked/);
  assert.doesNotMatch(result.stderr, /Chrome 提前退出|ENOENT/);
});

test("failed Chrome launch cannot produce a green E2E file or capture exit", () => {
  const cwd = fileURLToPath(new URL("../../", import.meta.url));
  // A nested node:test child must not inherit the parent's IPC-only runner mode.
  const { NODE_TEST_CONTEXT: _runnerContext, ...environment } = process.env;
  for (const arguments_ of [
    ["--test", "--test-reporter=spec", "tests/e2e/app.e2e.test.mjs"],
    ["tests/visual/capture-baseline.mjs", "capture", "/private/tmp/sentinel-tool-negative-unused"],
  ]) {
    const result = spawnSync(process.execPath, arguments_, {
      cwd, env: { ...environment, CHROME_BIN: "/usr/bin/false" }, encoding: "utf8", timeout: 10000,
    });
    assert.equal(result.error, undefined);
    assert.notEqual(result.status, 0, `Failed Chrome incorrectly accepted: ${result.stdout}`);
    assert.match(result.stdout + result.stderr, /Chrome 提前退出/);
  }
});
