import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { E2E_BASE_URL, connectIabBrowser } from "./cdp.mjs";
import { gotoMockAdministrator } from "./mock-auth.mjs";

let browser;
before(async () => {
  browser = await connectIabBrowser();
});
after(async () => {
  await browser?.close();
});

test("dashboard shell navigation keeps routes addressable and system tabs URL-owned", async () => {
  const page = await browser.newPage();
  try {
    await page.clearStorage(new URL(E2E_BASE_URL).origin);
    await gotoMockAdministrator(page, `${E2E_BASE_URL}/#/overview?app=all&range=1h`);
    await page.waitFor(`!!document.querySelector(".app-shell .main-nav")`);

    for (const [label, route] of [
      ["总览", "overview"],
      ["应用与实例", "applications"],
      ["规则", "rules"],
      ["实时监控", "realtime"],
      ["故障分析", "faults"],
      ["系统管理", "system"],
    ]) {
      await page.clickByText(label, ".main-nav button");
      await page.waitFor(`location.hash.startsWith("#/${route}")`);
      await page.waitFor(
        `[...document.querySelectorAll(".main-nav button")].some((button) => button.textContent.trim() === ${JSON.stringify(label)} && button.className.includes("active"))`,
      );
      assert.match(await page.hash(), new RegExp(`^#/${route}(?:\\?|$)`));
    }

    await page.goto(`${E2E_BASE_URL}/#/system?view=audit`);
    await page.waitFor(
      `[...document.querySelectorAll(".page-system h2")].some((heading) => heading.textContent.trim() === "操作审计")`,
      { label: "audit tab panel rendered" },
    );
    assert.match(await page.hash(), /view=audit/);
    assert.deepEqual(page.consoleErrors, []);
  } finally {
    await page.close();
  }
});
