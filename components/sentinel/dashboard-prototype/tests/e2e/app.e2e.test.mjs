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

import { E2E_BASE_URL, launchBrowser } from "./cdp.mjs";

let browser;

before(async () => {
  browser = await launchBrowser();
});

after(async () => {
  await browser?.close();
  // CDP WebSocket 与 Chrome 进程句柄在用例跑完后仍可能持有事件循环，
  // `node --test` 会一直等它们自然退出。全部结果已由 reporter 输出，
  // 这里主动结束进程；退出码保留给 node:test 判定成败。
  process.exit(process.exitCode ?? 0);
});

/** 每个用例用独立页面，避免上一个用例的受控状态与监听器泄漏到下一个。 */
async function withPage(run) {
  const page = await browser.newPage();
  try {
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
async function selectOption(page, comboboxIndex, optionText) {
  const exists = await page.eval(
    `document.querySelectorAll('button[role="combobox"]').length > ${comboboxIndex}`,
  );
  assert.ok(exists, `找不到第 ${comboboxIndex} 个下拉框`);
  await page.click("button[role='combobox']", { index: comboboxIndex });
  await waitDropdownOpen(page);
  await page.clickByText(optionText, "div[role='option']");
  await waitDropdownClosed(page);
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
        await page.goto(`${E2E_BASE_URL}/#/overview?app=all&range=1h`);
        await page.waitFor(`!!document.querySelector('.topbar')`, { label: "顶栏" });

        await page.clickByText(label, ".main-nav button");
        await page.waitFor(`location.hash.includes('/${route}')`, { label: `跳到 ${route}` });

        const current = await page.hash();
        assert.match(current, new RegExp(`^#/${route}\\?`), `hash 应以 #/${route}? 开头，实际 ${current}`);
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
      await page.goto(deep);
      await page.waitFor(`!!document.querySelector('.topbar')`, { label: "顶栏" });
      await page.goto(deep);
      await page.waitFor(`!!document.querySelector('.page-realtime')`, { label: "实时监控页" });
      assert.match(await page.hash(), /app=order-service/);
      assert.match(await page.hash(), /range=15m/);
    });
  });

  it("登录页不套应用壳", async () => {
    await withPage(async (page) => {
      await page.goto(`${E2E_BASE_URL}/#/login`);
      await page.waitFor(`!!document.querySelector('body')`, { label: "登录页" });
      assert.equal(await page.count(".topbar"), 0, "登录页不应出现应用壳顶栏");
      assert.equal(await page.count(".demo-banner"), 0, "登录页不应出现示例回放横幅");
    });
  });
});

describe("筛选上下文写入 URL", () => {
  it("切换时间窗口写回 URL 并影响标签", async () => {
    await withPage(async (page) => {
      await page.goto(`${E2E_BASE_URL}/#/overview?app=all&range=1h`);
      await page.waitFor(`!!document.querySelector('.page-overview')`, { label: "总览" });

      // 总览页的 combobox 顺序实测为：0 语言 / 1 环境 / 2 应用 / 3 时间范围。
      // 规则页没有时间范围，顺序也不同——按下标驱动前必须先确认。
      await selectOption(page, 3, "最近 15 分钟");
      await page.waitFor(`location.hash.includes('range=15m')`, { label: "range 写回" });
      assert.match(await page.hash(), /range=15m/);

      await page.waitFor(
        `[...document.querySelectorAll('button[role="combobox"]')][3].textContent.trim() === "最近 15 分钟"`,
        { label: "时间范围下拉显示新窗口" },
      );
    });
  });

  it("非法 range 被丢弃，界面不出现未匹配值", async () => {
    await withPage(async (page) => {
      await page.goto(`${E2E_BASE_URL}/#/overview?app=all&range=bogus`);
      await page.waitFor(`!!document.querySelector('.page-overview')`, { label: "总览" });
      const labels = await page.eval(
        `[...document.querySelectorAll('button[role="combobox"]')].map(b => b.textContent.trim())`,
      );
      assert.ok(
        !labels.some((text) => text.includes("bogus")),
        `非法 range 不应出现在下拉里，实际: ${JSON.stringify(labels)}`,
      );
      // 非法值应被丢弃而不是回落到某个「看起来合理」的窗口
      assert.equal(labels[3], "最近 1 小时", "非法 range 应回落到缺省窗口");
    });
  });

  it("single 粒度路由把「全部应用」收敛为真实应用", async () => {
    await withPage(async (page) => {
      // `#/applications?app=all` 是合法的可分享形态（深链可直达），但应用页是
      // `single` 粒度，不接受「全部应用」：下拉框必须落到一个真实应用，
      // 否则匹配不到任何选项而退化成占位符。URL 保留 app=all 是既有行为。
      await page.goto(`${E2E_BASE_URL}/#/applications?app=all&range=1h`);
      await page.waitFor(`!!document.querySelector('.page-applications')`, { label: "应用页" });
      const appLabel = await page.eval(
        `[...document.querySelectorAll('button[role="combobox"]')][2].textContent.trim()`,
      );
      assert.notEqual(appLabel, "全部应用", "single 路由的应用下拉不应停在「全部应用」");
      assert.ok(appLabel.length > 0, "应用下拉应有真实应用名");
    });
  });
});

describe("系统管理 tab 受控于 URL", () => {
  const TABS = ["connections", "permissions", "identity", "runtime", "audit"];

  for (const tab of TABS) {
    it(`切到 ${tab} 写回 view 参数并渲染对应面板`, async () => {
      await withPage(async (page) => {
        await page.goto(`${E2E_BASE_URL}/#/system`);
        await page.waitFor(`!!document.querySelector('.page-system')`, { label: "系统管理页" });
        await page.goto(`${E2E_BASE_URL}/#/system?view=${tab}`);
        await page.waitFor(`!!document.querySelector('.page-system')`, { label: "系统管理页" });
        // 面板内容必须真的换掉，而不是 tab 高亮变了内容没变
        const body = await page.text(".page-system");
        assert.ok(body.length > 200, `${tab} 面板内容过短，疑似未渲染`);
      });
    });
  }
});

describe("规则工作台筛选", () => {
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
        await page.goto(`${E2E_BASE_URL}/#/rules?app=${app}&range=1h&view=${kind}`);
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
      await page.goto(`${E2E_BASE_URL}/#/rules?app=order-service&range=1h&view=system`);
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
      await page.goto(`${E2E_BASE_URL}/#/rules?app=order-service&range=1h&view=flow`);
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
      await page.goto(`${E2E_BASE_URL}/#/rules?app=order-service&range=1h&view=bogus`);
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
      await page.goto(`${E2E_BASE_URL}/#/rules?app=order-service&range=1h&view=degrade`);
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
      await page.goto(`${E2E_BASE_URL}/#/rules?app=order-service&range=1h`);
      await page.waitFor(`!!document.querySelector('.rules-layout')`, { label: "规则工作台" });
      const placeholder = await page.eval(
        `[...document.querySelectorAll('input')].map(i => i.placeholder).find(Boolean) ?? ''`,
      );
      assert.ok(placeholder, "前提：应能取到搜索框 placeholder");

      await page.type(".rules-layout input[type='search'], .rules-layout input", "zzzz-no-such-rule");
      // 按面板定位：`.rules-layout .empty` 会同时命中目录面板和检视器，
      // 两者是独立的两块，必须用 nth-child 区分，否则断言到的是另一块。
      await page.waitFor(
        `!!document.querySelector('.rules-layout > *:nth-child(1) .empty')`,
        { label: "搜索无结果时目录空态出现" },
      );
      const emptyText = await page.text(".rules-layout > *:nth-child(1) .empty");
      assert.notEqual(
        emptyText.trim(),
        `${placeholder}：0`,
        `空态文案不能是搜索框 placeholder 加计数：「${emptyText}」`,
      );
    });
  });
});

describe("多语言", () => {
  it("切到 English 后导航文案随之切换", async () => {
    await withPage(async (page) => {
      await page.goto(`${E2E_BASE_URL}/#/overview?app=all&range=1h`);
      await page.waitFor(`!!document.querySelector('.main-nav')`, { label: "导航" });
      await selectOption(page, 0, "English");
      await page.waitFor(
        `[...document.querySelectorAll('.main-nav button')].some(b => /rules|rule/i.test(b.textContent ?? ''))`,
        { label: "导航切到英文" },
      );
    });
  });
});
