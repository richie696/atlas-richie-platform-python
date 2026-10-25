#!/usr/bin/env node
/**
 * 文档中心插图捕获工具。
 *
 * 中文
 * ----
 * 文档正文要讲「点哪里、看什么」，光靠文字描述读者仍然要在界面里找。插图把
 * 「这一页长什么样、模块在哪、图上哪个数字对应正文哪个指标」固定下来。
 *
 * 这个工具做三件事：
 * 1. 用隔离的 Edge 实例（临时 profile，与日常浏览器无关）打开控制台；
 * 2. 按 locale 设置界面语言偏好，等页面渲染收敛后截图；
 * 3. 写出一份 manifest，列出每张图的字节数与摘要，供逻辑测试核对正文引用。
 *
 * **收敛判据**：连续两次截图字节一致才算数。页面里有懒绘制（`content-visibility: auto`），
 * 早截会把视口下缘画成页面背景色，晚截画成面板底色——两种都是合法渲染，但落到哪一张
 * 是随机的，不收敛的图进文档会变成噪声。
 *
 * 用法：
 * ```bash
 * node scripts/capture-doc-figures.mjs                     # 全部 locale
 * LOCALE=zh-CN node scripts/capture-doc-figures.mjs         # 只抓中文
 * ONLY=overview,rules node scripts/capture-doc-figures.mjs  # 只抓指定图
 * BASE_URL=http://127.0.0.1:5173 node scripts/capture-doc-figures.mjs
 * ```
 */
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";

import { connectE2EBrowser } from "../tests/e2e/cdp.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(HERE, "..");
const OUTPUT_ROOT = path.join(PROJECT_ROOT, "public", "docs", "figures");
const MANIFEST_PATH = path.join(OUTPUT_ROOT, "manifest.json");

const VIEWPORT = { width: 1280, height: 900 };
const BASE_URL = process.env.BASE_URL ?? "http://localhost:5173";
const EDGE_BIN = process.env.EDGE_BIN ?? "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge";
const LOCALES = ["zh-CN", "en-US", "ja-JP"];

/**
 * 插图清单。
 *
 * 每一项是「页面 + 取景」。`hash` 是控制台的 hash 路由；`clip` 可选，用来裁掉
 * 顶栏与侧边导航，只保留要讲的那块内容。`scroll` 用来把页面滚到指定位置再截，
 * 让下半屏的模块也能入镜。
 */
/**
 * 插图路由。
 *
 * `env=test-env` 与 `app=app-one` 不是随手写的：它们是演示场景里真实存在的环境 id 与
 * 应用 id（`src/app/api/mockSystemScenario.ts`）。传错应用 id 时页面不会报错，只会渲染
 * 「未找到所选应用」的空态——插图于是变成一张没有内容的图，还比没有更糟。
 */
const FIGURES = [
  { name: "overview", hash: "#/overview?env=test-env&app=all&range=1h" },
  { name: "applications", hash: "#/applications?env=test-env&app=app-one&range=1h" },
  { name: "hosts", hash: "#/applications?env=test-env&app=all&range=1h&view=hosts" },
  { name: "rules", hash: "#/rules?env=test-env&app=app-one&range=1h" },
  { name: "realtime", hash: "#/realtime?env=test-env&app=all&range=1h", scrollTo: 1000 },
  { name: "faults", hash: "#/faults?env=test-env&app=all&range=1h&event=incident-resource-pressure" },
  { name: "system-connections", hash: "#/system?env=test-env&app=all&range=1h&view=connections" },
  { name: "accounts", hash: "#/accounts?env=test-env&app=all&range=1h&account=account-admin" },
];

const ONLY = process.env.ONLY
  ? new Set(
      process.env.ONLY.split(",")
        .map((item) => item.trim())
        .filter(Boolean),
    )
  : null;
const LOCALE = process.env.LOCALE;

/**
 * 固定时钟。
 *
 * 页面顶部会显示「读取时间」与观测窗口的起止，这些都来自当前时间。两次捕获之间
 * 时钟走了一秒，图就永远不收敛——插图会变成一张随时间变化的噪点图。
 * 固定时刻后，页面算出的观测窗口也固定，图才稳定可复现。
 *
 * 用 UTC 固定时刻而不是本地时间：图上会显示本地时区偏移，同一张图在不同机器上
 * 应当呈现同样的内容。
 */
const FIXED_NOW = Date.UTC(2026, 9, 25, 3, 55, 48);

/**
 * 页面已渲染的判据。
 *
 * 三件事要同时成立：
 * 1. `.main-nav` 出现——身份已放行，导航渲染完；
 * 2. 路由懒加载的兜底段 `[data-route-state="loading"]` 消失——页面组件真的加载完了；
 * 3. `#root` 有子节点。
 *
 * 只等 1 会截到「正在加载页面…」：那是 `RouteBoundary` 的 Suspense 兜底，
 * 导航先于页面组件渲染。只等 2 会卡在登录页（登录页不套应用壳）。
 */
const APP_READY = `(() => {
  const root = document.getElementById("root");
  if (!root || root.children.length === 0) return false;
  if (!root.querySelector(".main-nav")) return false;
  return !root.querySelector('[data-route-state="loading"]');
})()`;

async function waitForDevTools(profile, child, timeoutMs = 20000) {
  const activePortFile = path.join(profile, "DevToolsActivePort");
  const deadline = Date.now() + timeoutMs;
  let diagnostics = "";
  child.stderr.on("data", (chunk) => {
    diagnostics = (chunk.toString() ?? "").slice(-4000);
  });
  while (Date.now() < deadline) {
    if (child.exitCode !== null || child.signalCode !== null) {
      throw new Error(`Microsoft Edge exited before DevTools was ready. ${diagnostics}`);
    }
    if (existsSync(activePortFile)) {
      const [port] = readFileSync(activePortFile, "utf8").trim().split(/\r?\n/);
      if (/^\d+$/.test(port ?? "")) {
        const endpoint = `http://127.0.0.1:${port}`;
        try {
          const response = await fetch(`${endpoint}/json/version`, {
            signal: AbortSignal.timeout(1000),
          });
          if (response.ok && typeof (await response.json()).webSocketDebuggerUrl === "string") {
            return endpoint;
          }
        } catch {
          // Edge 先写 DevToolsActivePort，再开放发现端点；这一步失败属于正常时序。
        }
      }
    }
    await delay(100);
  }
  throw new Error(`Timed out waiting for Edge DevTools. ${diagnostics}`);
}

/**
 * 连续两次截图字节一致才算收敛。
 *
 * `scrollTo` 把页面滚到指定位置再取景。默认只截首屏，但有些页面的主体在折叠线以下
 * （实时监控页的进程级曲线就在主机级区块下面），只截首屏会拍到一块空态提示。
 */
async function captureSettled(page, url, prepare, scrollTo = 0) {
  let previous = null;
  for (let attempt = 1; attempt <= 5; attempt += 1) {
    await page.clearStorage(new URL(BASE_URL).origin);
    // 语言偏好必须落在清存储之后、导航之前，否则会被清掉。
    if (prepare) await prepare();
    await page.goto(url);
    await page.waitFor(APP_READY, { label: url });
    if (scrollTo > 0) {
      await page.send("Runtime.evaluate", {
        expression: `window.scrollTo(0, ${scrollTo})`,
        returnByValue: true,
      });
      // 滚动会触发懒绘制，必须重新等一次布局收敛。
      await page.waitForStableLayout();
    }
    await page.waitForStableLayout();
    const current = await page.screenshot();
    if (previous !== null && current.equals(previous)) return { bytes: current, attempts: attempt };
    previous = current;
  }
  return { bytes: previous, attempts: 5 };
}

async function main() {
  if (!existsSync(EDGE_BIN)) {
    throw new Error(`Microsoft Edge executable not found: ${EDGE_BIN}; set EDGE_BIN`);
  }
  const locales = LOCALE ? [LOCALE] : LOCALES;
  const figures = ONLY ? FIGURES.filter((figure) => ONLY.has(figure.name)) : FIGURES;
  if (figures.length === 0) throw new Error("No figures matched the filter");

  const profile = mkdirSync(path.join(tmpdir(), `sentinel-doc-figures-${process.pid}-`), {
    recursive: true,
  });
  const browserProcess = spawn(
    EDGE_BIN,
    [
      "--headless=new",
      "--no-first-run",
      "--no-default-browser-check",
      "--disable-extensions",
      "--hide-scrollbars",
      "--remote-debugging-port=0",
      "--remote-allow-origins=*",
      `--user-data-dir=${profile}`,
      "about:blank",
    ],
    { detached: true, stdio: ["ignore", "ignore", "pipe"] },
  );

  let endpoint;
  try {
    endpoint = await waitForDevTools(profile, browserProcess);
  } catch (error) {
    rmSync(profile, { recursive: true, force: true });
    throw error;
  }

  const entries = [];
  let browser;
  try {
    browser = await connectE2EBrowser({ viewport: VIEWPORT, cdpEndpoint: endpoint });
    const page = await browser.newPage();
    for (const locale of locales) {
      const localeDirectory = path.join(OUTPUT_ROOT, locale);
      mkdirSync(localeDirectory, { recursive: true });
      // 语言偏好与演示身份来自 localStorage，必须在清存储之后、导航之前落，
      // 否则会被清掉，页面会一直停在「正在加载页面…」。
      // 用 `addScriptToEvaluateOnNewDocument` 而不是手动 setItem：手动写入需要在
      // 导航前先开一次页面，那一次额外加载会把服务注册与身份一起带偏。
      const { identifier } = await page.send("Page.addScriptToEvaluateOnNewDocument", {
        source: [
          `localStorage.setItem("sentinel.locale", ${JSON.stringify(locale)});`,
          `localStorage.setItem("sentinel.mock.role", "admin");`,
          // 固定时钟：不固定则「读取时间」每次都不同，图永远不收敛。
          `(() => {
            const FIXED = ${FIXED_NOW};
            const Real = Date;
            class Fixed extends Real {
              constructor(...args) { if (args.length === 0) super(FIXED); else super(...args); }
              static now() { return FIXED; }
            }
            Date = Fixed;
          })();`,
          // 关闭动画与过渡：图表入场动画会让连续两次截图不一致。
          `(() => {
            const apply = () => {
              if (!document.head) return false;
              const style = document.createElement("style");
              style.setAttribute("data-doc-figure", "still");
              style.textContent =
                "*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}";
              document.head.appendChild(style);
              return true;
            };
            if (!apply()) document.addEventListener("DOMContentLoaded", apply);
          })();`,
        ].join("\n"),
      });
      try {
        for (const figure of figures) {
          const url = `${BASE_URL}/${figure.hash}`;
          const shot = await captureSettled(page, url, undefined, figure.scrollTo ?? 0);
          const bodyText = await page.text("body");
          if (bodyText.includes("正在加载页面") || bodyText.includes("Loading page")) {
            throw new Error(
              `插图 ${locale}/${figure.name} 截到加载兜底页，说明页面组件没加载完。\n` +
                `  正文摘要: ${bodyText.replace(/\s+/g, " ").slice(0, 200)}\n` +
                `  控制台错误: ${JSON.stringify(page.consoleErrors ?? []).slice(0, 1200)}`,
            );
          }
          const fileName = `${figure.name}.png`;
          const filePath = path.join(localeDirectory, fileName);
          writeFileSync(filePath, shot.bytes);
          const digest = createHash("sha256").update(shot.bytes).digest("hex").slice(0, 16);
          entries.push({
            name: figure.name,
            locale,
            path: `docs/figures/${locale}/${fileName}`,
            bytes: shot.bytes.length,
            digest,
            converged: shot.attempts < 5,
          });
          process.stdout.write(
            `  ${locale} ${figure.name.padEnd(22)} ${String(shot.bytes.length).padStart(8)}B  settle=${shot.attempts}\n`,
          );
        }
      } finally {
        await page.send("Page.removeScriptToEvaluateOnNewDocument", { identifier });
      }
    }
  } finally {
    if (browser) await browser.close();
    try {
      process.kill(-browserProcess.pid, "SIGTERM");
    } catch {
      browserProcess.kill("SIGTERM");
    }
    // Edge 的辅助进程退出有延迟，profile 目录还在写时直接删会报 ENOTEMPTY。
    const exited = new Promise((resolve) => browserProcess.once("exit", resolve));
    await Promise.race([exited, delay(3000)]);
    rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  }

  mkdirSync(OUTPUT_ROOT, { recursive: true });
  writeFileSync(
    MANIFEST_PATH,
    `${JSON.stringify({ viewport: VIEWPORT, figures: entries }, null, 2)}\n`,
    "utf8",
  );
  const unresolved = entries.filter((entry) => !entry.converged);
  if (unresolved.length > 0) {
    process.stdout.write(
      `\n⚠ 未收敛的图（已写入但可能不稳定）: ${unresolved.map((entry) => `${entry.locale}/${entry.name}`).join(", ")}\n`,
    );
  }
  process.stdout.write(`\n共 ${entries.length} 张图 -> ${path.relative(PROJECT_ROOT, OUTPUT_ROOT)}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
});
