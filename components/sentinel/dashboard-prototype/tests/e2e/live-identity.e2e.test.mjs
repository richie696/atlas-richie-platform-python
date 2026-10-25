import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { randomBytes, randomUUID } from "node:crypto";
import { E2E_BASE_URL, connectE2EBrowser } from "./cdp.mjs";

const enabled = process.env.SENTINEL_E2E_LIVE_ACCOUNT_AUTH === "1";
const adminPassword = process.env.SENTINEL_LIVE_E2E_PASSWORD;
const consoleOrigin = process.env.SENTINEL_E2E_CONSOLE_ORIGIN;
let browser;

before(async () => {
  if (enabled) browser = await connectE2EBrowser();
});

after(async () => {
  await browser?.close();
});

async function login(page, username, password) {
  const origin = new URL(E2E_BASE_URL).origin;
  await page.goto(`${origin}/#/login`);
  await page.waitFor(`!!document.querySelector('.login-page input[autocomplete="username"]')`);
  await page.type('.login-page input[autocomplete="username"]', username);
  await page.type('.login-page input[autocomplete="current-password"]', password);
  await page.clickByText("登录", ".login-page form button");
  await page.waitFor(
    `location.hash.startsWith('#/overview') && !!document.querySelector('.app-shell')`,
    { timeoutMs: 15000, label: `Console confirms ${username} session` },
  );
}

async function readAccounts(page, search) {
  return page.eval(`(async()=>{
    const requestId=crypto.randomUUID();
    const url=new URL('/api/v1/accounts',location.origin);
    url.searchParams.set('page','1');url.searchParams.set('pageSize','20');url.searchParams.set('search',${JSON.stringify(search)});
    const response=await fetch(url,{headers:{'x-request-id':requestId},cache:'no-store'});
    return {status:response.status,requestId:response.headers.get('x-request-id'),body:await response.json()};
  })()`);
}

async function setAccountStatus(page, accountId, desiredStatus) {
  await page.goto(`${new URL(E2E_BASE_URL).origin}/#/accounts`);
  const row = `tr[data-account-id="${accountId}"]`;
  await page.waitFor(`!!document.querySelector(${JSON.stringify(row)})`, {
    timeoutMs: 15000,
    label: "synthetic account row is read from the Console",
  });
  const alreadyDesired = await page.eval(
    `(()=>{const text=document.querySelector(${JSON.stringify(row)})?.textContent??"";return ${JSON.stringify(desiredStatus)}==="disabled"?text.includes("已停用"):text.includes("启用")&&!text.includes("已停用");})()`,
  );
  if (alreadyDesired) return;
  await page.click(`${row} button`, { index: 1 });
  await page.waitFor(`!!document.querySelector('dialog[open]')`);
  await page.clickByText("确认变更", "dialog button");
  await page.waitFor(`!document.querySelector('dialog[open]')`);
  const statusText = desiredStatus === "disabled" ? "已停用" : "启用";
  await page.waitFor(
    `document.querySelector(${JSON.stringify(row)})?.textContent.includes(${JSON.stringify(statusText)})`,
    { timeoutMs: 15000, label: `Console confirms account is ${statusText}` },
  );
}

async function readOldSession(cookieHeader) {
  assert.ok(consoleOrigin, "SENTINEL_E2E_CONSOLE_ORIGIN is required");
  const requestId = randomUUID();
  const response = await fetch(`${consoleOrigin}/api/v1/auth/me`, {
    headers: { cookie: cookieHeader, "x-request-id": requestId },
    cache: "no-store",
  });
  return {
    status: response.status,
    requestId: response.headers.get("x-request-id"),
    body: await response.json(),
  };
}

test(
  "LIVE identity: viewer can read, cannot manage, and account re-enable never revives its revoked session",
  { skip: !enabled || !adminPassword || !consoleOrigin },
  async () => {
    const origin = new URL(E2E_BASE_URL).origin;
    const suffix = randomUUID().replaceAll("-", "").slice(0, 16);
    const username = `e2e_view_${suffix}`;
    const deniedUsername = `e2e_denied_${suffix}`;
    const password = `T07-${randomBytes(24).toString("base64url")}-9a`;
    const deniedPassword = `T07-${randomBytes(24).toString("base64url")}-8b`;
    const page = await browser.newPage();
    let accountId = null;
    let viewerCookieHeader = null;
    try {
      await page.clearStorage(origin);
      await login(page, "admin", adminPassword);
      const admin = await page.eval(`(async()=>{
        const response=await fetch('/api/v1/auth/me',{headers:{'x-request-id':crypto.randomUUID()},cache:'no-store'});
        return {status:response.status,body:await response.json()};
      })()`);
      assert.equal(admin.status, 200);
      assert.equal(admin.body?.roleId, "admin");

      await page.goto(`${origin}/#/accounts`);
      await page.waitFor(`!!document.querySelector('[data-account-management]')`);
      await page.clickByText("新增账号");
      await page.waitFor(`!!document.querySelector('dialog[open]')`);
      await page.type('dialog input[autocomplete="username"]', username);
      await page.type('dialog input[autocomplete="new-password"]', password);
      await page.clickByText("创建账号", "dialog button");
      await page.waitFor(`!document.querySelector('dialog[open]')`);
      await page.waitFor(`document.body.innerText.includes(${JSON.stringify(username)})`);

      const created = await readAccounts(page, username);
      assert.equal(created.status, 200);
      assert.equal(created.requestId?.length > 0, true);
      assert.equal(created.body.total, 1);
      assert.equal(created.body.items[0].username, username);
      assert.equal(created.body.items[0].roleId, "view");
      assert.equal(created.body.items[0].status, "active");
      accountId = created.body.items[0].id;
      assert.equal(Object.hasOwn(created.body.items[0], "password"), false);
      assert.equal(JSON.stringify(created.body).includes(password), false);
      const browserState = await page.eval(
        `JSON.stringify({url:location.href,local:{...localStorage},session:{...sessionStorage},body:document.body.innerText})`,
      );
      assert.equal(browserState.includes(password), false);

      await page.click('button[aria-label="打开 admin 的会话菜单"]');
      await page.clickByText("退出登录", '[role="group"] button');
      await page.waitFor(`!!document.querySelector('.login-page input[autocomplete="username"]')`);
      await login(page, username, password);
      const identity = await page.eval(`(async()=>{
        const response=await fetch('/api/v1/auth/me',{headers:{'x-request-id':crypto.randomUUID()},cache:'no-store'});
        return {status:response.status,body:await response.json()};
      })()`);
      assert.equal(identity.status, 200);
      assert.equal(identity.body?.username, username);
      assert.equal(identity.body?.roleId, "view");
      assert.equal(identity.body?.capabilities.includes("metrics:view"), true);
      assert.equal(identity.body?.capabilities.includes("rules:write"), false);

      await page.goto(`${origin}/#/applications`);
      await page.waitFor(`!!document.querySelector('.app-shell .intro h1')`);
      assert.equal(await page.count('[data-route-state="failed"]'), 0);
      assert.equal(await page.count('[data-route-state="access-denied"]'), 0);

      const cookies = await page.send("Network.getCookies", { urls: [origin] });
      const sessionCookie = cookies.cookies.find((cookie) => cookie.name === "sentinel_session");
      const csrfCookie = cookies.cookies.find((cookie) => cookie.name === "__Host-sentinel_csrf");
      assert.ok(sessionCookie?.value);
      assert.ok(csrfCookie?.value);
      viewerCookieHeader = `sentinel_session=${sessionCookie.value}; __Host-sentinel_csrf=${csrfCookie.value}`;

      const deniedList = await page.eval(`(async()=>{
        const response=await fetch('/api/v1/accounts?page=1&pageSize=20&search=',{headers:{'x-request-id':crypto.randomUUID()},cache:'no-store'});
        return {status:response.status,body:await response.json()};
      })()`);
      assert.equal(deniedList.status, 403);
      assert.equal(deniedList.body.error.code, "forbidden");
      const deniedWrite = await page.eval(`(async()=>{
        const requestKey=${JSON.stringify(`view-denied-${suffix}`)};
        const requestId=crypto.randomUUID();
        const response=await fetch('/api/v1/accounts/commands',{method:'POST',headers:{'content-type':'application/json','x-request-id':requestId,'idempotency-key':requestKey,'x-sentinel-csrf':${JSON.stringify(csrfCookie.value)}},body:JSON.stringify({kind:'create',requestKey,input:{username:${JSON.stringify(deniedUsername)},password:${JSON.stringify(deniedPassword)},roleId:'view'}})});
        return {status:response.status,requestId:response.headers.get('x-request-id'),body:await response.json()};
      })()`);
      assert.equal(deniedWrite.status, 403);
      assert.equal(deniedWrite.body.error.code, "forbidden");
      assert.equal(deniedWrite.requestId?.length > 0, true);
      assert.equal(JSON.stringify(deniedWrite.body).includes(deniedPassword), false);

      await page.click(`button[aria-label="打开 ${username} 的会话菜单"]`);
      await page.clickByText("退出登录", '[role="group"] button');
      await page.waitFor(`!!document.querySelector('.login-page input[autocomplete="username"]')`);
      await login(page, "admin", adminPassword);
      const deniedAccount = await readAccounts(page, deniedUsername);
      assert.equal(deniedAccount.status, 200);
      assert.equal(deniedAccount.body.total, 0);

      await setAccountStatus(page, accountId, "disabled");
      const revoked = await readOldSession(viewerCookieHeader);
      assert.equal(revoked.status, 200);
      assert.equal(revoked.body, null);

      await setAccountStatus(page, accountId, "active");
      const stillRevoked = await readOldSession(viewerCookieHeader);
      assert.equal(stillRevoked.status, 200);
      assert.equal(stillRevoked.body, null);

      await setAccountStatus(page, accountId, "disabled");
      const finalRecord = await readAccounts(page, username);
      assert.equal(finalRecord.status, 200);
      assert.equal(finalRecord.body.total, 1);
      assert.equal(finalRecord.body.items[0].status, "disabled");
      assert.deepEqual(page.consoleErrors, []);
      console.log(`live_account_request_id=${created.requestId}`);
      console.log(`live_viewer_denied_command_request_id=${deniedWrite.requestId}`);
    } finally {
      if (accountId !== null) {
        try {
          await page.clearStorage(origin);
          await login(page, "admin", adminPassword);
          await setAccountStatus(page, accountId, "disabled");
        } catch (error) {
          console.error(`synthetic account cleanup needs review: ${error instanceof Error ? error.message : "unknown failure"}`);
        }
      }
      await page.close();
    }
  },
);
