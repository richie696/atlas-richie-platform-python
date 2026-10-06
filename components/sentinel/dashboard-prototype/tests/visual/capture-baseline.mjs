#!/usr/bin/env node
/**
 * Dashboard 视觉基线捕获 / 校验工具。
 *
 * 中文
 * ----
 * 重建页面时必须证明「展示效果不变」。本工具用系统 Chrome headless 对每条路由和
 * 关键交互状态捕获两样东西，并**分别**比较：
 *
 * 1. **归一化 DOM**：class 名决定实际样式，因此 DOM 归一化后逐字节相等，可以证明
 *    「这次改动没有动到影响渲染的结构与类名」，并且容易定位到差异元素。
 * 2. **整页 PNG**：证明「像素级渲染结果一致」。Chrome headless 截图是确定性的
 *    （同一 URL 连续两次捕获 md5 相同），因此可直接用内容摘要比较。
 *
 * **两个信号必须分开看。** DOM 相等但 PNG 不等 = 纯 CSS 层的回归：结构没动，
 * 但布局坏了。真实踩过的坑：Astryx `Button` 在 children 外包了一层盒子，
 * 使 `.event` 的四列 grid 只剩一个 grid item，事件行内容被塞进 12px 首列逐字
 * 换行——DOM 完全没变，DOM 比对全绿，但页面是错的。所以只比 DOM 是不够的。
 *
 * 归一化会抹掉的只有**与展示无关**的渲染期噪声：
 * - Vite 注入的 HMR 脚本与 style 标签内容；
 * - `data-backend-node-id`（Astryx 每次渲染重新生成）；
 * - SVG `id` / `clip-path`（Nivo 生成的随机实例 id）。
 * stylex 生成的 `x…` class 名**保留**，因为它们决定实际样式。
 *
 * 用法：
 * ```bash
 * node tests/visual/capture-baseline.mjs capture <outDir>   # 捕获基线
 * node tests/visual/capture-baseline.mjs compare <baseDir> <newDir>
 * ONLY=realtime,faults node tests/visual/capture-baseline.mjs capture <outDir>
 * # 有意接受某个用例的渲染变化（修复布局 bug 时使用，会记录在输出里）
 * ACCEPT_RENDER=faults node tests/visual/capture-baseline.mjs compare <baseDir> <newDir>
 * ```
 * 需要 dev server 已在 `BASE_URL`（默认 http://localhost:5173）运行。
 */
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync, existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { DEFAULT_TOLERANCE, diffPng } from "./png-diff.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BASE_URL = process.env.BASE_URL ?? "http://localhost:5173";
const CHROME = process.env.CHROME_BIN
  ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const VIEWPORT = { width: 1280, height: 900 };

/**
 * 采集矩阵。
 *
 * 中文
 * ----
 * 除了 11 条路由，还覆盖会改变渲染结果的筛选上下文：时间窗口、单/多实例 scope、
 * 语言、身份子页。仅覆盖路由本身会漏掉「切语言后时间范围标签失配」这类回归。
 */
const CASES = [
  { name: "overview-fleet", hash: "#/overview?app=all&range=1h" },
  { name: "overview-15m", hash: "#/overview?app=all&range=15m" },
  { name: "overview-single-app", hash: "#/overview?app=order-service&range=1h" },
  { name: "applications", hash: "#/applications?app=order-service&range=1h" },
  { name: "applications-15m", hash: "#/applications?app=order-service&range=15m" },
  { name: "rules", hash: "#/rules?app=order-service&range=1h" },
  // 规则页的类型筛选受控于 URL `view`。五个类型各一个用例 + 非法值回落。
  { name: "rules-filter-flow", hash: "#/rules?app=order-service&range=1h&view=flow" },
  { name: "rules-filter-degrade", hash: "#/rules?app=order-service&range=1h&view=degrade" },
  { name: "rules-filter-system", hash: "#/rules?app=order-service&range=1h&view=system" },
  { name: "rules-filter-authority", hash: "#/rules?app=order-service&range=1h&view=authority" },
  { name: "rules-filter-param", hash: "#/rules?app=order-service&range=1h&view=param" },
  { name: "rules-invalid-view", hash: "#/rules?app=order-service&range=1h&view=bogus" },
  { name: "realtime", hash: "#/realtime?app=all&range=1h" },
  { name: "realtime-15m", hash: "#/realtime?app=all&range=15m" },
  { name: "faults", hash: "#/faults?app=all&range=1h" },
  { name: "faults-15m", hash: "#/faults?app=all&range=15m" },
  { name: "login", hash: "#/login" },
  { name: "setup", hash: "#/setup" },

  // 系统管理的 5 个 tab 各自一个用例。tab 状态进 URL query（`view=<tab id>`），
  // 所以它们能被直接捕获。tab 还在组件 state 里的时代，这些面板的改动没有任何
  // 自动回归保护——基线只覆盖得到默认 tab。
  { name: "system-connections", hash: "#/system?app=all&range=1h&view=connections" },
  { name: "system-permissions", hash: "#/system?app=all&range=1h&view=permissions" },
  { name: "system-protocol", hash: "#/system?app=all&range=1h&view=protocol" },
  { name: "system-accounts", hash: "#/system?app=all&range=1h&view=accounts" },
  { name: "system-roles", hash: "#/system?app=all&range=1h&view=roles" },
  // 无 `view` 时应回落到默认 tab，且不产生多余的 query
  { name: "system-default-tab", hash: "#/system?app=all&range=1h" },
  // 非法 view 必须回落到默认 tab，而不是「就近猜一个」
  { name: "system-invalid-view", hash: "#/system?app=all&range=1h&view=bogus" },

  { name: "accounts", hash: "#/accounts?app=all&range=1h&account=account-admin" },
  { name: "roles", hash: "#/roles?app=all&range=1h&account=account-view" },
  { name: "change-password", hash: "#/change-password?app=all&range=1h&account=account-admin" },
];

/**
 * 用例过滤。
 *
 * 多个 feature 并行重建时，每个 worker 只校验自己负责的路由：其余路由此刻可能正
 * 处于其他 worker 的中间态，纳入比较只会产生无法归因的误报。用 `ONLY=a,b` 指定。
 */
const ONLY = process.env.ONLY
  ? new Set(process.env.ONLY.split(",").map((item) => item.trim()).filter(Boolean))
  : null;

/**
 * 声明接受的渲染变化。
 *
 * 只在**刻意修复布局缺陷**时使用（此时 DOM 正确但像素应当改变）。它把「我知道这
 * 个用例的渲染会变，且这是有意的」变成一次显式声明并留在命令输出里，而不是让
 * 差异被悄悄重新基线化。
 */
const ACCEPT_RENDER = process.env.ACCEPT_RENDER
  ? new Set(process.env.ACCEPT_RENDER.split(",").map((item) => item.trim()).filter(Boolean))
  : new Set();

/**
 * 声明接受某个用例的 **DOM 变化**。
 *
 * 中文
 * ----
 * DOM 等价是本工具的主硬约束，渲染 diff 只是附加信号。因此有意的结构或文案变更
 * （例如登录页加一句演示账号说明）必须能被显式记录，而不是靠「换个基线目录」
 * 让它变绿——后者是静默的，而静默重新基线化会让人以为这次变更从未发生。
 *
 * **必须同时给 `DOM_CHANGE_REASON`**，否则直接报错退出：接受一个自己说不出原因的
 * DOM 变化，和不接受它的差别只剩下一个绿色输出。
 */
const ACCEPT_DOM = process.env.ACCEPT_DOM
  ? new Set(process.env.ACCEPT_DOM.split(",").map((item) => item.trim()).filter(Boolean))
  : new Set();

/** 接受 DOM 变化时必须给出的原因，会打印在输出里。 */
const DOM_CHANGE_REASON = process.env.DOM_CHANGE_REASON ?? "";

if (ACCEPT_DOM.size > 0 && !DOM_CHANGE_REASON.trim()) {
  throw new Error(
    "ACCEPT_DOM 需要同时提供 DOM_CHANGE_REASON：接受一个说不出原因的 DOM 变化，" +
      "与不接受它只差一个绿色输出。",
  );
}

/**
 * 渲染容差。可用 `TOLERANCE_RATIO` / `TOLERANCE_MAX_DELTA` 覆盖。
 *
 * 默认值来自实测：跨进程 Chrome 捕获的抗锯齿抖动上限约 0.0077% 像素 / 通道差 44；
 * 真实布局回归是 0.68% / 通道差 233。阈值取抖动上限的约 6 倍与 1.8 倍。
 */
const TOLERANCE = Object.freeze({
  ratio: Number(process.env.TOLERANCE_RATIO ?? DEFAULT_TOLERANCE.ratio),
  maxDelta: Number(process.env.TOLERANCE_MAX_DELTA ?? DEFAULT_TOLERANCE.maxDelta),
});

/** 按过滤器筛选用例。 */
function selectedCases() {
  return ONLY ? CASES.filter((item) => ONLY.has(item.name)) : CASES;
}

/** 抹掉与展示无关的渲染期噪声；stylex 的 x… class 名必须保留。 */
function normalizeDom(html) {
  return html
    // Vite HMR 注入的脚本与样式内容含随机 token
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "")
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, "")
    // Astryx 每次渲染重新生成的节点标识
    .replace(/\sdata-backend-node-id="[^"]*"/g, "")
    // Nivo / SVG 生成的实例级 id
    .replace(/\sid="[^"]*"/g, ' id="_"')
    .replace(/url\(#[^)]*\)/g, "url(#_)")
    .replace(/\sclip-path="[^"]*"/g, ' clip-path="url(#_)"')
    // 压缩空白，避免纯格式差异造成误报
    .replace(/\s+/g, " ")
    .replace(/> </g, "><")
    .trim();
}

function chrome(args) {
  return execFileSync(
    CHROME,
    ["--headless", "--disable-gpu", "--hide-scrollbars", "--no-sandbox", ...args],
    { encoding: "utf8", maxBuffer: 64 * 1024 * 1024, stdio: ["ignore", "pipe", "pipe"] },
  );
}

/**
 * 截一张图并等到**渲染收敛**。
 *
 * 中文
 * ----
 * 页面里存在懒绘制（Astryx 的 `content-visibility: auto`），视口下缘的内容按需补绘。
 * 截图若早于补绘完成，那一带会画成页面背景色；晚于则画成面板底色。两种结果都是
 * **合法渲染**，但截图捕获到哪一个是随机的——实测同一份代码 8 次采样里 5 次落在
 * 状态 A、3 次落在状态 B，差异 23287px / 2.02% / 通道差 61，而 DOM 逐字节相同。
 *
 * 这会让像素门禁变成随机噪声：同一个 commit 有时「全绿」有时「失败」，而失败信息
 * 指向的区域其实与被测改动无关。改前状态同样复现（8 次里 3 次落到 B），所以这是
 * 既有缺陷，不是某次改动引入的。
 *
 * 修法不是去猜绘制时序，而是**拒绝接受未收敛的捕获**：连续两次截图一致才算数。
 * 收敛后记录的就是稳定态，基线与比对才重新有意义。代价约 1.7 倍截图时间。
 *
 * 逐字节比较足够：像素完全相同则 PNG 编码结果也完全相同（实测同态两次 md5 一致）。
 */
function captureSettled(testCase, outDir) {
  const url = `${BASE_URL}/${testCase.hash}`;
  const finalPath = path.join(outDir, `${testCase.name}.png`);
  const scratch = `${finalPath}.settling.png`;
  const args = (target) => [
    `--screenshot=${target}`,
    `--window-size=${VIEWPORT.width},${VIEWPORT.height}`,
    "--virtual-time-budget=4000",
    url,
  ];

  let previous = null;
  for (let attempt = 1; attempt <= 5; attempt += 1) {
    chrome(args(scratch));
    const current = readFileSync(scratch);
    if (previous !== null && current.equals(previous)) {
      writeFileSync(finalPath, current);
      rmSync(scratch, { force: true });
      return { attempts: attempt, converged: true };
    }
    previous = current;
  }
  // 5 次仍未收敛：采用最后一次，并如实标记，让比对阶段知道这条不可靠。
  writeFileSync(finalPath, previous);
  rmSync(scratch, { force: true });
  return { attempts: 5, converged: false };
}

function captureCase(testCase, outDir) {
  const url = `${BASE_URL}/${testCase.hash}`;
  const dom = normalizeDom(chrome(["--dump-dom", url]));
  writeFileSync(path.join(outDir, `${testCase.name}.html`), dom, "utf8");

  const shot = captureSettled(testCase, outDir);
  return { name: testCase.name, bytes: dom.length, ...shot };
}

function capture(outDir) {
  if (!existsSync(outDir)) mkdirSync(outDir, { recursive: true });
  const results = [];
  for (const testCase of selectedCases()) {
    const result = captureCase(testCase, outDir);
    results.push(result);
    // 收敛信息必须可见：静默重采会让人以为一次就稳定，而那正是本工具出过问题的地方。
    const settle = result.converged
      ? `settle=${result.attempts}`
      : `⚠ 未收敛(重试 ${result.attempts} 次)`;
    process.stdout.write(`  ✓ ${result.name.padEnd(24)} dom=${result.bytes}B  ${settle}\n`);
  }
  writeFileSync(
    path.join(outDir, "manifest.json"),
    JSON.stringify(
      {
        viewport: VIEWPORT,
        cases: selectedCases().map((c) => ({
          name: c.name,
          hash: c.hash,
          settled: results.find((r) => r.name === c.name)?.converged ?? null,
        })),
      },
      null, 2,
    ),
    "utf8",
  );
  return results.length;
}

/** 找出首个差异位置并打印上下文，便于直接定位到元素。 */
function firstDifference(baseline, candidate) {
  const limit = Math.min(baseline.length, candidate.length);
  let index = 0;
  while (index < limit && baseline[index] === candidate[index]) index += 1;
  const start = Math.max(0, index - 120);
  return {
    index,
    baselineLength: baseline.length,
    candidateLength: candidate.length,
    baselineExcerpt: baseline.slice(start, index + 160),
    candidateExcerpt: candidate.slice(start, index + 160),
  };
}

/** 截图内容摘要。摘要相同即像素级完全一致，可跳过像素扫描。 */
function renderDigest(filePath) {
  return createHash("sha256").update(readFileSync(filePath)).digest("hex").slice(0, 16);
}

/**
 * 比较两��截图的渲染结果。
 *
 * 不直接比摘要：抗锯齿与字体栅格化在跨进程 Chrome 启动之间有极少量抖动
 * （实测同一页面两次捕获最多 89 像素 / 0.0077% / 最大通道差 44），而真实布局
 * 回归的量级是 7849 像素 / 0.68% / 最大通道差 233。改用容差像素比对，两个条件
 * 任一超限才判为回归。
 */
function compareRender(name, basePng, newPng) {
  if (!existsSync(basePng) || !existsSync(newPng)) {
    return { state: "无基线截图", failure: null };
  }
  if (renderDigest(basePng) === renderDigest(newPng)) {
    return { state: "渲染一致", failure: null };
  }
  const result = diffPng(basePng, newPng, TOLERANCE);
  if (!result.beyondTolerance) {
    return {
      state: `渲染一致(容差内 ${result.differing}px)`,
      failure: null,
    };
  }
  if (ACCEPT_RENDER.has(name)) {
    return {
      state: `渲染变化(已声明接受 ${result.differing}px)`,
      failure: null,
      accepted: true,
    };
  }
  const region = result.bbox ? `区域 x${result.bbox[0]}-${result.bbox[2]} y${result.bbox[1]}-${result.bbox[3]}` : "全图";
  return {
    state: result.sizeMismatch
      ? "渲染不同(尺寸变化)"
      : `渲染不同 ${result.differing}px/${(result.ratio * 100).toFixed(4)}% Δ${result.maxDelta}`,
    failure: {
      reason: result.sizeMismatch
        ? `渲染不同：尺寸从 ${result.baselineSize} 变为 ${result.candidateSize}`
        : `渲染不同：${result.differing} 像素（${(result.ratio * 100).toFixed(4)}%），最大通道差 ${result.maxDelta}，${region}`,
    },
  };
}

function compare(baseDir, newDir) {
  if (!existsSync(baseDir)) throw new Error(`基线目录不存在: ${baseDir}`);
  const caseNames = readdirSync(baseDir)
    .filter((name) => name.endsWith(".html"))
    .map((name) => name.replace(/\.html$/, ""))
    .filter((name) => !ONLY || ONLY.has(name))
    .sort();
  if (caseNames.length === 0) throw new Error(`基线目录没有 .html 快照: ${baseDir}`);

  const failures = [];
  const accepted = [];
  let domEqual = 0;
  let renderEqual = 0;

  for (const name of caseNames) {
    const baseHtml = path.join(baseDir, `${name}.html`);
    const newHtml = path.join(newDir, `${name}.html`);
    const basePng = path.join(baseDir, `${name}.png`);
    const newPng = path.join(newDir, `${name}.png`);

    if (!existsSync(newHtml)) {
      failures.push({ name, reason: "新快照缺失该用例" });
      process.stdout.write(`  ✗ ${name.padEnd(24)} 快照缺失\n`);
      continue;
    }

    const baseline = readFileSync(baseHtml, "utf8");
    const candidate = readFileSync(newHtml, "utf8");
    const domOk = baseline === candidate;
    const domAccepted = !domOk && ACCEPT_DOM.has(name);
    if (domOk) domEqual += 1;
    else if (domAccepted) accepted.push(name);
    else failures.push({ name, reason: "DOM 不等价", ...firstDifference(baseline, candidate) });

    // DOM 相等但渲染不同 = 纯 CSS 层回归。这是最容易漏掉的一类。
    const render = compareRender(name, basePng, newPng);
    if (render.failure) {
      failures.push({ name, reason: render.failure.reason });
    } else if (render.accepted) {
      accepted.push(name);
    } else if (render.state.startsWith("渲染一致")) {
      renderEqual += 1;
    }

    process.stdout.write(
      `  ${(domOk || domAccepted) && !render.failure ? "✓" : "✗"} ${name.padEnd(24)} ` +
        `DOM ${domOk ? "等价" : domAccepted ? "变化(已声明接受)" : "不等价"} · ${render.state}\n`,
    );
  }

  const newCases = readdirSync(newDir)
    .filter((name) => name.endsWith(".html"))
    .map((name) => name.replace(/\.html$/, ""))
    .filter((name) => !caseNames.includes(name))
    .filter((name) => !ONLY || ONLY.has(name));
  for (const name of newCases) {
    failures.push({ name, reason: "新增了基线中不存在的用例" });
  }

  process.stdout.write(
    `\n用例 ${caseNames.length} 个 · DOM 等价 ${domEqual} 个 · 渲染一致 ${renderEqual} 个`,
  );
  if (accepted.length > 0) {
    process.stdout.write(` · 已声明接受的渲染变化: ${accepted.join(", ")}`);
  }
  process.stdout.write("\n");
  if (failures.length > 0) {
    process.stdout.write("\n差异详情:\n");
    for (const failure of failures) {
      process.stdout.write(`\n[${failure.name}] ${failure.reason}\n`);
      if (failure.baselineExcerpt !== undefined) {
        process.stdout.write(`  首个差异位置: ${failure.index} (基线 ${failure.baselineLength}B vs 当前 ${failure.candidateLength}B)\n`);
        process.stdout.write(`  基线: …${failure.baselineExcerpt}…\n`);
        process.stdout.write(`  当前: …${failure.candidateExcerpt}…\n`);
      }
    }
  }
  return failures.length;
}

const [command, ...rest] = process.argv.slice(2);
if (command === "capture") {
  const outDir = rest[0];
  if (!outDir) throw new Error("用法: capture <outDir>");
  process.stdout.write(`捕获基线 -> ${outDir} (${selectedCases().length} 个用例)${ONLY ? ` [ONLY=${[...ONLY].join(",")}]` : ""}\n`);
  const count = capture(outDir);
  process.stdout.write(`\n完成: ${count} 个用例\n`);
  process.exit(0);
} else if (command === "compare") {
  const [baseDir, newDir] = rest;
  if (!baseDir || !newDir) throw new Error("用法: compare <baseDir> <newDir>");
  const failures = compare(baseDir, newDir);
  process.exit(failures > 0 ? 1 : 0);
} else {
  throw new Error("用法: capture <outDir> | compare <baseDir> <newDir>");
}
