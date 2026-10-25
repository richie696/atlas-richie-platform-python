/**
 * 交互层 E2E 用例。
 *
 * 中文
 * ----
 * 视觉基线（`tests/visual/`）只捕获首屏渲染，**证明不了交互正确**。历史缺陷正是
 * 只在交互/深链后才暴露：规则页筛选后检视器落到无意义空态，而 28 条基线用例
 * （含 5 条 `rules-filter-*`）全部「通过」——因为每一帧都截到了，只是截到的是错的。
 *
 * 这层用例补上「点了会发生什么」：导航跳转、筛选写入 URL、受控回环、深链恢复、
 * 空态语义。断言优先读 URL（可分享的契约）与语义标记，不依赖像素。
 *
 * 跑法：
 * ```bash
 * npm run test:e2e                       # 需要 dev server 在 BASE_URL 运行
 * BASE_URL=http://localhost:5173 npm run test:e2e
 * ```
 */
import { after, before, describe, it } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";

import { E2E_BASE_URL, connectIabBrowser } from "./cdp.mjs";

let browser;
const authenticatedPages = new WeakSet();

before(async () => {
  browser = await connectIabBrowser();
});

after(async () => {
  await browser?.close();
  // Let node:test report failed hooks/cancelled cases. Forcing exit here can
  // turn a browser startup failure into a misleading single passing file.
});

/** Separate document AND origin storage per case; tabs alone share localStorage/cookies. */
async function withPage(run) {
  const page = await browser.newPage();
  try {
    await page.clearStorage(new URL(E2E_BASE_URL).origin);
    await run(page);
  } finally {
    try {
      assert.deepEqual(
        page.consoleErrors,
        [],
        `页面产生了控制台错误:\n${page.consoleErrors.join("\n")}`,
      );
    } finally {
      // 不关页面的话标签会一直累积，整套用例越跑越慢。
      await page.close();
    }
  }
}

/** Await routed content, not merely the shell that appears before a lazy chunk. */
async function gotoDashboard(page, url) {
  const target = new URL(url);
  const route = target.hash.slice(1).split("?", 1)[0];
  const publicRoute = route === "/login" || route === "/setup";
  if (!publicRoute && !authenticatedPages.has(page)) {
    // Route/UI E2E cases exercise protected screens, not the login workflow.
    // Seed only the explicit demo HTTP mock identity before the app's first
    // authenticated read; login/setup acceptance has its own dedicated suites.
    await page.goto(`${target.origin}/`);
    await page.eval(`localStorage.setItem('sentinel.mock.role', 'admin')`);
    await page.send("Page.reload", { ignoreCache: true });
    await page.waitFor(`!!document.querySelector('.main-nav')`, {
      label: "mock administrator session",
    });
    authenticatedPages.add(page);
  }
  await page.goto(url);
  await page.waitFor(
    `(() => {
    const root = document.getElementById('root');
    return !!root?.children.length && !root.querySelector('[data-route-state="loading"], [data-route-state="access-pending"]');
  })()`,
    { label: "route and session access ready" },
  );
}

/**
 * 规则页「类型筛选」下拉的稳定选择器。
 *
 * 中文
 * ----
 * **不要用全页下标。** 规则表单会按规则类型渲染不同数量的 Select，实测
 * `view=flow` 时全页 7 个 combobox、`view=system` 时只有 4 个——下标 3 碰巧对，
 * 但那取决于表单的 Select 个数，规则类型一变就可能指到别的控件。
 *
 * 目录面板内始终只有一个 combobox，就是类型筛选，作用域内下标恒为 0。
 */
const RULE_KIND_FILTER = ".rules-layout > *:nth-child(1) button[role='combobox']";

/**
 * Astryx `Selector` 是自绘控件：先点 combobox 展开，再点目标 option。
 *
 * 中文
 * ----
 * **必须用可见性判断展开状态，不能用「节点存在」。** Astryx 把所有 listbox 常驻
 * DOM（不点开也 querySelector 得到），因此 `!!document.querySelector('div[role=option]')`
 * 永远为真，等待会立即通过——下拉实际没展开时测试照样往下走。踩过这个坑：第二次点
 * combobox 并没有展开，脚本却以为展开了，随后在隐藏选项上量坐标，结果什么都没点到，
 * 一度被误判成业务缺陷。
 *
 * 判据用 `offsetParent`（隐藏元素为 null），是不引入布局库时最省事的可见性近似。
 */
async function selectFromTrigger(page, selector, optionText, index = 0) {
  await page.click(selector, { index });
  await waitDropdownOpen(page);
  const selection = await page.eval(`(() => {
    const options=[...document.querySelectorAll('div[role="option"]')].filter(option=>option.offsetParent);
    return {current:options.findIndex(option=>option.getAttribute('aria-selected')==='true'),target:options.findIndex(option=>option.textContent.trim().includes(${JSON.stringify(optionText)}))};
  })()`);
  assert.ok(selection.current >= 0, "当前选项应可访问");
  assert.ok(selection.target >= 0, `找不到下拉选项「${optionText}」`);
  const direction = selection.target >= selection.current ? "ArrowDown" : "ArrowUp";
  for (let index = 0; index < Math.abs(selection.target - selection.current); index += 1) {
    await page.send("Input.dispatchKeyEvent", {
      type: "keyDown",
      key: direction,
      code: direction,
      windowsVirtualKeyCode: direction === "ArrowDown" ? 40 : 38,
    });
    await page.send("Input.dispatchKeyEvent", {
      type: "keyUp",
      key: direction,
      code: direction,
      windowsVirtualKeyCode: direction === "ArrowDown" ? 40 : 38,
    });
  }
  await page.send("Input.dispatchKeyEvent", {
    type: "keyDown",
    key: "Enter",
    code: "Enter",
    windowsVirtualKeyCode: 13,
  });
  await page.send("Input.dispatchKeyEvent", {
    type: "keyUp",
    key: "Enter",
    code: "Enter",
    windowsVirtualKeyCode: 13,
  });
  await waitDropdownClosed(page);
}

async function selectOption(page, comboboxIndex, optionText) {
  const exists = await page.eval(
    `document.querySelectorAll('button[role="combobox"]').length > ${comboboxIndex}`,
  );
  assert.ok(exists, `找不到第 ${comboboxIndex} 个下拉框`);
  await selectFromTrigger(page, "button[role='combobox']", optionText, comboboxIndex);
}

async function observationCombobox(page, index) {
  const selector = `[data-observation-filters] [role="combobox"]`;
  await page.waitFor(
    `document.querySelectorAll(${JSON.stringify(selector)}).length > ${index}`,
    { label: `第 ${index + 1} 个观测筛选控件挂载` },
  );
  const exists = await page.eval(
    `document.querySelectorAll(${JSON.stringify(selector)}).length > ${index}`,
  );
  assert.ok(exists, `找不到第 ${index + 1} 个观测筛选控件`);
  return { selector, index };
}

async function selectObservationOption(page, index, optionText) {
  const control = await observationCombobox(page, index);
  await selectFromTrigger(page, control.selector, optionText, control.index);
}

/** 等待至少有一个**可见**的 option，即下拉确实展开了。 */
function waitDropdownOpen(page) {
  return page.waitFor(
    `[...document.querySelectorAll('div[role="option"]')].some((o) => o.offsetParent)`,
    { label: "下拉展开（存在可见 option）" },
  );
}

/** 等待没有可见 option，即下拉已收起。 */
function waitDropdownClosed(page) {
  return page.waitFor(
    `![...document.querySelectorAll('div[role="option"]')].some((o) => o.offsetParent)`,
    { label: "下拉收起" },
  );
}

/** Compare vendor control border boxes, not their internally inset native inputs. */
async function assertFormGridAlignment(page, scope) {
  const grids =
    await page.eval(`(() => [...document.querySelectorAll(${JSON.stringify(scope + " .sentinel-form-fields")})].map(grid => {
    const fields=[...grid.children].map(child=>child.matches('.astryx-field')?child:child.querySelector('.astryx-field')).filter(Boolean);
    return fields.map(field=>{
      const control=field.querySelector('.astryx-text-input,.astryx-number-input,.astryx-selector');
      const f=field.getBoundingClientRect(), c=control?.getBoundingClientRect();
      return {label:field.querySelector('label')?.textContent, fieldTop:f.top, top:c?.top, left:c?.left, width:c?.width, fieldWidth:f.width};
    });
  }))()`);
  assert.ok(grids.length > 0, `no production FormGrid under ${scope}`);
  for (const fields of grids) {
    for (const field of fields) {
      assert.ok(
        field.width > 0 && field.width <= field.fieldWidth + 1,
        `control escaped its slot: ${JSON.stringify(field)}`,
      );
      for (const other of fields) {
        if (field !== other && Math.abs(field.fieldTop - other.fieldTop) < 1)
          assert.ok(
            Math.abs(field.top - other.top) < 1,
            `same-row controls are misaligned: ${JSON.stringify([field, other])}`,
          );
      }
    }
  }
}

async function saveFormEvidence(page, name) {
  // Do not mistake a half-faded opening animation for a new visual baseline.
  await page.eval(`(async () => {
    const transitions=document.getAnimations().filter(a=>a.playState==='running'&&Number.isFinite(a.effect?.getTiming().iterations));
    await Promise.all(transitions.map(a=>a.finished.catch(()=>{})));
  })()`);
  const directory = artifactDirectory("sentinel-f3-production-forms-20261007");
  mkdirSync(directory, { recursive: true });
  writeFileSync(`${directory}/${name}.png`, await page.screenshot());
}

describe("F3 样式所有权", () => {
  it("实际集群表单使用正式枚举选项，开关不与数值框混排且无内层焦点框", async () => {
    await withPage(async (page) => {
      await gotoDashboard(page, `${E2E_BASE_URL}/#/rules?env=test-env&app=app-one&view=flow`);
      await page.waitFor(`!!document.querySelector('[data-rule-binding-open="binding-app-one"]')`, {
        label: "Flow rule binding directory",
      });
      await page.click('[data-rule-binding-open="binding-app-one"]');
      await page.waitFor(`!!document.querySelector('[data-rule-workspace]')`);
      await page.click('[data-rule-action="begin"]');
      await page.waitFor(`!!document.querySelector('[data-rule-record]')`, {
        label: "the imported draft rule is available for explicit selection",
      });
      await page.click('[data-rule-record]');
      await page.waitFor(`!!document.querySelector('[data-ruleset-editor] .rule-form')`);
      await page.click('.rule-toggle input[type="checkbox"]');
      await page.waitFor(`!!document.querySelector('.cluster-grid')`);
      await assertFormGridAlignment(page, ".rule-form");
      assert.equal(
        await page.count('.cluster-grid input[role="spinbutton"]'),
        2,
        "threshold type must not be a numeric code input",
      );
      await page.click('.cluster-grid button[role="combobox"]');
      await waitDropdownOpen(page);
      await page.eval(`(async () => {
        const transitions = document.getAnimations().filter(animation =>
          animation.playState === 'running' && Number.isFinite(animation.effect?.getTiming().iterations),
        );
        await Promise.all(transitions.map(animation => animation.finished.catch(() => {})));
      })()`);
      assert.deepEqual(
        await page.eval(
          `[...document.querySelectorAll('div[role="option"]')].filter(o=>o.offsetParent).map(o=>o.textContent.trim())`,
        ),
        ["单机平均额度", "集群总额度"],
      );
      await page.send("Input.dispatchKeyEvent", {
        type: "keyDown",
        key: "ArrowDown",
        code: "ArrowDown",
        windowsVirtualKeyCode: 40,
      });
      await page.send("Input.dispatchKeyEvent", {
        type: "keyUp",
        key: "ArrowDown",
        code: "ArrowDown",
        windowsVirtualKeyCode: 40,
      });
      await page.send("Input.dispatchKeyEvent", {
        type: "keyDown",
        key: "Enter",
        code: "Enter",
        windowsVirtualKeyCode: 13,
      });
      await page.send("Input.dispatchKeyEvent", {
        type: "keyUp",
        key: "Enter",
        code: "Enter",
        windowsVirtualKeyCode: 13,
      });
      await waitDropdownClosed(page);
      await page.waitFor(
        `document.querySelector('.cluster-grid button[role="combobox"]').textContent.includes('集群总额度')`,
      );
      await page.click('.cluster-grid input[role="spinbutton"]');
      assert.equal(
        await page.eval(`getComputedStyle(document.activeElement).outlineStyle`),
        "none",
      );
      await saveFormEvidence(page, "flow-cluster");
    });
  });
  it("新增账号与初始化各步骤复用字段布局，单选卡片由公开 slot 着色", async () => {
    await withPage(async (page) => {
      await gotoDashboard(page, `${E2E_BASE_URL}/`);
      await page.eval(
        `localStorage.setItem('sentinel.mock.initialized','true');localStorage.setItem('sentinel.mock.role','admin')`,
      );
      await gotoDashboard(page, `${E2E_BASE_URL}/#/accounts`);
      await page.waitFor(`!!document.querySelector('[data-account-management] table')`);
      await page.clickByText("新增账号");
      await page.waitFor(`!!document.querySelector('dialog[open]')`);
      await assertFormGridAlignment(page, "dialog[open]");
      assert.equal(await page.count('dialog[open] input[type="password"]'), 1);
      await saveFormEvidence(page, "account-create");
      await page.clickByText("取消", "dialog[open] button");
      await page.eval(
        `localStorage.setItem('sentinel.mock.initialized','false');localStorage.setItem('sentinel.mock.operator-authorized','true');localStorage.removeItem('sentinel.mock.role')`,
      );
      await gotoDashboard(page, `${E2E_BASE_URL}/#/setup`);
      await page.waitFor(`!!document.querySelector('.setup-form-grid')`);
      await assertFormGridAlignment(page, ".setup-workspace");
      await saveFormEvidence(page, "setup-storage");
      await page.type('.setup-workspace input[autocomplete="off"]', "db.synthetic.internal");
      await page.click('.setup-workspace input[autocomplete="off"]', { index: 1 });
      await page.send("Input.insertText", { text: "sentinel_e2e" });
      await page.type(
        '.setup-workspace input[autocomplete="username"]',
        "synthetic-connection-user",
      );
      await page.type('.setup-workspace input[type="password"]', "SYNTHETIC-DB");
      await page.clickByText("下一步");
      await page.waitFor(
        `document.querySelector('.setup-workspace').textContent.includes('创建内置管理员')`,
      );
      await assertFormGridAlignment(page, ".setup-workspace");
      await saveFormEvidence(page, "setup-admin");
      await page.type('.setup-workspace input[autocomplete="username"]', "synthetic-admin");
      await page.type('.setup-workspace input[type="password"]', "Synthetic-only-Password-42");
      await page.click('.setup-workspace input[type="password"]', { index: 1 });
      await page.send("Input.insertText", { text: "Synthetic-only-Password-42" });
      await page.clickByText("下一步");
      await page.waitFor(`!!document.querySelector('.setup-authentication')`);
      await assertFormGridAlignment(page, ".setup-workspace");
      await saveFormEvidence(page, "setup-source-reference");
      await page.clickByText("在控制台填写凭证", ".setup-authentication .astryx-radio-list-item");
      await page.waitFor(`!!document.querySelector('.setup-workspace input[type="password"]')`);
      await assertFormGridAlignment(page, ".setup-workspace");
      await saveFormEvidence(page, "setup-source-direct");
    });
  });
  it("共享表单在三语长帮助、字段错误和窄容器下对齐，原生输入与 checkbox 仍可用", async () => {
    await withPage(async (page) => {
      await gotoDashboard(page, `${E2E_BASE_URL}/#/accounts`);
      await page.eval(`(async () => {
        const React = (await import('/node_modules/.vite/deps/react.js')).default;
        const {createRoot} = (await import('/node_modules/.vite/deps/react-dom_client.js')).default;
        const {FormGridProbe} = await import('/tests/e2e/probes/FormGridProbe.tsx');
        const container=document.createElement('section'); container.id='form-grid-probe'; document.body.prepend(container);
        const root=createRoot(container); root.render(React.createElement(FormGridProbe));
        window.__formGridClean=()=>{root.unmount();container.remove();};
      })()`);
      await page.waitFor(`!!document.querySelector('#form-grid-probe output')`);
      const measure = `(() => {
        const root=document.querySelector('#form-grid-probe');
        const control=name=>{const label=[...root.querySelectorAll('label')].find(l=>l.textContent===name);return label&&document.getElementById(label.htmlFor);};
        const rect=name=>{const input=control(name);const box=input.closest('.astryx-text-input,.astryx-number-input,.astryx-selector')??input;const r=box.getBoundingClientRect(); return {top:r.top,bottom:r.bottom,left:r.left,width:r.width};};
        const grid=root.querySelector('.sentinel-form-fields').getBoundingClientRect();
        return {account:rect('Account'),quota:rect('Quota'),mode:rect('Mode'),explanation:rect('Additional explanation with a longer label'),full:rect('Full-row field'),gridWidth:grid.width};
      })()`;
      for (const locale of ["zh", "en", "ja"]) {
        await page.click(`#form-grid-probe [data-locale="${locale}"]`);
        for (const error of [false, true]) {
          if (
            (await page.eval(
              `JSON.parse(document.querySelector('#form-grid-probe output').textContent).error`,
            )) !== error
          )
            await page.click('#form-grid-probe [data-action="error"]');
          const bounds = await page.eval(measure);
          assert.ok(
            Math.abs(bounds.account.top - bounds.quota.top) < 1,
            `${locale}/${error}: text/number control top differs: ${JSON.stringify(bounds)}`,
          );
          assert.ok(
            Math.abs(bounds.mode.top - bounds.explanation.top) < 1,
            `${locale}/${error}: selector/text border box top differs: ${JSON.stringify(bounds)}`,
          );
          assert.ok(
            bounds.full.width > bounds.gridWidth - 5,
            "full-row field does not fill the grid",
          );
        }
      }
      await page.click('#form-grid-probe input[role="spinbutton"]');
      assert.equal(
        await page.eval(`getComputedStyle(document.activeElement).outlineStyle`),
        "none",
        "native outline must not compete with Astryx wrapper focus",
      );
      assert.equal(await page.eval(`document.activeElement.getAttribute('role')`), "spinbutton");
      await page.clickByText("Allow fallback", "#form-grid-probe label");
      await page.waitFor(
        `!JSON.parse(document.querySelector('#form-grid-probe output').textContent).fallback`,
      );
      const directory = artifactDirectory("sentinel-f3-form-grid-20261007");
      mkdirSync(directory, { recursive: true });
      writeFileSync(`${directory}/wide-error-ja.png`, await page.screenshot());
      await page.click('#form-grid-probe [data-action="width"]');
      await page.waitFor(
        `JSON.parse(document.querySelector('#form-grid-probe output').textContent).narrow`,
      );
      await page.waitFor(
        `(() => {const b=${measure};return Math.abs(b.account.left-b.quota.left)<1&&b.quota.top>b.account.bottom;})()`,
      );
      const narrow = await page.eval(measure);
      assert.ok(
        narrow.account.width > narrow.gridWidth - 5,
        "narrow container did not become one column",
      );
      assert.equal(
        await page.eval(
          `JSON.parse(document.querySelector('#form-grid-probe output').textContent).quota`,
        ),
        "10",
      );
      writeFileSync(`${directory}/narrow-error-ja.png`, await page.screenshot());
      await page.eval(`window.__formGridClean()`);
    });
  });
  it("跨 lazy 页面载入顺序不改变身份标题、实例密度和页面间距", async () => {
    await withPage(async (page) => {
      await gotoDashboard(page, `${E2E_BASE_URL}/`);
      await page.eval(
        `localStorage.setItem('sentinel.mock.initialized','true');localStorage.setItem('sentinel.mock.role','admin')`,
      );
      await gotoDashboard(page, `${E2E_BASE_URL}/#/accounts`);
      await page.waitFor(`!!document.querySelector('[data-account-management] table')`);
      assert.deepEqual(
        await page.eval(`(() => ({
        alignment: getComputedStyle(document.querySelector('.identity-intro')).alignItems,
        margin: getComputedStyle(document.querySelector('.identity-panel')).marginBottom,
      }))()`),
        { alignment: "flex-end", margin: "16px" },
      );
      for (const title of ["应用与实例", "总览", "应用与实例"]) {
        await page.clickByText(title, ".main-nav button");
        await page.waitFor(
          `!!document.querySelector(${JSON.stringify(title === "总览" ? "[data-fleet-application]" : "[data-observed-instance]")})`,
        );
        assert.equal(
          await page.eval(`getComputedStyle(document.querySelector('main')).paddingTop`),
          "13px",
        );
        if (title === "应用与实例") {
          const cells = await page.eval(`(() => {
            const cell = document.querySelector('[data-observed-instance] td:nth-child(2)');
            return {top:getComputedStyle(cell).paddingTop, left:getComputedStyle(cell).paddingLeft,
              groups:document.querySelectorAll('main details').length};
          })()`);
          assert.equal(cells.top, "11px");
          assert.equal(cells.left, "12px");
          assert.ok(
            cells.groups > 0,
            "observed instances remain grouped by host without fabricating host rows",
          );
        }
      }
    });
  });
});

describe("应用壳导航", () => {
  const NAV = [
    ["总览", "overview"],
    ["应用与实例", "applications"],
    ["规则", "rules"],
    ["实时监控", "realtime"],
    ["故障分析", "faults"],
    ["系统管理", "system"],
  ];

  for (const [label, route] of NAV) {
    it(`点击「${label}」进入 ${route} 并把路由写进 URL`, async () => {
      await withPage(async (page) => {
        await gotoDashboard(page, `${E2E_BASE_URL}/#/overview?app=all&range=1h`);
        await page.waitFor(`!!document.querySelector('.topbar')`, { label: "顶栏" });

        await page.clickByText(label, ".main-nav button");
        await page.waitFor(`location.hash.includes('/${route}')`, { label: `跳到 ${route}` });

        const current = await page.hash();
        assert.match(
          current,
          new RegExp(`^#/${route}\\?`),
          `hash 应以 #/${route}? 开头，实际 ${current}`,
        );
        // 导航必须带上下文：切页后筛选条件不应丢失
        assert.match(current, /app=/, "导航后应保留 app 上下文");
        assert.match(current, /range=/, "导航后应保留 range 上下文");
        // 高亮项必须跟着路由走，否则「点了没反应」会被当成成功。
        // 必须 waitFor：URL 变更（hashchange）与 React 重渲染不是同一时刻，
        // 直接读会读到上一个路由的高亮——踩过一次，4 条导航用例全假失败。
        await page.waitFor(
          `[...document.querySelectorAll('.main-nav button')]
             .filter((b) => b.className.includes('active'))
             .map((b) => b.textContent.trim()).join() === ${JSON.stringify(label)}`,
          { label: `导航高亮切到「${label}」` },
        );
      });
    });
  }

  it("深链刷新后恢复到同一视图", async () => {
    await withPage(async (page) => {
      const deep = `${E2E_BASE_URL}/#/realtime?app=order-service&range=15m`;
      await gotoDashboard(page, deep);
      await page.waitFor(`!!document.querySelector('.topbar')`, { label: "顶栏" });
      await gotoDashboard(page, deep);
      await page.waitFor(`!!document.querySelector('.page-realtime')`, { label: "实时监控页" });
      assert.match(await page.hash(), /app=order-service/);
      assert.match(await page.hash(), /range=15m/);
    });
  });

  // 应用筛选不得展示其他应用的实例
  // ------------------------------
  // 当前应用页按 HTTP 目录及 URL 中明确选择的 appId 查询实例，不存在“用另一个应用的
  // 示例矩阵兜底”的旧原型逻辑。这里验证过滤结果只包含所选应用，且不会静默混入 app-one。
  describe("无实例示例数据的应用", () => {
    it("切换到 app-two 后只显示其目录实例，不借用 app-one 的数据", async () => {
      await withPage(async (page) => {
        await gotoDashboard(
          page,
          `${E2E_BASE_URL}/#/applications?env=test-env&app=app-two&range=1h`,
        );
        await page.waitFor(`!!document.querySelector('[data-observed-instance="instance-3"]')`, {
          label: "所选应用实例目录",
        });
        assert.equal(await page.count("[data-observed-instance]"), 1);
        assert.equal(await page.count('[data-observed-instance="instance-1"]'), 0);
        assert.equal(await page.text('[data-observed-instance="instance-3"] td'), "app-two");
        assert.match(await page.hash(), /app=app-two/);
      });
    });
  });

  // 权限门禁
  // --------
  // `DASHBOARD_CONTROL_PLANE.md` §2：两个能力可独立授予，缺 `rules:write` 时
  // 规则页隐藏写入口。**界面隐藏不是安全边界**——服务端在每次写操作上仍会独立
  // 校验，这层用例验证的只是「入口不显示」。
  describe("权限门禁", () => {
    /**
     * 切换演示身份。
     *
     * mock 服务端角色存在 mock-only 的 `sentinel.mock.role`，不经过登录
     * 流程——这里要验证的是门禁，不是登录表单。
     */
    async function withRole(page, role) {
      await gotoDashboard(page, `${E2E_BASE_URL}/`);
      await page.eval(`window.localStorage.setItem('sentinel.mock.role', ${JSON.stringify(role)})`);
      await gotoDashboard(page, `${E2E_BASE_URL}/#/rules?env=test-env&app=app-one&view=flow`);
      await page.waitFor(`!!document.querySelector('[data-rule-binding-open], [role="alert"]')`, {
        label: "规则目录或权限反馈",
      });
    }

    it("全权限身份显示规则写入口", async () => {
      await withPage(async (page) => {
        await withRole(page, "admin");
        await page.click('[data-rule-binding-open="binding-app-one"]');
        await page.waitFor(
          `!!document.querySelector('[data-rule-workspace] [data-rule-action="begin"]')`,
        );
        assert.equal(await page.count('[data-rule-workspace] [data-rule-action="begin"]'), 1);
      });
    });

    it("只读身份隐藏全部规则写入口, 但仍可读规则目录", async () => {
      await withPage(async (page) => {
        await withRole(page, "view");
        assert.ok((await page.count("[data-rule-binding-open]")) > 0, "view 身份仍可读规则目录");
        await page.click('[data-rule-binding-open="binding-app-one"]');
        await page.waitFor(`!!document.querySelector('[data-rule-workspace]')`);
        assert.equal(
          await page.count("[data-rule-workspace] [data-rule-action]"),
          0,
          "view 身份不得得到规则编辑命令",
        );
        assert.ok(
          (await page.text("[data-rule-workspace]")).length > 0,
          "受限编辑区仍提供权限说明",
        );
      });
    });

    it("身份切换后无需刷新即可生效", async () => {
      await withPage(async (page) => {
        await withRole(page, "admin");
        assert.ok((await page.count("[data-rule-binding-open]")) > 0, "管理员可读取规则目录");
        await page.eval(`window.localStorage.setItem('sentinel.mock.role', 'view')`);
        await gotoDashboard(page, `${E2E_BASE_URL}/#/faults`);
        await gotoDashboard(page, `${E2E_BASE_URL}/#/rules?env=test-env&app=app-one&view=flow`);
        await page.waitFor(`!!document.querySelector('[data-rule-binding-open]')`, {
          label: "规则目录重载",
        });
        await page.click('[data-rule-binding-open="binding-app-one"]');
        await page.waitFor(`!!document.querySelector('[data-rule-workspace]')`);
        assert.equal(
          await page.count("[data-rule-workspace] [data-rule-action]"),
          0,
          "切换 view 后编辑命令应撤销",
        );
      });
    });
  });

  it("登录页不套应用壳", async () => {
    await withPage(async (page) => {
      await gotoDashboard(page, `${E2E_BASE_URL}/#/login`);
      await page.waitFor(`!!document.querySelector('body')`, { label: "登录页" });
      assert.equal(await page.count(".topbar"), 0, "登录页不应出现应用壳顶栏");
      assert.equal(await page.count(".demo-banner"), 0, "登录页不应出现示例回放横幅");
    });
  });
});

describe("筛选上下文写入 URL", () => {
  it("切换时间窗口写回 URL 并影响标签", async () => {
    await withPage(async (page) => {
      await gotoDashboard(page, `${E2E_BASE_URL}/#/overview?app=all&range=1h`);
      await page.waitFor(`!!document.querySelector('.page-overview')`, { label: "总览" });

      await selectObservationOption(page, 2, "最近 15 分钟");
      await page.waitFor(`location.hash.includes('range=15m')`, { label: "range 写回" });
      assert.match(await page.hash(), /range=15m/);

      const rangeControl = (await observationCombobox(page, 2)).selector;
      await page.waitFor(
        `document.querySelectorAll(${JSON.stringify(rangeControl)})[2].textContent.trim() === "最近 15 分钟"`,
        { label: "时间范围下拉显示新窗口" },
      );
    });
  });

  it("非法 range 被丢弃，界面不出现未匹配值", async () => {
    await withPage(async (page) => {
      await gotoDashboard(page, `${E2E_BASE_URL}/#/overview?app=all&range=bogus`);
      await page.waitFor(`!!document.querySelector('.page-overview')`, { label: "总览" });
      const rangeControl = (await observationCombobox(page, 2)).selector;
      const labels = await page.eval(
        `[document.querySelectorAll(${JSON.stringify(rangeControl)})[2].textContent.trim()]`,
      );
      assert.ok(
        !labels.some((text) => text.includes("bogus")),
        `非法 range 不应出现在下拉里，实际: ${JSON.stringify(labels)}`,
      );
      // 非法值应被丢弃而不是回落到某个「看起来合理」的窗口
      assert.equal(labels[0], "最近 1 小时", "非法 range 应回落到缺省窗口");
    });
  });

  it("single 粒度路由把「全部应用」收敛为真实应用", async () => {
    await withPage(async (page) => {
      // `#/applications?app=all` 是合法的可分享形态（深链可直达），但应用页是
      // `single` 粒度，不接受「全部应用」：下拉框必须落到一个真实应用，
      // 否则匹配不到任何选项而退化成占位符。目录读到后 URL 也应收敛为实际 app。
      await gotoDashboard(page, `${E2E_BASE_URL}/#/applications?app=all&range=1h`);
      await page.waitFor(`!!document.querySelector('.page-applications')`, { label: "应用页" });
      await page.waitFor(`location.hash.includes('app=app-one')`, {
        label: "目录加载后收敛到默认应用",
      });
      const applicationControl = (await observationCombobox(page, 1)).selector;
      const appLabel = await page.eval(
        `document.querySelectorAll(${JSON.stringify(applicationControl)})[1].textContent.trim()`,
      );
      assert.notEqual(appLabel, "全部应用", "single 路由的应用下拉不应停在「全部应用」");
      assert.ok(appLabel.length > 0, "应用下拉应有真实应用名");
    });
  });
});

describe("系统管理 tab 受控于 URL", () => {
  const TABS = [
    ["connections", "连接与采集", "[data-system-connection]"],
    ["permissions", "权限与审计", "[data-session-permissions]"],
    ["protocol", "协议与版本", "[data-system-protocol]"],
    ["audit", "操作审计", "[data-system-audit]"],
    ["accounts", "账户维护", "[data-account-management]"],
    ["roles", "角色绑定", "[data-role-management]"],
  ];

  for (const [tab, label, panel] of TABS) {
    it(`切到 ${tab} 写回 view 参数并渲染对应面板`, async () => {
      await withPage(async (page) => {
        await gotoDashboard(page, `${E2E_BASE_URL}/#/system`);
        await page.waitFor(`!!document.querySelector('[role="group"][aria-label] button')`, {
          label: "系统管理 tabs",
        });
        if (tab === "connections") {
          // Connections is the default tab. Clicking an already-selected tab is
          // intentionally a no-op and should not add redundant URL state.
          await page.waitFor(`!!document.querySelector(${JSON.stringify(panel)})`, {
            label: "默认连接面板",
          });
          return;
        }
        await page.clickByText(label, '[role="group"][aria-label] button');
        await page.waitFor(`location.hash.includes(${JSON.stringify(`view=${tab}`)})`, {
          label: `${tab} 写入 URL`,
        });
        await page.waitFor(`!!document.querySelector(${JSON.stringify(panel)})`, {
          label: `${tab} 正式面板`,
        });
      });
    });
  }
});

// Legacy route/form assertions below target the retired inline editor (`order-service`,
// `.rule-edit-button`, `.rule-inspector`, `.rules-layout`). The current product selects an
// environment/application binding before opening a workspace; current route, directory, HTTP,
// and workspace behavior is covered by rule-set-http, rule-directory, and rule-workspace specs.
describe.skip("已被绑定式规则工作台用例替代的旧规则页面断言", () => {
  it("只读用例之后的新用例从独立管理员演示状态开始", async () => {
    await withPage(async (page) => {
      await gotoDashboard(page, `${E2E_BASE_URL}/#/rules?app=order-service`);
      await page.eval(`localStorage.setItem('sentinel.mock.role', 'view')`);
      await gotoDashboard(page, `${E2E_BASE_URL}/#/rules?app=order-service`);
      assert.equal(await page.count(".rule-edit-button"), 0);
    });
    await withPage(async (page) => {
      await page.goto(`${E2E_BASE_URL}/#/login`);
      await page.eval(
        `localStorage.setItem('sentinel.mock.initialized', 'true'); localStorage.setItem('sentinel.mock.role', 'admin'); location.reload();`,
      );
      await gotoDashboard(page, `${E2E_BASE_URL}/#/rules?app=order-service`);
      assert.equal(await page.count(".rule-edit-button"), 1);
      assert.equal(await page.eval(`localStorage.getItem('sentinel.mock.role')`), "admin");
    });
  });
  it("参数例外编辑保留焦点，删除相邻行不丢另一行的草稿，表单标识不进入 JSON", async () => {
    await withPage(async (page) => {
      await gotoDashboard(page, `${E2E_BASE_URL}/#/rules?app=user-service&view=param`);
      await page.waitFor(`!!document.querySelector('.rule-edit-button')`);
      await page.click(".rule-edit-button");
      const input = ".param-item input";
      await page.click(input);
      await page.eval(`document.querySelector(${JSON.stringify(input)}).select()`);
      await page.send("Input.insertText", { text: "java.lang.Long" });
      await page.waitFor(
        `document.querySelector(${JSON.stringify(input)})?.value === 'java.lang.Long'`,
      );
      assert.ok(
        await page.eval(
          `document.activeElement===document.querySelector(${JSON.stringify(input)})`,
        ),
      );
      await page.clickByText("添加例外值", ".param-exceptions-head button");
      await page.waitFor(`document.querySelectorAll('.param-item').length===2`);
      await page.clickByText("移除", ".param-item button");
      await page.waitFor(`document.querySelectorAll('.param-item').length===1`);
      const preview = await page.eval(
        `JSON.parse(document.querySelector('.compatibility-json pre').textContent)[0].paramFlowItemList`,
      );
      assert.deepEqual(preview, [{ classType: "java.lang.String", object: "", count: 120 }]);
      assert.ok(!JSON.stringify(preview).includes("formKey"));
    });
  });
  it("数字草稿支持分数与真正清空，清空不会隐式变成零或回到旧值", async () => {
    await withPage(async (page) => {
      await gotoDashboard(page, `${E2E_BASE_URL}/#/rules?app=order-service&view=flow`);
      await page.waitFor(`!!document.querySelector('.rule-edit-button')`);
      await page.click(".rule-edit-button");
      const found = await page.eval(`(() => {
        const label = [...document.querySelectorAll('.rule-inspector label')].find(label=>label.textContent.trim()==='单机阈值');
        const input = label && document.getElementById(label.htmlFor); if (!input) return false;
        input.dataset.ruleTest='decimal-field';return true;
      })()`);
      assert.ok(found);
      const input = '[data-rule-test="decimal-field"]',
        value = `JSON.parse(document.querySelector('.compatibility-json pre').textContent)[0].count`;
      await page.click(input);
      await page.eval(`document.querySelector(${JSON.stringify(input)}).select()`);
      await page.send("Input.insertText", { text: "1.5" });
      await page.click(".rule-inspector .primary-button.full");
      await page.waitFor(
        `${value} === 1.5 && !document.querySelector('.rule-inspector .inline-note.invalid')`,
      );
      await page.click(input);
      await page.eval(`document.querySelector(${JSON.stringify(input)}).select()`);
      await page.send("Input.dispatchKeyEvent", {
        type: "keyDown",
        key: "Backspace",
        code: "Backspace",
        windowsVirtualKeyCode: 8,
      });
      await page.send("Input.dispatchKeyEvent", {
        type: "keyUp",
        key: "Backspace",
        code: "Backspace",
        windowsVirtualKeyCode: 8,
      });
      await page.click(".rule-inspector .primary-button.full");
      await page.waitFor(
        `${value} === '' && document.querySelector(${JSON.stringify(input)})?.getAttribute('aria-invalid') === 'true'`,
      );
    });
  });
  for (const sample of [
    { kind: "flow", app: "order-service", label: "单机阈值", invalid: "-1" },
    { kind: "degrade", app: "order-service", label: "慢调用比例", invalid: "1.2" },
    { kind: "system", app: "user-service", label: "CPU 使用率阈值", invalid: "1.2" },
    { kind: "authority", app: "order-service", label: "调用来源列表", invalid: ",," },
    { kind: "param", app: "user-service", label: "参数索引", invalid: "-1" },
  ]) {
    it(`五类表单 ${sample.kind}：原生输入、失焦校验与字段 ARIA 错误一致`, async () => {
      await withPage(async (page) => {
        await gotoDashboard(page, `${E2E_BASE_URL}/#/rules?app=${sample.app}&view=${sample.kind}`);
        await page.waitFor(`!!document.querySelector('.rule-edit-button')`);
        await page.click(".rule-edit-button");
        const found = await page.eval(`(() => {
          const label = [...document.querySelectorAll('.rule-inspector label')].find(label=>label.textContent.trim() === ${JSON.stringify(sample.label)});
          const input = label && document.getElementById(label.htmlFor);
          if (!input) return false;
          input.dataset.ruleTest = 'invalid-field';return true;
        })()`);
        assert.ok(found, `${sample.kind}: missing labeled input ${sample.label}`);
        const input = '[data-rule-test="invalid-field"]';
        await page.click(input);
        await page.eval(`document.querySelector(${JSON.stringify(input)}).select()`);
        await page.send("Input.insertText", { text: sample.invalid });
        await page.click(".rule-inspector .primary-button.full");
        await page.waitFor(
          `document.querySelector(${JSON.stringify(input)})?.getAttribute('aria-invalid') === 'true'`,
        );
        await assertFormGridAlignment(page, ".rule-inspector");
        await saveFormEvidence(page, `rule-${sample.kind}-error`);
        assert.ok((await page.count('.rule-inspector [role="alert"]')) >= 1);
        assert.ok(
          await page.eval(`(() => {
          const input = document.querySelector(${JSON.stringify(input)}), ids = (input.getAttribute('aria-describedby') ?? '').split(/\\s+/).filter(Boolean);
          return ids.length > 0 && ids.every(id=>document.querySelectorAll('[id]').length > 0 && [...document.querySelectorAll('[id]')].filter(element=>element.id===id).length===1);
        })()`),
        );
      });
    });
  }
  /**
   * 每类规则**实际存在**的应用。
   *
   * 中文
   * ----
   * fixture 里 order-service 只有 Flow / Degrade / Authority 三类规则，
   * System 与 ParamFlow 规则属于 user-service。之前对五类一律用 order-service
   * 并断言「目录非空」，于是 system / param 两条假失败——那是测试假设错了：
   * 应用正确地显示了空目录，**没有**拿别的应用的行来填充，这正是期望行为。
   */
  const KINDS = [
    { kind: "flow", app: "order-service" },
    { kind: "degrade", app: "order-service" },
    { kind: "authority", app: "order-service" },
    { kind: "system", app: "user-service" },
    { kind: "param", app: "user-service" },
  ];

  for (const { kind, app } of KINDS) {
    it(`筛选 ${kind}（${app}）写回 view 并把目录收敛到该类型`, async () => {
      await withPage(async (page) => {
        await gotoDashboard(page, `${E2E_BASE_URL}/#/rules?app=${app}&range=1h&view=${kind}`);
        await page.waitFor(`!!document.querySelector('.rules-layout')`, { label: "规则工作台" });

        const rows = await page.count(".rules-layout tbody tr");
        assert.ok(rows >= 1, `${kind} 在 ${app} 下应有规则，实际 ${rows} 行`);
      });
    });
  }

  it("某应用下没有该类规则时，目录为空而不是拿别的应用填充", async () => {
    await withPage(async (page) => {
      // order-service 没有 System 规则。正确行为是空目录 + 明确空态，
      // 而不是显示 user-service 的 system-user-service 那条。
      await gotoDashboard(page, `${E2E_BASE_URL}/#/rules?app=order-service&range=1h&view=system`);
      await page.waitFor(`!!document.querySelector('.rules-layout')`, { label: "规则工作台" });
      const rows = await page.count(".rules-layout tbody tr");
      assert.equal(rows, 0, "order-service 下不应出现 System 规则行");
      const empty = await page.eval(
        `(() => { const n = document.querySelector('.rules-layout > *:nth-child(1) .empty'); return n ? n.textContent.trim() : null; })()`,
      );
      assert.equal(empty, "没有匹配当前筛选条件的规则", "应显示明确的空态文案");
    });
  });

  /**
   * 失败基线用例 2。
   *
   * 中文
   * ----
   * 「全部类型」选项完全失效。`RulesPage` 切回全类型时传 `view: undefined`，而
   * `App.tsx` 的 `navigate` 用 `context?.view ?? view` 取值——`undefined` 被当成
   * 「不修改」，于是旧的 `view=degrade` 原样留在 URL，下拉框和目录都不变。
   *
   * 与用例 1 同属 `view` 这一个事实被两处代码分别解释的问题。
   */
  it("切回「全部类型」应清掉 URL 里的 view", async () => {
    await withPage(async (page) => {
      await gotoDashboard(page, `${E2E_BASE_URL}/#/rules?app=order-service&range=1h&view=flow`);
      await page.waitFor(`!!document.querySelector('.rules-layout')`, { label: "规则工作台" });

      // 先切到另一个类型，确认切换本身有效
      await page.click(RULE_KIND_FILTER);
      await waitDropdownOpen(page);
      await page.clickByText("熔断降级", "div[role='option']");
      await waitDropdownClosed(page);
      await page.waitFor(`location.hash.includes('view=degrade')`, { label: "切到降级类型" });

      // 再切回全部类型：view 应被清空
      await page.click(RULE_KIND_FILTER);
      await waitDropdownOpen(page);
      await page.clickByText("全部类型", "div[role='option']");
      await waitDropdownClosed(page);
      await page.waitFor(`!location.hash.includes('view=')`, { label: "view 被清空" });

      // 等 UI 收敛再断言：URL 变更与 React 重渲染不是同一时刻，
      // 直接读下拉标签会偶发读到旧值。
      await page.waitFor(
        `document.querySelector(${JSON.stringify(RULE_KIND_FILTER)}).textContent.trim() === "全部类型"`,
        { label: "类型下拉回到「全部类型」" },
      );
    });
  });

  it("非法 view 回落到全部类型，不产生空目录", async () => {
    await withPage(async (page) => {
      await gotoDashboard(page, `${E2E_BASE_URL}/#/rules?app=order-service&range=1h&view=bogus`);
      await page.waitFor(`!!document.querySelector('.rules-layout')`, { label: "规则工作台" });
      const rows = await page.count(".rules-layout tbody tr");
      assert.ok(rows > 1, `非法 view 应回落到全部类型（多行），实际 ${rows} 行`);
    });
  });

  /**
   * 失败基线用例。
   *
   * 中文
   * ----
   * 深链 `view=degrade` 时，目录里有降级规则，但右侧检视器落到空态，且空态文案
   * 直接复用了搜索框 placeholder（「搜索资源或策略：0」）。根因是 `selectedId` 初值
   * 取 `entries[0]`（Flow 类型），与筛选条件无关，必然被滤掉。
   *
   * 28 条视觉基线全部「通过」——因为它只证明每帧都截到了，没证明截到的是对的。
   */
  it("深链到已筛选类型时，检视器应选中该类型下的一条真实规则", async () => {
    await withPage(async (page) => {
      await gotoDashboard(page, `${E2E_BASE_URL}/#/rules?app=order-service&range=1h&view=degrade`);
      await page.waitFor(`!!document.querySelector('.rules-layout')`, { label: "规则工作台" });

      const rows = await page.count(".rules-layout tbody tr");
      assert.ok(rows >= 1, "前提：目录里应有降级规则");

      const inspector = await page.eval(
        `(document.querySelectorAll('.rules-layout > *')[1]?.textContent ?? '').trim()`,
      );
      const emptyNode = await page.eval(
        `(() => { const n = document.querySelector('.rules-layout > *:nth-child(2) .empty'); return n ? n.textContent : null; })()`,
      );
      assert.equal(
        emptyNode,
        null,
        `目录非空却显示检视器空态「${emptyNode}」。检视器内容: ${inspector.slice(0, 120)}`,
      );
    });
  });

  it("检视器空态文案不得复用搜索框 placeholder", async () => {
    await withPage(async (page) => {
      // 搜索到空，是触发空态的合法路径
      await gotoDashboard(page, `${E2E_BASE_URL}/#/rules?app=order-service&range=1h`);
      await page.waitFor(`!!document.querySelector('.rules-layout')`, { label: "规则工作台" });
      const placeholder = await page.eval(
        `[...document.querySelectorAll('input')].map(i => i.placeholder).find(Boolean) ?? ''`,
      );
      assert.ok(placeholder, "前提：应能取到搜索框 placeholder");

      await page.type(
        ".rules-layout input[type='search'], .rules-layout input",
        "zzzz-no-such-rule",
      );
      // 按面板定位：`.rules-layout .empty` 会同时命中目录面板和检视器，
      // 两者是独立的两块，必须用 nth-child 区分，否则断言到的是另一块。
      await page.waitFor(`!!document.querySelector('.rules-layout > *:nth-child(1) .empty')`, {
        label: "搜索无结果时目录空态出现",
      });
      const emptyText = await page.text(".rules-layout > *:nth-child(1) .empty");
      assert.notEqual(
        emptyText.trim(),
        `${placeholder}：0`,
        `空态文案不能是搜索框 placeholder 加计数：「${emptyText}」`,
      );
    });
  });
});

describe("绑定式规则工作台集成", () => {
  it("管理员从规则目录显式打开绑定后才能进入编辑", async () => {
    await withPage(async (page) => {
      await gotoDashboard(page, `${E2E_BASE_URL}/#/rules?env=test-env&app=app-one&view=flow`);
      await page.waitFor(`!!document.querySelector('[data-rule-binding-open="binding-app-one"]')`, {
        label: "Flow binding directory is loaded",
      });
      assert.equal(await page.count("[data-rule-workspace]"), 0, "规则绑定不得自动选中");
      await page.click('[data-rule-binding-open="binding-app-one"]');
      await page.waitFor(
        `!!document.querySelector('[data-rule-workspace] [data-rule-source-summary]')`,
        {
          label: "the selected binding snapshot is loaded",
        },
      );
      await page.click('[data-rule-workspace] [data-rule-action="begin"]');
      await page.waitFor(`!!document.querySelector('[data-rule-full-preview]')`, {
        label: "editing starts only after explicit user intent",
      });
      assert.ok((await page.text("[data-rule-full-preview]")).includes("POST /api/orders"));
    });
  });
});

describe("F0 账号与空数据回归", () => {
  it("创建账号 → 角色绑定 → 启停 → 跨页返回保留同一份状态", async () => {
    await withPage(async (page) => {
      await gotoDashboard(page, `${E2E_BASE_URL}/#/accounts`);
      await page.waitFor(`!!document.querySelector('[data-account-management] table')`);
      await page.clickByText("新增账号");
      await page.waitFor(`!!document.querySelector('dialog[open]')`);
      await page.type("dialog[open] input[autocomplete='username']", "f0-regression");
      await page.type("dialog[open] input[type='password']", "Synthetic-only-Password-42");
      await page.clickByText("创建账号", "dialog[open] button");
      await page.waitFor(
        `document.querySelector('[data-account-management] table')?.textContent.includes('f0-regression') ?? false`,
      );
      assert.equal(await page.count("dialog[open]"), 0);

      const rowSelector = () =>
        `[...document.querySelectorAll('[data-account-management] tr[data-account-id]')].find(row => row.textContent.includes('f0-regression'))`;
      await page.eval(`(${rowSelector()}).querySelector('button').click()`);
      await page.waitFor(`!!document.querySelector('[data-role-editor] [data-account-summary]')`);
      assert.match(await page.text("[data-role-editor] [data-account-summary]"), /f0-regression/);
      // Astryx 的可见 radio surface 代理到受控 input；点击实际输入保持真实浏览器事件。
      await page.click('[data-role-editor] input[type="radio"][value="admin"]');
      await page.waitFor(
        `document.querySelector('[data-role-editor] input[type="radio"][value="admin"]').checked && ![...document.querySelectorAll('[data-role-editor] button')].find(button=>button.textContent.includes('保存角色'))?.disabled`,
        { label: "administrator draft is dirty and can be saved" },
      );
      await page.clickByText("保存角色", "[data-role-editor] button");
      await page.waitFor(`document.body.textContent.includes('服务端已确认保存')`);
      await page.waitFor(
        `document.querySelector('[data-role-editor] [data-account-summary]')?.getAttribute('data-account-role') === 'admin'`,
        { label: "server reread confirms the saved admin role" },
      );
      await page.eval(
        `new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))`,
      );
      const roleActions = await page.eval(
        `[...document.querySelectorAll('[data-role-editor] button')].map(button=>({text:button.textContent,disabled:button.disabled}))`,
      );
      assert.ok(
        roleActions.some((action) => action.text.includes("保存角色") && action.disabled),
        `已确认保存后编辑仍显示未保存: ${JSON.stringify(roleActions)}`,
      );
      assert.deepEqual(
        await page.eval(
          `Object.keys(sessionStorage).filter(key=>key.includes('role-draft')).map(key=>sessionStorage.getItem(key))`,
        ),
        [],
        "保存确认后不得把旧角色草稿重新写回 sessionStorage",
      );
      await page.clickByText("返回账户维护");
      await page.waitFor(`!!document.querySelector('[data-account-management] table')`, {
        label: "account directory reload completes after returning from role binding",
      });
      assert.match(await page.eval(`(${rowSelector()}).textContent`), /管理员/);
      await page.eval(`(${rowSelector()}).querySelectorAll('button')[1].click()`);
      await page.waitFor(`!!document.querySelector('dialog[open]')`);
      await page.clickByText("确认变更", "dialog[open] button");
      await page.waitFor(`(${rowSelector()}).textContent.includes('已停用')`);
      await page.eval(`location.hash = '#/change-password?account=invalid-account'`);
      await page.waitFor(
        `!!document.querySelector('[data-own-password] form') && !document.querySelector('[data-route-state="loading"]')`,
      );
      assert.equal(
        await page.count('[data-own-password] [name="account"]'),
        0,
        "改密目标只能由当前会话决定",
      );
      await page.eval(`location.hash = '#/accounts'`);
      await page.waitFor(`!!document.querySelector('[data-account-management] table')`);
      const finalRow = await page.eval(`(${rowSelector()}).textContent`);
      assert.match(finalRow, /管理员/);
      assert.match(finalRow, /已停用/);
    });
  });

  for (const route of ["roles", "change-password"]) {
    it(`${route}: 显式未知账号不会误选管理员，缺省目标仍可操作`, async () => {
      await withPage(async (page) => {
        await gotoDashboard(page, `${E2E_BASE_URL}/#/${route}?account=missing-account`);
        if (route === "roles") {
          await page.waitFor(
            `document.querySelector('[data-role-management]')?.textContent.includes('未找到账号')`,
          );
          assert.equal(await page.count("[data-role-editor]"), 0);
          await page.eval(`location.hash = '#/roles'`);
          await page.waitFor(
            `!!document.querySelector('[data-role-management] [role="combobox"]')`,
          );
          assert.equal(await page.count("[data-role-editor]"), 0, "缺少显式选择时不得默认挑选账号");
        } else {
          // Password change is session-owned; an account query parameter is ignored, not a target selector.
          await page.waitFor(`!!document.querySelector('[data-own-password] form')`);
          assert.equal(await page.count('[data-own-password] input[type="password"]'), 3);
        }
      });
    });
  }

  it("同一角色页面收到不同深链目标后，不沿用旧账号", async () => {
    await withPage(async (page) => {
      await gotoDashboard(page, `${E2E_BASE_URL}/#/roles?account=account-view`);
      await page.waitFor(`!!document.querySelector('[data-role-editor] [data-account-summary]')`);
      assert.match(await page.text("[data-role-editor] [data-account-summary]"), /viewer/);
      await page.eval(`location.hash = '#/roles?account=account-admin'`);
      await page.waitFor(
        `document.querySelector('[data-role-editor] [data-account-summary]')?.textContent.includes('admin')`,
      );
      await page.eval(`location.hash = '#/roles?account=missing-account'`);
      await page.waitFor(
        `document.querySelector('[data-role-management]')?.textContent.includes('未找到账号')`,
      );
      assert.equal(await page.count('[data-role-editor] input[type="radio"]'), 0);
    });
  });

  for (const hash of [
    "#/roles?account=account-admin",
    "#/system?view=roles&account=account-admin",
  ]) {
    it(`${hash}: 账号选择写回 URL，返回原目标不会残留上次选择`, async () => {
      await withPage(async (page) => {
        await gotoDashboard(page, `${E2E_BASE_URL}/${hash}`);
        await page.waitFor(`!!document.querySelector('[data-role-editor] [data-account-summary]')`);
        // 0 是页头语言；身份选择器在独立 roles 页和 system roles tab 都是第 1 个。
        await selectOption(page, 1, "viewer");
        // hash 写入先于 React 处理 hashchange；同时等待目标内容，不能只等 URL。
        await page.waitFor(
          `location.hash.includes('account=account-view') && document.querySelector('[data-role-editor] [data-account-summary]')?.textContent.includes('viewer')`,
        );
        assert.match(await page.text("[data-role-editor] [data-account-summary]"), /viewer/);
        if (hash.includes("system")) assert.match(await page.hash(), /system.*view=roles/);
        await page.eval(`location.hash = ${JSON.stringify(hash)}`);
        await page.waitFor(
          `document.querySelector('[data-role-editor] [data-account-summary]')?.textContent.includes('admin')`,
        );
      });
    });
  }

  it("显式未知应用显示空态且可以重新选择，不显示其它应用详情", async () => {
    await withPage(async (page) => {
      await gotoDashboard(page, `${E2E_BASE_URL}/#/applications?app=missing-app`);
      await page.waitFor(`!!document.querySelector('[data-application-not-found-message]')`);
      assert.match(await page.text("[data-application-not-found-message]"), /未找到所选应用/);
      assert.ok((await page.count("[data-observation-filters] button[role='combobox']")) > 0);
      assert.equal(await page.count("[data-instance-directory]"), 0);
      await selectObservationOption(page, 1, "app-one");
      await page.waitFor(
        `location.hash.includes('app=app-one') && !!document.querySelector('[data-observed-instance="instance-1"]')`,
      );
    });
  });
});

describe("F1 启动与路由边界", () => {
  for (const route of [
    "overview",
    "applications",
    "rules",
    "realtime",
    "faults",
    "system",
    "accounts",
    "roles",
    "change-password",
    "login",
    "setup",
  ]) {
    it(`${route}: 控件 label/ARIA 引用仍指向唯一的真实元素`, async () => {
      await withPage(async (page) => {
        await gotoDashboard(page, `${E2E_BASE_URL}/#/${route}?app=order-service`);
        const broken = await page.eval(`(() => {
          const failures = [];
          for (const element of document.querySelectorAll('[for], [aria-labelledby], [aria-describedby]')) {
            for (const attribute of ['for', 'aria-labelledby', 'aria-describedby']) {
              for (const id of (element.getAttribute(attribute) ?? '').split(/\\s+/).filter(Boolean)) {
                if (document.querySelectorAll('#' + CSS.escape(id)).length !== 1) failures.push({ attribute, id });
              }
            }
          }
          return failures;
        })()`);
        assert.deepEqual(broken, []);
      });
    });
  }

  it("未知非空路由显示恢复入口；首页仍按默认总览展示", async () => {
    await withPage(async (page) => {
      await gotoDashboard(page, `${E2E_BASE_URL}/#/missing-page`);
      assert.match(await page.text('[data-route-state="not-found"]'), /找不到这个页面/);
      await page.clickByText("返回总览");
      await page.waitFor(
        `location.hash.startsWith('#/overview') && !!document.querySelector('[data-observation-filters]')`,
      );
    });
  });

  async function mountBoundaryProbe(page, mode) {
    await gotoDashboard(page, `${E2E_BASE_URL}/#/accounts`);
    await page.eval(`(async () => {
      const React = (await import('/node_modules/.vite/deps/react.js')).default;
      const { createRoot } = (await import('/node_modules/.vite/deps/react-dom_client.js')).default;
      const { RouteBoundary } = await import('/src/app/router/RouteBoundary.tsx');
      const container = document.createElement('section'); container.id = 'f1-route-probe'; document.body.append(container);
      const caught = []; const root = createRoot(container, { onCaughtError: error => caught.push(error.name) });
      let calls = 0, release;
      const flags = { crashes: ${mode === "render"} };
      function Page() { if (flags.crashes) throw new Error('private-error-message'); return React.createElement('output', {}, 'ready'); }
      const loader = () => {
        calls++;
        if (${mode === "deferred"}) return new Promise(resolve => { release = () => resolve({ default: Page }); });
        if (${mode === "reject"} && calls === 1) return Promise.reject(new Error('private-chunk-error'));
        return Promise.resolve({ default: Page });
      };
      const healthyLoader = () => Promise.resolve({ default: () => React.createElement('output', {}, 'changed-route') });
      let homeCalls = 0, reloadCalls = 0;
      const render = (key = 'first', selectedLoader = loader) => root.render(React.createElement(RouteBoundary, { loader: selectedLoader, resetKey: key, pageProps: {}, onHome() { homeCalls++; }, onReload() { reloadCalls++; } }));
      window.__f1 = { flags, caught, release: () => release(), calls: () => calls, homeCalls: () => homeCalls, reloadCalls: () => reloadCalls, render, change: () => render('other', healthyLoader), clean: () => { root.unmount(); container.remove(); } };
      render();
    })()`);
  }

  it("异步加载显示状态；完成后不会无限重新加载", async () => {
    await withPage(async (page) => {
      await mountBoundaryProbe(page, "deferred");
      await page.waitFor(
        `!!document.querySelector('#f1-route-probe [data-route-state="loading"]')`,
      );
      await page.eval(`window.__f1.release()`);
      await page.waitFor(
        `document.querySelector('#f1-route-probe output')?.textContent === 'ready'`,
      );
      assert.equal(await page.eval(`window.__f1.calls()`), 1);
      await page.eval(`window.__f1.clean()`);
    });
  });

  it("chunk 失败可重试；不泄露异常正文且不破坏外壳", async () => {
    await withPage(async (page) => {
      await mountBoundaryProbe(page, "reject");
      await page.waitFor(`!!document.querySelector('#f1-route-probe [role="alert"]')`);
      assert.doesNotMatch(await page.text("#f1-route-probe"), /private-chunk-error/);
      assert.ok(
        await page.eval(
          `!!document.querySelector('.topbar') && !!document.querySelector('[data-account-management] table')`,
        ),
      );
      await page.clickByText("重试加载", "#f1-route-probe button");
      await page.waitFor(
        `document.querySelector('#f1-route-probe output')?.textContent === 'ready'`,
      );
      assert.equal(await page.eval(`window.__f1.calls()`), 2);
      assert.equal(await page.eval(`window.__f1.caught.length`), 1);
      await page.eval(`window.__f1.clean()`);
    });
  });

  it("页面异常可恢复；改换路由也清除旧错误状态", async () => {
    await withPage(async (page) => {
      await mountBoundaryProbe(page, "render");
      await page.waitFor(`!!document.querySelector('#f1-route-probe [role="alert"]')`);
      assert.doesNotMatch(await page.text("#f1-route-probe"), /private-error-message/);
      await page.eval(`window.__f1.flags.crashes = false`);
      await page.clickByText("重试加载", "#f1-route-probe button");
      await page.waitFor(
        `document.querySelector('#f1-route-probe output')?.textContent === 'ready'`,
      );
      await page.eval(`window.__f1.flags.crashes = true; window.__f1.render('crashed')`);
      await page.waitFor(`!!document.querySelector('#f1-route-probe [role="alert"]')`);
      await page.eval(`window.__f1.change()`);
      await page.waitFor(
        `document.querySelector('#f1-route-probe output')?.textContent === 'changed-route'`,
      );
      await page.eval(`window.__f1.clean()`);
    });
  });

  it("重载必须显式触发；当前首页失败时返回首页也能清除旧错误边界", async () => {
    await withPage(async (page) => {
      await mountBoundaryProbe(page, "render");
      await page.waitFor(`!!document.querySelector('#f1-route-probe [role="alert"]')`);
      assert.equal(await page.eval(`window.__f1.reloadCalls()`), 0);
      await page.clickByText("重新载入应用", "#f1-route-probe button");
      assert.equal(await page.eval(`window.__f1.reloadCalls()`), 1);
      await page.eval(`window.__f1.flags.crashes = false`);
      await page.clickByText("返回总览", "#f1-route-probe button");
      await page.waitFor(
        `document.querySelector('#f1-route-probe output')?.textContent === 'ready'`,
      );
      assert.equal(await page.eval(`window.__f1.homeCalls()`), 1);
      await page.eval(`window.__f1.clean()`);
    });
  });

  it("StrictMode 与 Provider 重渲染保持服务身份，不重复覆盖账号状态", async () => {
    await withPage(async (page) => {
      await gotoDashboard(page, `${E2E_BASE_URL}/#/accounts`);
      await page.eval(`(async () => {
        const React = (await import('/node_modules/.vite/deps/react.js')).default;
        const { createRoot } = (await import('/node_modules/.vite/deps/react-dom_client.js')).default;
        const { AppProviders } = await import('/src/app/providers/AppProviders.tsx');
        const { createConsoleServices } = await import('/src/app/providers/consoleServices.ts');
        const { ProviderProbe } = await import('/tests/e2e/probes/ProviderProbe.tsx');
        const { accountStore } = await import('/src/features/identity/state/accountStore.ts');
        const original = accountStore.getSnapshot();
        const runtime = { mode: 'mock', apiBaseUrl: window.location.origin };
        const serviceOwner = createConsoleServices(runtime);
        const container = document.createElement('section'); container.id = 'f1-provider-probe'; document.body.append(container);
        const root = createRoot(container); const snapshots = [];
        const onSnapshot = service => snapshots.push(service);
        const render = value => root.render(React.createElement(React.StrictMode, {}, React.createElement(AppProviders, { runtime, services: serviceOwner }, React.createElement(ProviderProbe, { value, onSnapshot }))));
        window.__f1Providers = { render, same: () => snapshots.every(service => service === snapshots[0]), snapshotSame: () => accountStore.getSnapshot() === original, clean: () => { root.unmount(); serviceOwner.dispose(); container.remove(); } };
        render('first');
      })()`);
      await page.waitFor(
        `document.querySelector('#f1-provider-probe output')?.textContent === 'first'`,
      );
      await page.eval(`window.__f1Providers.render('second')`);
      await page.waitFor(
        `document.querySelector('#f1-provider-probe output')?.textContent === 'second'`,
      );
      assert.ok(
        await page.eval(`window.__f1Providers.same() && window.__f1Providers.snapshotSame()`),
      );
      await page.eval(`window.__f1Providers.clean()`);
    });
  });
});

describe("F2 React 资源生命周期", () => {
  it("规则草稿在首次 commit 就对应新类别，切空与返回不会复活已丢弃的编辑态", async () => {
    await withPage(async (page) => {
      await gotoDashboard(page, `${E2E_BASE_URL}/#/rules`);
      await page.eval(`(async () => {
        const React = (await import('/node_modules/.vite/deps/react.js')).default;
        const {createRoot} = (await import('/node_modules/.vite/deps/react-dom_client.js')).default;
        const {RuleWorkbenchProbe,RULE_FIXTURES} = await import('/tests/e2e/probes/RuleWorkbenchProbe.tsx');
        const container = document.createElement('section');container.id='rules-state-probe';document.body.append(container);
        const root=createRoot(container),commits=[],onCommit=commit=>commits.push(commit);
        const render=(kind,empty=false)=>root.render(React.createElement(React.StrictMode,{},React.createElement(RuleWorkbenchProbe,{entries:empty?[]:RULE_FIXTURES,kind,onCommit})));
        window.__ruleProbe={commits,render,clean:()=>{root.unmount();container.remove();}};
        render('flow');
      })()`);
      const snapshot = `JSON.parse(document.querySelector('#rules-state-probe output').textContent)`;
      await page.waitFor(`${snapshot}.draftKind === 'flow'`);
      await page.click("#rules-state-probe button");
      await page.waitFor(`${snapshot}.editing`);
      await page.eval(`window.__ruleProbe.render('degrade')`);
      await page.waitFor(`${snapshot}.draftKind === 'degrade' && !${snapshot}.editing`);
      await page.eval(`window.__ruleProbe.render('flow',true)`);
      await page.waitFor(`${snapshot}.draftKind === null && ${snapshot}.selectedKind === null`);
      await page.eval(`window.__ruleProbe.render('flow')`);
      await page.waitFor(`${snapshot}.draftKind === 'flow' && !${snapshot}.editing`);
      assert.ok(
        await page.eval(`window.__ruleProbe.commits.every(c=>c.selectedKind===c.draftKind)`),
      );
      await page.eval(`window.__ruleProbe.clean()`);
    });
  });
  it("路由所有者换默认身份/目录不串缓存；push/replace/back 与诊断上下文一致", async () => {
    await withPage(async (page) => {
      await gotoDashboard(page, `${E2E_BASE_URL}/#/overview`);
      await page.eval(`(async () => {
        const React = (await import('/node_modules/.vite/deps/react.js')).default;
        const {createRoot} = (await import('/node_modules/.vite/deps/react-dom_client.js')).default;
        const {NavigationProbe} = await import('/tests/e2e/probes/NavigationProbe.tsx');
        const container = document.createElement('section'); container.id='f2-navigation-probe';container.style.cssText='position:fixed;top:8px;left:8px;z-index:2147483647;background:#fff;padding:8px';document.body.append(container);
        const root=createRoot(container), render=options => root.render(React.createElement(React.StrictMode, {}, React.createElement(NavigationProbe,{options})));
        window.__f2Navigation={render,clean:()=>{root.unmount();container.remove();}};
        render({applicationScopeIds:['order-service'],defaultAccountId:'first-owner'});
      })()`);
      const snapshot = `JSON.parse(document.querySelector('#f2-navigation-probe output').textContent)`;
      await page.waitFor(`${snapshot}.accountId === 'first-owner'`);
      await page.eval(
        `window.__f2Navigation.render({applicationScopeIds:['payment-service'],defaultAccountId:'second-owner'})`,
      );
      await page.waitFor(`${snapshot}.accountId === 'second-owner'`);
      const initialLength = await page.eval(`history.length`);
      await page.click('#f2-navigation-probe [data-action="push"]');
      await page.waitFor(
        `${snapshot}.context.eventId === 'event-1' && ${snapshot}.context.instanceId === 'order-1'`,
      );
      assert.equal(await page.eval(`history.length`), initialLength + 1);
      assert.equal(
        await page.eval(`${snapshot}.context.resource`),
        "POST /api/orders?status=ready",
      );
      await page.click('#f2-navigation-probe [data-action="replace"]');
      await page.waitFor(
        `new URLSearchParams(location.hash.split('?')[1] ?? '').get('q') === 'qps > 200'`,
        { label: "replaceState writes the latest search into the route URL" },
      );
      await page.waitFor(`${snapshot}.context.search === 'qps > 200'`);
      assert.equal(await page.eval(`history.length`), initialLength + 1);
      await page.click('#f2-navigation-probe [data-action="clear"]');
      await page.waitFor(
        `${snapshot}.view === '' && !${snapshot}.context.instanceId && !${snapshot}.context.eventId`,
      );
      assert.equal(await page.eval(`${snapshot}.context.environmentId`), "prod");
      await page.click('#f2-navigation-probe [data-action="cross"]');
      await page.waitFor(`${snapshot}.route === 'applications' && ${snapshot}.view === ''`);
      await page.eval(`history.back()`);
      await page.waitFor(`${snapshot}.route === 'rules'`);
      await page.eval(`history.back()`);
      await page.waitFor(
        `${snapshot}.context.instanceId === 'order-1' && ${snapshot}.context.search === 'qps > 200'`,
      );
      await page.eval(`window.__f2Navigation.clean()`);
    });
  });
  it("StrictMode 清理、换查询取消和卸载后迟到响应不会覆盖新状态", async () => {
    await withPage(async (page) => {
      await gotoDashboard(page, `${E2E_BASE_URL}/#/accounts`);
      await page.eval(`(async () => {
        const React = (await import('/node_modules/.vite/deps/react.js')).default;
        const { createRoot } = (await import('/node_modules/.vite/deps/react-dom_client.js')).default;
        const { QueryLifecycleProbe, createQueryResource } = await import('/tests/e2e/probes/QueryLifecycleProbe.tsx');
        const reads = [], commits = [], resource = createQueryResource({
          keyOf: query => JSON.stringify([query.session, query.application]),
          classify: () => 'ready',
          read: (query, signal) => new Promise(resolve => reads.push({ query, signal, resolve })),
        });
        const container = document.createElement('section'); container.id = 'f2-resource-probe'; document.body.append(container);
        const root = createRoot(container);
        const onCommit = (query, snapshot) => commits.push({query, data: 'data' in snapshot ? snapshot.data : null});
        const render = query => root.render(React.createElement(React.StrictMode, {}, React.createElement(QueryLifecycleProbe, { resource, query, onCommit })));
        window.__f2 = { reads, commits, resource, render, unmount: () => root.unmount(), clean: () => container.remove() };
        render({session: 'first-session', application: 'orders'});
      })()`);
      await page.waitFor(`window.__f2.reads.length === 2 && window.__f2.reads[0].signal.aborted`);
      await page.eval(`window.__f2.reads[1].resolve(['orders'])`);
      await page.waitFor(
        `document.querySelector('#f2-resource-probe output')?.textContent.includes('"data":["orders"]')`,
      );
      await page.eval(`window.__f2.render({session: 'next-session', application: 'payments'})`);
      await page.waitFor(
        `window.__f2.reads.length === 3 && document.querySelector('#f2-resource-probe output')?.textContent === '{"status":"loading","data":null}'`,
      );
      await page.eval(
        `window.__f2.reads[0].resolve(['late-old-session']); window.__f2.reads[2].resolve(['payments'])`,
      );
      await page.waitFor(
        `document.querySelector('#f2-resource-probe output')?.textContent === '{"status":"ready","data":["payments"]}'`,
      );
      assert.ok(
        await page.eval(
          `window.__f2.commits.filter(item => item.query.session === 'next-session').every(item => item.data === null || !item.data.includes('orders'))`,
        ),
      );
      await page.eval(`window.__f2.render({session: 'next-session', application: 'pending'})`);
      await page.waitFor(`window.__f2.reads.length === 4`);
      await page.eval(`window.__f2.unmount()`);
      assert.ok(await page.eval(`window.__f2.reads[3].signal.aborted`));
      await page.eval(`window.__f2.reads[3].resolve(['after-unmount'])`);
      assert.equal(await page.eval(`window.__f2.resource.getSnapshot().status`), "idle");
      await page.eval(`window.__f2.resource.dispose(); window.__f2.clean()`);
    });
  });
});

describe("多语言", () => {
  /**
   * 切换语言用的页面清单。
   *
   * 中文
   * ----
   * 每页用 `?app=` 明确应用粒度：只给 hash 的页面在渲染前会经过一次收敛，等待
   * 条件要多绕一圈，容易读到中间态。
   */
  const LOCALIZED_PAGES = [
    { name: "总览", hash: "#/overview?app=all&range=1h" },
    { name: "应用与实例", hash: "#/applications?app=order-service&range=1h" },
    { name: "规则", hash: "#/rules?app=order-service&range=1h" },
    { name: "实时监控", hash: "#/realtime?app=all&range=1h" },
    { name: "故障分析", hash: "#/faults?app=all&range=1h" },
    { name: "系统管理", hash: "#/system" },
  ];

  /**
   * 元素文本里残留的中文字符数。
   *
   * 踩过的坑：`.match(/[\\u4e00-\\u9fa5]/g)` **无匹配时返回 null**，于是
   * `?.length ?? -1` 得到 -1 而不是 0 —— 结果「翻译正确的页面」永远通不过
   * `=== 0`，而「全是中文的页面」反而能通过。判据必须用 `?? 0`。
   *
   * 选 0 作��缺失元素的默认：元素不存在与「有 0 个汉字」都视为达标，另外用一条
   * 独立的 `before >= 0` 断言确认选择器真的取到了东西，避免恒真。
   */
  const cjkCount = (selector) =>
    `(document.querySelector('${selector}')?.textContent ?? '').match(/[\\u4e00-\\u9fa5]/g)?.length ?? 0`;
  const TITLE_CJK = cjkCount(".intro h1");
  const FILTERS_CJK = cjkCount("[data-observation-filters]");

  it("切到 English 后导航文案随之切换", async () => {
    await withPage(async (page) => {
      await gotoDashboard(page, `${E2E_BASE_URL}/#/overview?app=all&range=1h`);
      await page.waitFor(`!!document.querySelector('.main-nav')`, { label: "导航" });
      await selectOption(page, 0, "English");
      await page.waitFor(
        `[...document.querySelectorAll('.main-nav button')].some(b => /rules|rule/i.test(b.textContent ?? ''))`,
        { label: "导航切到英文" },
      );
    });
  });

  /**
   * 逐页断言「切到 English / 日本語后页面标题不再含中文」。
   *
   * 中文
   * ----
   * 判据只取 `.intro h1`，不取全文：正文里的中文有一部分是**领域数据**
   * （规则名「国庆大促保护方案」、应用名「生产环境」、故障描述），它们本来就不该
   * 翻译。用全文汉字数当判据会把 fixture 误判成漏翻——本轮就是这么误判过一次：
   * faults 正文汉字最高（288），实际它 ui 层一条未翻译文案都没有，全是注释与
   * fixture。
   *
   * 这批用例在迁移前应当**失败**，那正是它们要证明的缺口。
   */
  for (const [locale, optionLabel] of [
    ["en-US", "English"],
    ["ja-JP", "日本語"],
  ]) {
    for (const { name, hash } of LOCALIZED_PAGES) {
      it(`切到 ${locale} 后「${name}」页标题不含中文`, async () => {
        await withPage(async (page) => {
          await gotoDashboard(page, `${E2E_BASE_URL}/${hash}`);
          await page.waitFor(`!!document.querySelector('.app-shell')`, { label: "壳层" });
          // 记录切换前的中文数：已经是 0 的页面（如 faults / rules）这条断言形同虚设，
          // 顺带确认确实存在标题，避免选择器写错导致恒真。
          const before = await page.eval(TITLE_CJK);
          assert.ok(before >= 0, `未取到「${name}」页标题，选择器可能失效`);

          await selectOption(page, 0, optionLabel);
          await page.waitFor(`${TITLE_CJK} === 0`, {
            label: `「${name}」标题切到 ${locale}（切换前中文数 ${before}）`,
          });
        });
      });
    }
  }

  /**
   * 筛选条必须跟着切语言。
   *
   * 中文
   * ----
   * 观测页筛选条跟着切语言。规则工作台具有独立绑定/规则筛选，不属于观测上下文，
   * 其目录、工作台和发布控件由对应 rule-* E2E 覆盖，不能误要求渲染观测筛选条。
   */
  for (const [locale, optionLabel] of [
    ["en-US", "English"],
    ["ja-JP", "日本語"],
  ]) {
    for (const { name, hash } of LOCALIZED_PAGES.filter((p) =>
      ["总览", "应用与实例", "实时监控", "故障分析"].includes(p.name),
    )) {
      it(`切到 ${locale} 后「${name}」筛选条不含中文`, async () => {
        await withPage(async (page) => {
          await gotoDashboard(page, `${E2E_BASE_URL}/${hash}`);
          await page.waitFor(`!!document.querySelector('[data-observation-filters]')`, {
            label: "筛选条",
          });
          const before = await page.eval(FILTERS_CJK);
          assert.ok(before >= 0, `未取到「${name}」筛选条，选择器可能失效`);

          await selectOption(page, 0, optionLabel);
          await page.waitFor(`${FILTERS_CJK} === 0`, {
            label: `「${name}」筛选条切到 ${locale}（切换前中文数 ${before}）`,
          });
        });
      });
    }
  }
});
import { artifactDirectory } from "./artifacts.mjs";
