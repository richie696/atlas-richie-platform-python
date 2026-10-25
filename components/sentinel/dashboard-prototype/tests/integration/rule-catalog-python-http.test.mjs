import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createServer } from "vite";

const dashboardRoot = fileURLToPath(new URL("../..", import.meta.url));
const consoleRoot = fileURLToPath(new URL("../../../sentinel-console", import.meta.url));
const pythonServer = fileURLToPath(
  new URL("../../../sentinel-console/tests/support/live_rule_catalog_server.py", import.meta.url),
);
const SESSION = "synthetic-rule-catalog-session-token-000000000001";

async function startConsole() {
  const child = spawn(
    process.env.SENTINEL_UV ?? "uv",
    [
      "run",
      "--project",
      consoleRoot,
      "--extra",
      "test",
      "--extra",
      "server",
      "python",
      pythonServer,
      "--port",
      "0",
    ],
    { cwd: consoleRoot, stdio: ["ignore", "pipe", "pipe"] },
  );
  let output = "";
  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");
  child.stdout.on("data", (chunk) => (output += chunk));
  child.stderr.on("data", (chunk) => (output += chunk));
  const ready = new Promise((resolve, reject) => {
    const deadline = setTimeout(
      () => reject(new Error(`Console startup timeout:\n${output}`)),
      60_000,
    );
    const check = () => {
      for (const line of output.split(/\r?\n/)) {
        try {
          const message = JSON.parse(line);
          if (message.ready === true && Number.isInteger(message.port)) {
            clearTimeout(deadline);
            resolve(message.port);
            return;
          }
        } catch {
          // Uvicorn and uv may emit non-JSON diagnostics before the ready record.
        }
      }
      if (child.exitCode !== null) {
        clearTimeout(deadline);
        reject(new Error(`Console exited before startup (${child.exitCode}):\n${output}`));
      }
    };
    child.stdout.on("data", check);
    child.stderr.on("data", check);
    child.once("error", (error) => {
      clearTimeout(deadline);
      reject(error);
    });
    child.once("exit", check);
    check();
  });
  return { child, port: await ready, output: () => output };
}

async function stopConsole(child) {
  if (child.exitCode !== null || child.signalCode !== null) return;
  child.kill("SIGTERM");
  let timer;
  await Promise.race([
    once(child, "exit"),
    new Promise((resolve) => (timer = setTimeout(resolve, 5_000))),
  ]);
  clearTimeout(timer);
  if (child.exitCode === null && child.signalCode === null) {
    child.kill("SIGKILL");
    await once(child, "exit");
  }
}

test(
  "T03.4 formal React rule-catalog HTTP adapter reads the authenticated Python Console route",
  { timeout: 120_000 },
  async () => {
    let consoleProcess;
    let consoleOutput = () => "";
    let vite;
    let authenticatedTransport;
    let anonymousTransport;
    try {
      const started = await startConsole();
      consoleProcess = started.child;
      consoleOutput = started.output;
      vite = await createServer({
        configFile: false,
        root: dashboardRoot,
        appType: "custom",
        optimizeDeps: { noDiscovery: true, include: [] },
        server: { middlewareMode: true, hmr: false, ws: false },
      });
      const [{ createConsoleTransport }, { createRuleSetHttp }, { createIdentityHttp }] =
        await Promise.all([
          vite.ssrLoadModule("/src/core/api/transport/consoleTransport.ts"),
          vite.ssrLoadModule("/src/features/rules/api/ruleSetHttp.ts"),
          vite.ssrLoadModule("/src/features/identity/api/identityAccessHttp.ts"),
        ]);
      const baseUrl = `http://127.0.0.1:${started.port}`;
      let csrfCookie = "";
      const makeTransport = (authenticated) =>
        createConsoleTransport({
          baseUrl,
          owner: () => "rule-catalog-live-test",
          onUnauthorized: () => {},
          fetch: async (input, init) => {
            const request = new Request(input, init);
            if (authenticated) {
              request.headers.set(
                "cookie",
                `sentinel_session=${SESSION}${csrfCookie ? `; __Host-sentinel_csrf=${csrfCookie}` : ""}`,
              );
              request.headers.set("origin", "http://localhost:5173");
            }
            const response = await fetch(request);
            const returnedCsrf = response.headers.get("x-sentinel-csrf");
            if (returnedCsrf) csrfCookie = returnedCsrf;
            return response;
          },
        });
      authenticatedTransport = makeTransport(true);
      anonymousTransport = makeTransport(false);
      const identityApi = createIdentityHttp(authenticatedTransport);
      const bootstrap = await identityApi.readBootstrap(new AbortController().signal);
      assert.equal(bootstrap.initialized, true);
      assert.match(csrfCookie, /^[A-Za-z0-9_-]{32,256}$/);
      const authenticatedApi = createRuleSetHttp(authenticatedTransport);
      const query = {
        environmentId: "prod",
        appId: "checkout",
        kind: "flow",
        search: "",
        page: 1,
        pageSize: 20,
      };
      const refresh = await authenticatedApi.refreshRuleCatalog(
        "prod",
        "checkout",
        new AbortController().signal,
      );
      assert.equal(refresh.scope.environmentId, "prod");
      assert.equal(refresh.scope.appId, "checkout");
      assert.equal(refresh.bindings.current, 1);
      const page = await authenticatedApi.readRuleCatalog(query, new AbortController().signal);
      assert.equal(page.query.environmentId, "prod");
      assert.equal(page.query.appId, "checkout");
      assert.equal(page.coverage, "complete");
      assert.equal(page.total, 1);
      assert.equal(page.items[0].record.rule.value.resource, "POST /checkout");
      assert.equal(page.items[0].record.rule.value.count, 17);
      assert.equal(page.items[0].binding.sourceLabel, "Integration Nacos");
      assert.equal(page.items[0].snapshot.checksum, "integration-checksum-17");
      assert.equal(page.items[0].snapshot.sourceRevision, "integration-revision-17");
      assert.equal(page.items[0].read.freshness, "current");

      const anonymousApi = createRuleSetHttp(anonymousTransport);
      await assert.rejects(
        anonymousApi.readRuleCatalog(query, new AbortController().signal),
        (error) => error.status === 401 && error.code === "unauthenticated",
      );
    } catch (error) {
      if (consoleOutput()) error.message += `\nPython Console output:\n${consoleOutput()}`;
      throw error;
    } finally {
      authenticatedTransport?.dispose();
      anonymousTransport?.dispose();
      await vite?.close();
      if (consoleProcess) await stopConsole(consoleProcess);
    }
  },
);
