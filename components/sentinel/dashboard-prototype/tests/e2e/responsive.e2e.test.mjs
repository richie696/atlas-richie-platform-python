import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { E2E_BASE_URL, connectIabBrowser } from "./cdp.mjs";
import { gotoMockAdministrator } from "./mock-auth.mjs";

let browser;
before(async () => {
  browser = await connectIabBrowser();
});
after(async () => {
  await browser?.close();
});
const ROUTES = [
  "overview",
  "applications?app=app-one",
  "rules?env=test-env&app=app-one&binding=binding-app-one",
  "realtime",
  "faults",
  "system",
  "setup",
  "login",
  "accounts",
  "roles",
  "change-password",
];
async function withPage(run) {
  const page = await browser.newPage();
  try {
    await page.clearStorage(new URL(E2E_BASE_URL).origin);
    await run(page);
    assert.deepEqual(page.consoleErrors, []);
  } finally {
    await page.close();
  }
}
async function goto(page, route, locale = "zh-CN") {
  await page.clearStorage(new URL(E2E_BASE_URL).origin);
  await gotoMockAdministrator(page, `${E2E_BASE_URL}/#/accounts`);
  await page.waitFor(`!!document.querySelector('[data-account-management] table')`);
  await page.eval(
    `(async()=>{const [{changeLocale},{writeStoredLocale},{default:i18n}]=await Promise.all([import('/src/app/i18n/changeLocale.ts'),import('/src/app/i18n/locales.ts'),import('/src/app/i18n/config.ts')]);await changeLocale(${JSON.stringify(locale)},writeStoredLocale);if((i18n.resolvedLanguage??i18n.language)!==${JSON.stringify(locale)})throw new Error('locale was not applied');})()`,
  );
  const pageRoute = route.split("?")[0];
  await page.eval(
    `(()=>{localStorage.setItem('sentinel.mock.initialized',${JSON.stringify(pageRoute !== "setup")});localStorage.setItem('sentinel.mock.role',${JSON.stringify(pageRoute === "login" ? "anonymous" : "admin")});if(${JSON.stringify(pageRoute === "setup")})localStorage.setItem('sentinel.mock.operator-authorized','true');else localStorage.removeItem('sentinel.mock.operator-authorized');})()`,
  );
  await page.goto(`${E2E_BASE_URL}/#/${route}`);
  const ready =
    pageRoute === "setup"
      ? `!!document.querySelector('.setup-form-grid')`
      : pageRoute === "login"
        ? `!!document.querySelector('.login-page form')`
        : `!!document.querySelector('.app-shell')&&!document.querySelector('[data-route-state="loading"]')&&!document.querySelector('[data-route-state="access-pending"]')`;
  await page.waitFor(ready, { label: `${pageRoute} authenticated route is ready` });
  await page.eval(
    `(async()=>{await Promise.all(document.getAnimations().filter(a=>a.playState==='running'&&Number.isFinite(a.effect?.getTiming().iterations)).map(a=>a.finished.catch(()=>{})));})()`,
  );
}
async function screenshot(page, name) {
  const dir = artifactDirectory("sentinel-f3-responsive-20261007");
  mkdirSync(dir, { recursive: true });
  writeFileSync(`${dir}/${name}.png`, await page.screenshot());
}
for (const { width, height, scale, name } of [
  { width: 320, height: 800, scale: 1, name: "narrow" },
  { width: 640, height: 450, scale: 2, name: "200-percent-equivalent" },
  { width: 1280, height: 900, scale: 1, name: "desktop" },
])
  test(`响应式 ${name}: 11 路由无页面横向溢出，账户与导航入口可达`, async () => {
    await withPage(async (page) => {
      await page.send("Emulation.setDeviceMetricsOverride", {
        width,
        height,
        deviceScaleFactor: scale,
        mobile: false,
      });
      for (const route of ROUTES) {
        await goto(page, route, width === 1280 ? "en-US" : "ja-JP");
        const result = await page.eval(
          `(()=>{const width=document.documentElement.clientWidth;const nav=document.querySelector('.main-nav'),user=document.querySelector('.avatar');const rect=e=>{const r=e?.getBoundingClientRect();return r?{left:r.left,right:r.right,width:r.width,height:r.height}:null;};return {width,body:document.body.scrollWidth,document:document.documentElement.scrollWidth,nav:rect(nav),user:rect(user),tables:[...document.querySelectorAll('.table-scroll')].map(rect),offenders:[...document.querySelectorAll('body *')].filter(e=>!nav?.contains(e)&&e.getBoundingClientRect().right>width+1&&getComputedStyle(e).position!=='absolute').slice(0,8).map(e=>({tag:e.tagName,classes:typeof e.className==='string'?e.className:'',text:e.textContent.trim().slice(0,45),left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right}))};})()`,
        );
        assert.ok(
          result.body <= result.width + 1 && result.document <= result.width + 1,
          route + ": " + JSON.stringify(result),
        );
        if (!["setup", "login"].includes(route)) {
          assert.ok(
            result.user?.width >= 24 && result.user.left >= 0 && result.user.right <= width + 1,
            route + " inaccessible account action " + JSON.stringify(result),
          );
          assert.ok(
            result.nav?.right <= width + 1,
            route + " navigation overflow " + JSON.stringify(result),
          );
        }
        assert.ok(
          result.tables.every((r) => r.left >= 0 && r.right <= width + 1),
          route + " table scroll container escaped page",
        );
        await screenshot(page, `${name}-${route.split("?")[0]}`);
      }
    });
  });
test("响应式: 1920px 保留单排导航，1280px 长文案换行，320px 末个导航键盘可达", async () => {
  await withPage(async (page) => {
    await page.send("Emulation.setDeviceMetricsOverride", {
      width: 1920,
      height: 900,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await goto(page, "overview", "en-US");
    assert.ok(
      await page.eval(`document.querySelector('.topbar').getBoundingClientRect().height<=61`),
    );
    await page.send("Emulation.setDeviceMetricsOverride", {
      width: 1280,
      height: 900,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await page.waitFor(`document.querySelector('.topbar').getBoundingClientRect().height>80`);
    await page.send("Emulation.setDeviceMetricsOverride", {
      width: 320,
      height: 800,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await page.eval(`document.querySelector('.main-nav button:last-child').focus()`);
    const rect = await page.eval(
      `(()=>{const r=document.activeElement.getBoundingClientRect();return {left:r.left,right:r.right};})()`,
    );
    assert.ok(rect.left >= 0 && rect.right <= 321, JSON.stringify(rect));
    await page.send("Input.dispatchKeyEvent", {
      type: "keyDown",
      key: "Enter",
      code: "Enter",
      windowsVirtualKeyCode: 13,
      text: "\r",
      unmodifiedText: "\r",
    });
    await page.send("Input.dispatchKeyEvent", {
      type: "keyUp",
      key: "Enter",
      code: "Enter",
      windowsVirtualKeyCode: 13,
    });
    await page.waitFor(`location.hash.startsWith('#/system')`);
  });
});
test("响应式: 表格滚动区可键盘聚焦，实例与详情不因窄屏丢失", async () => {
  await withPage(async (page) => {
    await page.send("Emulation.setDeviceMetricsOverride", {
      width: 320,
      height: 800,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await goto(page, "applications?app=app-one");
    await page.waitFor(`!!document.querySelector('[data-console-table-scroll]')`);
    const region = await page.eval(
      `(()=>{const r=document.querySelector('[data-console-table-scroll]');r.focus();return {role:r.getAttribute('role'),label:r.getAttribute('aria-label'),focused:document.activeElement===r,scrollable:r.scrollWidth>r.clientWidth};})()`,
    );
    assert.equal(region.role, "group");
    assert.ok(region.label && region.focused && region.scrollable, JSON.stringify(region));
    await page.send("Input.dispatchKeyEvent", {
      type: "keyDown",
      key: "ArrowRight",
      code: "ArrowRight",
      windowsVirtualKeyCode: 39,
    });
    await page.send("Input.dispatchKeyEvent", {
      type: "keyUp",
      key: "ArrowRight",
      code: "ArrowRight",
      windowsVirtualKeyCode: 39,
    });
    await page.waitFor(`document.querySelector('[data-console-table-scroll]').scrollLeft>0`);
    await page.click('[data-observed-instance="instance-1"] button');
    await page.waitFor(`!!document.querySelector('[data-instance-receipt]')`);
    assert.ok((await page.count("[data-instance-receipt]")) > 0);
  });
});
test("响应式: 深处表单聚焦时不被 sticky 顶栏遮挡", async () => {
  await withPage(async (page) => {
    await page.send("Emulation.setDeviceMetricsOverride", {
      width: 1280,
      height: 900,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await goto(page, "rules?env=test-env&app=app-one&binding=binding-app-one");
    await page.waitFor(`!!document.querySelector('[data-rule-source-summary]')`);
    await page.click('[data-rule-action="begin"]');
    await page.waitFor(
      `!!document.querySelector('[data-rule-action="add"]')&&!!document.querySelector('[data-ruleset-editor] input')`,
    );
    await page.eval(
      `(()=>{const input=[...document.querySelectorAll('[data-ruleset-editor] input')].at(-1);input.focus();input.scrollIntoView({block:'start',behavior:'instant'});})()`,
    );
    const result = await page.eval(
      `({focus:document.activeElement.getBoundingClientRect().top,header:document.querySelector('.topbar').getBoundingClientRect().bottom})`,
    );
    assert.ok(result.focus >= result.header + 2, JSON.stringify(result));
  });
});
import { artifactDirectory } from "./artifacts.mjs";
