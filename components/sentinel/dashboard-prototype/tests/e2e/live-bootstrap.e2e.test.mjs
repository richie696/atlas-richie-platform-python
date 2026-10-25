import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { E2E_BASE_URL, connectIabBrowser } from "./cdp.mjs";

const liveEnabled = process.env.SENTINEL_E2E_LIVE === "1";
const liveSourceAcceptanceEnabled = liveEnabled && process.env.SENTINEL_E2E_LIVE_SOURCE === "1";
const liveMySqlConsulEnabled =
  liveSourceAcceptanceEnabled && process.env.SENTINEL_E2E_LIVE_MYSQL_CONSUL === "1";
const liveInitializedSmokeEnabled =
  liveEnabled && process.env.SENTINEL_E2E_LIVE_BOOTSTRAP_INITIALIZED === "1";
const liveAuthenticatedEnabled = liveEnabled && process.env.SENTINEL_E2E_LIVE_AUTHENTICATED === "1";
const liveUsername = process.env.SENTINEL_LIVE_E2E_USERNAME;
const livePassword = process.env.SENTINEL_LIVE_E2E_PASSWORD;
const focusedRustProvisioning = process.env.SENTINEL_T07_FOCUSED_RUST_ACCEPTANCE === "1";
let browser;

before(async () => {
  if (liveEnabled) browser = await connectIabBrowser();
});

after(async () => {
  await browser?.close();
});

test(
  "LIVE bootstrap: initialized Console keeps the one-time setup window closed",
  { skip: !liveInitializedSmokeEnabled },
  async () => {
    const page = await browser.newPage();
    try {
      const origin = new URL(E2E_BASE_URL).origin;
      await page.clearStorage(origin);
      const trace = process.env.SENTINEL_E2E_TRACE_SETUP === "1";
      if (trace) console.log("live_setup_navigation_start");
      await page.goto(`${origin}/#/setup`);
      if (trace) console.log("live_setup_navigation_complete");
      await page.waitFor(
        `location.hash.startsWith('#/login') && !!document.querySelector('.login-page form input[autocomplete="username"]')`,
        { label: "real initialized bootstrap redirects direct setup access to login" },
      );
      assert.equal(await page.count(".setup-page form"), 0);
      assert.equal(await page.count(".login-demo-notice"), 0);
      assert.doesNotMatch(await page.text(".login-page"), /本地演示模式|Local demo mode/);

      const bootstrap = await page.eval(`(async () => {
        const response = await fetch('/api/v1/system/bootstrap', {
          headers: { 'x-request-id': crypto.randomUUID() },
          cache: 'no-store',
        });
        return { status: response.status, body: await response.json() };
      })()`);
      assert.equal(bootstrap.status, 200);
      assert.deepEqual(bootstrap.body, { initialized: true });
      assert.deepEqual(page.consoleErrors, []);
    } finally {
      await page.close();
    }
  },
);

test(
  "LIVE authenticated read journey: confirmed administrator can read each installed page",
  { skip: !liveAuthenticatedEnabled || !liveUsername || !livePassword },
  async () => {
    const page = await browser.newPage();
    try {
      const origin = new URL(E2E_BASE_URL).origin;
      await page.clearStorage(origin);
      await page.goto(`${origin}/#/login?app=all&range=1h`);
      await page.waitFor(
        `!!document.querySelector('.login-page form input[autocomplete="username"]')`,
      );
      await page.type('.login-page form input[autocomplete="username"]', liveUsername);
      await page.type('.login-page form input[autocomplete="current-password"]', livePassword);
      await page.clickByText("登录", ".login-page form button");
      await page.waitFor(
        `location.hash.startsWith('#/overview') && !!document.querySelector('.app-shell')`,
        { label: "live server confirms administrator session" },
      );

      for (const route of [
        "overview?app=all&range=1h",
        "applications?app=all&range=1h",
        "rules?app=all&range=1h",
        "realtime?app=all&range=1h",
        "faults?app=all&range=1h",
        "system?view=connections",
        "accounts",
        "roles",
        "change-password",
      ]) {
        await page.goto(`${origin}/#/${route}`);
        await page.waitFor(
          `location.hash.startsWith(${JSON.stringify(`#/${route.split(/[?]/)[0]}`)}) && !!document.querySelector('.app-shell .intro h1')`,
          { label: `live page ${route.split(/[?]/)[0]} renders its page heading` },
        );
        assert.equal(await page.count('[data-route-state="failed"]'), 0, route);
        assert.equal(await page.count('[data-route-state="access-denied"]'), 0, route);
      }
      assert.deepEqual(page.consoleErrors, []);
    } finally {
      await page.close();
    }
  },
);

test(
  "LIVE source acceptance: SQLite setup creates admin, authenticates, and reads every page",
  { skip: !liveSourceAcceptanceEnabled || !livePassword },
  async () => {
    const page = await browser.newPage();
    try {
      const origin = new URL(E2E_BASE_URL).origin;
      await page.clearStorage(origin);
      await page.goto(`${origin}/#/setup`);
      await page.waitFor(
        `!!document.querySelector('.setup-page') && !!document.querySelector('.setup-workspace')`,
        { label: "fresh Console renders the first-run setup wizard" },
      );

      await page.clickByText("SQLite", ".astryx-radio-list-item");
      await page.clickByText("下一步", ".setup-actions button");
      await page.waitFor(
        `document.querySelector('.setup-workspace').textContent.includes('创建内置管理员')`,
      );

      const setField = async (label, value) => {
        const trace = process.env.SENTINEL_E2E_TRACE_SETUP === "1";
        if (trace) console.log(`live_setup_field_start=${label}`);
        const id = await page.eval(
          `(()=>{const fieldLabel=[...document.querySelectorAll('.setup-workspace label')].find(node=>node.textContent.trim()===${JSON.stringify(label)});return fieldLabel?.htmlFor??null;})()`,
        );
        assert.ok(id, `setup field label exists: ${label}`);
        await page.type(
          `#${id.replace(/[^a-zA-Z0-9_-]/g, (character) => `\\${character}`)}`,
          value,
        );
        await page.waitFor(
          `document.getElementById(${JSON.stringify(id)}).value===${JSON.stringify(value)}`,
          { label: `${label} accepts input` },
        );
      };

      await setField("管理员密码", livePassword);
      await setField("确认管理员密码", livePassword);
      await page.clickByText("下一步", ".setup-actions button");
      await page.waitFor(`!!document.querySelector('.setup-authentication')`);

      await page.clickByText("不启用认证", ".setup-authentication .astryx-radio-list-item");
      await setField("服务地址", "http://localhost:8848");
      await page.clickByText("下一步", ".setup-actions button");
      await page.waitFor(`!!document.querySelector('.setup-summary')`);
      await page.clickByText("完成初始化", ".setup-actions button");
      await page.waitFor(
        `location.hash.startsWith('#/login') && !!document.querySelector('.login-page form input[autocomplete="username"]')`,
        { timeoutMs: 30000, label: "fresh SQLite initialization completes and returns to login" },
      );

      const bootstrap = await page.eval(`(async () => {
        const response = await fetch('/api/v1/system/bootstrap', {
          headers: { 'x-request-id': crypto.randomUUID() },
          cache: 'no-store',
        });
        return { status: response.status, body: await response.json() };
      })()`);
      assert.equal(bootstrap.status, 200);
      assert.deepEqual(bootstrap.body, { initialized: true });

      await page.type('.login-page form input[autocomplete="username"]', "admin");
      await page.type('.login-page form input[autocomplete="current-password"]', livePassword);
      await page.clickByText("登录", ".login-page form button");
      await page.waitFor(
        `location.hash.startsWith('#/overview') && !!document.querySelector('.app-shell')`,
        { timeoutMs: 15000, label: "fresh administrator login is confirmed by the Console" },
      );

      for (const route of [
        "overview?app=all&range=1h",
        "applications?app=all&range=1h",
        "rules?app=all&range=1h",
        "realtime?app=all&range=1h",
        "faults?app=all&range=1h",
        "system?view=connections",
        "accounts",
        "roles",
        "change-password",
      ]) {
        await page.goto(`${origin}/#/${route}`);
        await page.waitFor(
          `location.hash.startsWith(${JSON.stringify(`#/${route.split(/[?]/)[0]}`)}) && !!document.querySelector('.app-shell .intro h1')`,
          { label: `fresh source-run page ${route.split(/[?]/)[0]} renders its heading` },
        );
        assert.equal(await page.count('[data-route-state="failed"]'), 0, route);
        assert.equal(await page.count('[data-route-state="access-denied"]'), 0, route);
      }

      const persisted = await page.eval(
        `JSON.stringify({url:location.href,local:{...localStorage},session:{...sessionStorage}})`,
      );
      assert.equal(persisted.includes(livePassword), false);
      assert.deepEqual(page.consoleErrors, []);
    } finally {
      await page.close();
    }
  },
);

test(
  focusedRustProvisioning
    ? "LIVE T07.1 prerequisite provisioning: fresh MySQL+Consul setup and first admin login"
    : "LIVE fresh MySQL+Consul: setup, first admin login, and installed page reads",
  { skip: !liveMySqlConsulEnabled || !livePassword },
  async () => {
    const required = [
      "SENTINEL_E2E_MYSQL_HOST",
      "SENTINEL_E2E_MYSQL_PORT",
      "SENTINEL_E2E_MYSQL_DATABASE",
      "SENTINEL_E2E_MYSQL_USER",
      "SENTINEL_E2E_MYSQL_PASSWORD",
      "SENTINEL_E2E_CONSUL_URL",
    ];
    for (const name of required) assert.ok(process.env[name], `${name} is required`);

    const trace = process.env.SENTINEL_E2E_TRACE_SETUP === "1";
    const page = await browser.newPage();
    try {
      const origin = new URL(E2E_BASE_URL).origin;
      await page.clearStorage(origin);
      await page.send("Page.addScriptToEvaluateOnNewDocument", {
        source: `(() => {
          const originalFetch = window.fetch.bind(window);
          window.__setupE2eApiObservations = [];
          window.fetch = async (...args) => {
            const response = await originalFetch(...args);
            const rawUrl = args[0] instanceof Request ? args[0].url : String(args[0]);
            if (rawUrl.includes("/api/v1/system/bootstrap/")) {
              const body = await response.clone().json().catch(() => null);
              window.__setupE2eApiObservations.push({
                path: new URL(rawUrl, location.href).pathname,
                method: args[1]?.method ?? (args[0] instanceof Request ? args[0].method : "GET"),
                status: response.status,
                requestId: response.headers.get("x-request-id"),
                code: body?.error?.code ?? null,
                result: body?.status ?? null,
                requestKey: body?.requestKey ?? null,
                operationId: body?.operationId ?? null,
                reason: body?.reason ?? null,
              });
            }
            return response;
          };
        })();`,
      });
      await page.goto(`${origin}/#/setup`);
      await page.waitFor(
        `!!document.querySelector('.setup-page') && !!document.querySelector('.setup-workspace')`,
        { label: "fresh MySQL+Consul Console renders the forced first-run wizard" },
      );
      if (trace) console.log("live_setup_wizard_confirmed");

      const setField = async (label, value) => {
        const trace = process.env.SENTINEL_E2E_TRACE_SETUP === "1";
        if (trace) console.log(`live_setup_field_start=${label}`);
        const id = await page.eval(
          `(()=>{const fieldLabel=[...document.querySelectorAll('.setup-workspace label')].find(node=>node.textContent.trim()===${JSON.stringify(label)});return fieldLabel?.htmlFor??null;})()`,
        );
        assert.ok(id, `setup field label exists: ${label}`);
        await page.click(`#${id.replace(/[^a-zA-Z0-9_-]/g, (character) => `\\${character}`)}`);
        await page.eval(`document.activeElement.select()`);
        await page.send("Input.insertText", { text: value });
        await page.waitFor(
          `document.getElementById(${JSON.stringify(id)}).value===${JSON.stringify(value)}`,
          { label: `${label} accepts the test value` },
        );
        if (trace) console.log(`live_setup_field_complete=${label}`);
      };

      if (trace) console.log("live_setup_select_mysql_start");
      await page.clickByText("MySQL", ".astryx-radio-list-item");
      if (trace) console.log("live_setup_select_mysql_complete");
      await setField("主机", process.env.SENTINEL_E2E_MYSQL_HOST);
      await setField("端口", process.env.SENTINEL_E2E_MYSQL_PORT);
      await setField("数据库名", process.env.SENTINEL_E2E_MYSQL_DATABASE);
      await setField("用户名", process.env.SENTINEL_E2E_MYSQL_USER);
      await setField("密码", process.env.SENTINEL_E2E_MYSQL_PASSWORD);
      await page.clickByText("测试数据库连接", ".setup-workspace button");
      if (process.env.SENTINEL_E2E_TRACE_SETUP === "1")
        console.log("live_setup_database_check_submitted");
      try {
        await page.waitFor(`document.body.textContent.includes('连接可达')`, {
          timeoutMs: 30000,
          label: "real MySQL TLS connection check is reachable",
        });
      } catch (error) {
        const observations = await page.eval("window.__setupE2eApiObservations ?? []");
        throw new Error(
          `${error instanceof Error ? error.message : String(error)}; database-check API observations=${JSON.stringify(observations)}; setup body=${JSON.stringify((await page.text(".setup-workspace")).slice(0, 1800))}`,
        );
      }
      if (process.env.SENTINEL_E2E_TRACE_SETUP === "1")
        console.log("live_setup_database_check_confirmed");
      await page.clickByText("下一步", ".setup-actions button");
      if (process.env.SENTINEL_E2E_TRACE_SETUP === "1")
        console.log("live_setup_admin_step_requested");
      await page.waitFor(
        `document.querySelector('.setup-workspace').textContent.includes('创建内置管理员')`,
      );

      await setField("管理员密码", livePassword);
      await setField("确认管理员密码", livePassword);
      await page.clickByText("下一步", ".setup-actions button");
      await page.waitFor(`!!document.querySelector('.setup-authentication')`);

      await page.clickByText("Consul", ".astryx-radio-list-item");
      await setField("服务地址", process.env.SENTINEL_E2E_CONSUL_URL);
      await setField("命名空间 / 数据中心", "dc1");
      await page.clickByText("不启用认证", ".setup-authentication .astryx-radio-list-item");
      await page.clickByText("测试规则源连接", ".setup-workspace button");
      try {
        await page.waitFor(
          `[...document.querySelectorAll('[aria-busy]')].some(node => node.querySelector('h2')?.textContent.trim() === '规则来源' && node.textContent.includes('连接可达'))`,
          {
            timeoutMs: 30000,
            label: "the Consul-specific feedback confirms the real source check is reachable",
          },
        );
      } catch (error) {
        const observations = await page.eval("window.__setupE2eApiObservations ?? []");
        throw new Error(
          `${error instanceof Error ? error.message : String(error)}; bootstrap API observations=${JSON.stringify(observations)}`,
        );
      }
      await page.clickByText("下一步", ".setup-actions button");
      await page.waitFor(`!!document.querySelector('.setup-summary')`);
      assert.doesNotMatch(await page.text(".setup-summary"), /password|密码|凭证|SENTINEL_E2E/i);
      await page.clickByText("完成初始化", ".setup-actions button");
      const loginConfirmed = () =>
        page.waitFor(
          `location.hash.startsWith('#/login') && !!document.querySelector('.login-page form input[autocomplete="username"]')`,
          {
            timeoutMs: 20_000,
            label: "MySQL+Consul first-run initialization closes setup and returns to login",
          },
        );
      let initialized = false;
      for (let attempt = 0; attempt < 8 && !initialized; attempt += 1) {
        try {
          await loginConfirmed();
          initialized = true;
        } catch {
          const inspectAvailable = await page.eval(
            `document.body.innerText.includes("检查执行结果")`,
          );
          if (!inspectAvailable) continue;
          // Initialization is a non-repeatable command. If its HTTP response
          // outlives the browser timeout, reconcile the original request via
          // the read-only operation receipt instead of submitting it again.
          await page.clickByText("检查执行结果", "button");
        }
      }
      if (!initialized) {
        const observations = await page.eval("window.__setupE2eApiObservations ?? []");
        throw new Error(
          `MySQL+Consul initialization did not reach the confirmed login route; bootstrap API observations=${JSON.stringify(observations)}; url=${await page.eval("location.href")}; setup body=${JSON.stringify((await page.text(".setup-workspace")).slice(0, 2200))}; consoleErrors=${JSON.stringify(page.consoleErrors)}`,
        );
      }

      const bootstrapRequestId = await page.eval("crypto.randomUUID()");
      const bootstrap = await page.eval(`(async () => {
        const requestId = ${JSON.stringify(bootstrapRequestId)};
        const response = await fetch('/api/v1/system/bootstrap', {
          headers: { 'x-request-id': requestId },
          cache: 'no-store',
        });
        return { status: response.status, requestId: response.headers.get('x-request-id'), body: await response.json() };
      })()`);
      assert.equal(bootstrap.status, 200);
      assert.equal(bootstrap.requestId, bootstrapRequestId);
      assert.deepEqual(bootstrap.body, { initialized: true });
      console.log(`live_setup_bootstrap_request_id=${bootstrapRequestId}`);

      await page.type('.login-page form input[autocomplete="username"]', "admin");
      await page.type('.login-page form input[autocomplete="current-password"]', livePassword);
      await page.clickByText("登录", ".login-page form button");
      await page.waitFor(
        `location.hash.startsWith('#/overview') && !!document.querySelector('.app-shell')`,
        { timeoutMs: 15000, label: "new MySQL-backed administrator session is server-confirmed" },
      );

      if (!focusedRustProvisioning) {
        for (const route of [
          "overview?app=all&range=1h",
          "applications?app=all&range=1h",
          "rules?app=all&range=1h",
          "realtime?app=all&range=1h",
          "faults?app=all&range=1h",
          "system?view=connections",
          "accounts",
          "roles",
          "change-password",
        ]) {
          await page.goto(`${origin}/#/${route}`);
          await page
            .waitFor(
              `location.hash.startsWith(${JSON.stringify(`#/${route.split(/[?]/)[0]}`)}) && !!document.querySelector('.app-shell .intro h1')`,
              { label: `fresh MySQL+Consul page ${route.split(/[?]/)[0]} renders its page heading` },
            )
            .catch(async (error) => {
              throw new Error(
                `${error.message}\nurl=${await page.eval("location.href")}\nbody=${(await page.text("body")).slice(0, 2400)}\nconsoleErrors=${JSON.stringify(page.consoleErrors)}`,
              );
            });
          assert.equal(await page.count('[data-route-state="failed"]'), 0, route);
          assert.equal(await page.count('[data-route-state="access-denied"]'), 0, route);
        }
      }

      const persistedClientState = await page.eval(
        `JSON.stringify({url:location.href,local:{...localStorage},session:{...sessionStorage}})`,
      );
      assert.equal(persistedClientState.includes(livePassword), false);
      assert.equal(persistedClientState.includes(process.env.SENTINEL_E2E_MYSQL_PASSWORD), false);
      assert.deepEqual(page.consoleErrors, []);
    } finally {
      await page.close();
    }
  },
);
