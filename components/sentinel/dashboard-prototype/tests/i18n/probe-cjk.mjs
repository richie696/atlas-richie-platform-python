/**
 * 一次性探测：切到指定语言后，列出页面上所有**可见**的中文文本。
 *
 * 为什么需要它
 * ------------
 * E2E 里的语言用例只检查页面**标题**与**筛选条**。overview 迁移前，这两处都是
 * 干净的（Filters 已迁、页面标题由壳层 nav 渲染），但表格头、趋势标题、异常摘要、
 * 基础组件卡片全是中文——49 条用例全绿，中文却满页都是。
 *
 * `tests/i18n/audit.mjs` 扫的是**源码**，它看不到：
 * - model 层被渲染成文本的中文常量（`TPS_INTEGRATION.note` 就是这样漏掉的）
 * - shared 组件里的文案
 * - 经由 props 层层传递、最终在别的 feature 渲染的中文
 *
 * 这个脚本扫**运行时 DOM**，因此能兜住上面三类。代价是它分不清「界面文案」和
 * 「演示数据」：应用名、健康状态、事件标题里的中文是 `fixtures/` 的数据，按设计
 * 不翻译。所以输出是**清单**不是判定，交由人归类。
 *
 * 用法：
 *   node tests/i18n/probe-cjk.mjs en-US                 # 全部用例
 *   node tests/i18n/probe-cjk.mjs ja-JP overview-fleet # 指定用例
 */
import { launchBrowser } from "../e2e/cdp.mjs";

const BASE = process.env.BASE_URL ?? "http://127.0.0.1:5173";

/** 与 `tests/visual/capture-baseline.mjs` 的 CASES 保持同一批路由。 */
const CASES = [
  ["overview-fleet", "#/overview"],
  ["applications", "#/applications"],
  ["rules", "#/rules"],
  ["realtime", "#/realtime"],
  ["faults", "#/faults"],
  ["system-roles", "#/system"],
  ["accounts", "#/accounts"],
  ["roles", "#/roles"],
];

/**
 * 在页面里执行：收集所有可见的、含 CJK 的文本片段。
 *
 * 判据是「自己占用面积且没有隐藏祖先」——`textContent` 会把 `<script>`、隐藏的
 * listbox 选项、`display: contents` 的包装层一起算进来，那些不是用户看到的内容。
 */
const COLLECT = `(() => {
  const CJK = /[\\u4e00-\\u9fff]/;
  const out = [];
  const seen = new Set();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    const text = (node.nodeValue || "").trim();
    if (!text || !CJK.test(text)) continue;
    const el = node.parentElement;
    if (!el) continue;
    if (el.closest("script, style, [aria-hidden='true']")) continue;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) continue;
    if (getComputedStyle(el).visibility === "hidden") continue;
    // 同一段文字可能在多个节点重复（列表虚拟化），只留一份并记住出处。
    const tag = el.tagName.toLowerCase();
    const key = tag + "|" + text;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ tag, cls: el.className || "", text });
  }
  return out;
})()`;

const locale = process.argv[2] ?? "en-US";
const filters = process.argv.slice(3);
const cases = filters.length
  ? CASES.filter(([name]) => filters.includes(name))
  : CASES;

if (cases.length === 0) {
  console.error(`没有匹配的用例。可用: ${CASES.map(([n]) => n).join(", ")}`);
  process.exit(2);
}

const browser = await launchBrowser();
let exitCode = 0;
try {
  const page = await browser.newPage();
  // 先用一次访问把 localStorage 写好，再逐个路由切换：直接改存储比点语言下拉
  // 少一层 UI 依赖，探测的是「语言值 → 渲染」这条链，不是下拉本身。
  await page.goto(`${BASE}/`);
  await page.eval(`window.localStorage.setItem('sentinel.locale', ${JSON.stringify(locale)})`);

  for (const [name, hash] of cases) {
    await page.goto(`${BASE}/${hash}`);
    await page.waitFor(`document.querySelector('.app-shell, body > #root') !== null`, {
      label: "应用挂载",
    });
    const items = await page.eval(COLLECT);
    const head = items.length === 0 ? "干净" : `${items.length} 处`;
    console.log(`\n── ${name} ${head} ──`);
    for (const item of items) {
      const where = item.cls ? `.${String(item.cls).split(/\s+/).slice(0, 2).join(".")}` : item.tag;
      console.log(`  <${item.tag}${item.cls ? ` class="${item.cls}"` : ""}> ${item.text}`);
      void where;
    }
    if (items.length) exitCode = 1;
  }
} finally {
  await browser.close();
}
process.exit(exitCode);
