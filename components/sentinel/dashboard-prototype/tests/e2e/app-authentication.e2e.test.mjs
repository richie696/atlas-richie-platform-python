import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { E2E_BASE_URL, connectIabBrowser } from "./cdp.mjs";

let browser;

before(async () => {
  browser = await connectIabBrowser();
});

after(async () => {
  await browser?.close();
});

test("App identity: server-confirmed login gates routes and view cannot enter management", async () => {
  const page = await browser.newPage();
  try {
    const origin = new URL(E2E_BASE_URL).origin;
    await page.clearStorage(origin);
    await page.goto(`${E2E_BASE_URL}/#/login`);
    await page.eval(
      `localStorage.setItem("sentinel.mock.role", "anonymous"); location.hash = "#/login"; location.reload();`,
    );
    await page.waitFor(
      `!!document.querySelector('.login-page form input[autocomplete="username"]')`,
    );

    await page.eval(`(() => {
      const originalReplaceState = history.replaceState.bind(history);
      window.__overviewReplaceCount = 0;
      history.replaceState = (state, title, url) => {
        if (typeof url === 'string' && new URL(url, location.href).hash.startsWith('#/overview'))
          window.__overviewReplaceCount++;
        return originalReplaceState(state, title, url);
      };
    })()`);

    await page.type('.login-page input[autocomplete="username"]', "viewer");
    await page.type('.login-page input[autocomplete="current-password"]', "synthetic-password");
    await page.clickByText("登录", ".login-page button");
    await page.waitFor(
      `location.hash.includes("overview") && !!document.querySelector(".app-shell")`,
    );

    assert.equal(await page.eval(`window.__overviewReplaceCount`), 1, "login confirmation navigates once");
    assert.equal(await page.eval(`localStorage.getItem("sentinel.mock.role")`), "view");
    assert.equal(await page.eval(`location.hash.includes("accounts")`), false);
    await page.eval(`location.hash = "#/accounts"`);
    await page.waitFor(`document.body.textContent.includes("只有当前管理员可以管理账号和角色")`);
    assert.equal(await page.eval(`location.hash.includes("accounts")`), true);
    assert.equal(await page.count("[data-account-management] table"), 0);
    assert.deepEqual(page.consoleErrors, []);
  } finally {
    await page.close();
  }
});

test("App login: rejected credentials preserve the username and use a non-enumerating error", async () => {
  const page = await browser.newPage();
  try {
    const origin = new URL(E2E_BASE_URL).origin;
    await page.clearStorage(origin);
    await page.goto(`${E2E_BASE_URL}/#/login`);
    await page.eval(
      `localStorage.setItem("sentinel.mock.role", "anonymous"); location.hash = "#/login"; location.reload();`,
    );
    await page.waitFor(
      `!!document.querySelector('.login-page form input[autocomplete="username"]')`,
    );

    await page.type('.login-page input[autocomplete="username"]', "unknown-operator");
    await page.type('.login-page input[autocomplete="current-password"]', "incorrect-password");
    await page.clickByText("登录", ".login-page button");
    await page.waitFor(`!!document.querySelector('.login-page [role="alert"]')`);

    assert.equal(
      await page.eval(`document.querySelector('.login-page input[autocomplete="username"]').value`),
      "unknown-operator",
    );
    assert.doesNotMatch(
      await page.text('.login-page [role="alert"]'),
      /unknown-operator|user does not exist|account not found/i,
    );
    assert.deepEqual(page.consoleErrors, []);
  } finally {
    await page.close();
  }
});

test("App identity: admin account management survives React StrictMode and restores its mock directory", async () => {
  const page = await browser.newPage();
  try {
    const origin = new URL(E2E_BASE_URL).origin;
    await page.clearStorage(origin);
    await page.goto(`${E2E_BASE_URL}/#/login`);
    await page.eval(
      `localStorage.setItem("sentinel.mock.role", "anonymous"); location.hash = "#/login"; location.reload();`,
    );
    await page.waitFor(
      `!!document.querySelector('.login-page form input[autocomplete="username"]')`,
    );

    await page.type('.login-page input[autocomplete="username"]', "admin");
    await page.type('.login-page input[autocomplete="current-password"]', "synthetic-password");
    await page.clickByText("登录", ".login-page button");
    await page.waitFor(
      `location.hash.includes("overview") && !!document.querySelector(".app-shell")`,
    );

    await page.eval(`location.hash = "#/accounts"`);
    await page.waitFor(`!!document.querySelector('[data-account-management] tr[data-account-id]')`);
    assert.match(await page.text("[data-account-management]"), /admin[\s\S]*viewer/);

    await page.clickByText("新增账号", "[data-account-management] button");
    await page.waitFor(`!!document.querySelector('dialog[open]')`);
    assert.equal(await page.count("dialog[open] input"), 2);
    assert.doesNotMatch(await page.text("dialog[open]"), /确认密码|显示名称/);
    assert.deepEqual(page.consoleErrors, []);
  } finally {
    await page.close();
  }
});

test("App route owner: changing authenticated session on the same route hides old data and cancels reads", async () => {
  const page = await browser.newPage();
  try {
    const origin = new URL(E2E_BASE_URL).origin;
    await page.clearStorage(origin);
    await page.goto(`${E2E_BASE_URL}/#/login`);
    await page.eval(
      `localStorage.setItem("sentinel.mock.role", "anonymous"); location.hash = "#/login"; location.reload();`,
    );
    await page.waitFor(
      `!!document.querySelector('.login-page form input[autocomplete="username"]')`,
    );
    await page.eval(`(async () => {
      const React = (await import('/node_modules/.vite/deps/react.js')).default;
      const { createRoot } = (await import('/node_modules/.vite/deps/react-dom_client.js')).default;
      const { RouteBoundary } = await import('/src/app/router/RouteBoundary.tsx');
      const { routePageOwnerKey } = await import('/src/app/router/routeOwner.ts');
      const { QueryLifecycleProbe, createQueryResource } = await import('/tests/e2e/probes/QueryLifecycleProbe.tsx');
      const reads = [], commits = [], resource = createQueryResource({
        keyOf: query => JSON.stringify([query.session, query.application]),
        classify: () => 'ready',
        read: (query, signal) => new Promise(resolve => reads.push({ query, signal, resolve })),
      });
      const container = document.createElement('section'); container.id = 'f2-session-route-probe'; document.body.append(container);
      const root = createRoot(container), loader = async () => ({ default: QueryLifecycleProbe });
      const onCommit = (query, snapshot) => commits.push({ query, data: 'data' in snapshot ? snapshot.data : null });
      const render = query => root.render(React.createElement(React.StrictMode, {}, React.createElement(RouteBoundary, {
        loader,
        resetKey: routePageOwnerKey('realtime', query.session),
        pageProps: { resource, query, onCommit },
        onHome: () => {},
      })));
      window.__f2SessionRoute = { reads, commits, resource, render, clean: () => { root.unmount(); container.remove(); } };
      render({ session: 'server-session-one', application: 'orders' });
    })()`);
    await page.waitFor(
      `window.__f2SessionRoute.reads.length === 2 && window.__f2SessionRoute.reads[0].signal.aborted`,
    );
    await page.eval(`window.__f2SessionRoute.reads[1].resolve(['private-session-one'])`);
    await page.waitFor(
      `document.querySelector('#f2-session-route-probe output')?.textContent === '{"status":"ready","data":["private-session-one"]}'`,
    );
    await page.eval(
      `window.__f2SessionRoute.render({ session: 'server-session-two', application: 'orders' })`,
    );
    await page.waitFor(
      `window.__f2SessionRoute.reads.length === 4 && window.__f2SessionRoute.reads[2].signal.aborted`,
    );
    assert.equal(
      await page.text("#f2-session-route-probe output"),
      '{"status":"loading","data":null}',
      "the new session must not render the prior session snapshot while its request is pending",
    );
    assert.ok(await page.eval(`window.__f2SessionRoute.reads[1].signal.aborted`));
    await page.eval(
      `window.__f2SessionRoute.reads[0].resolve(['late-old-session']); window.__f2SessionRoute.reads[3].resolve(['private-session-two'])`,
    );
    await page.waitFor(
      `document.querySelector('#f2-session-route-probe output')?.textContent === '{"status":"ready","data":["private-session-two"]}'`,
    );
    assert.ok(
      await page.eval(
        `window.__f2SessionRoute.commits.filter(item => item.query.session === 'server-session-two').every(item => item.data === null || !item.data.includes('private-session-one'))`,
      ),
    );
    await page.eval(`window.__f2SessionRoute.clean()`);
    assert.deepEqual(page.consoleErrors, []);
  } finally {
    await page.close();
  }
});
