/**
 * 零依赖 Chrome DevTools Protocol 客户端。
 *
 * 中文
 * ----
 * 视觉基线工具（`tests/visual/capture-baseline.mjs`）用 `chrome --dump-dom` /
 * `--screenshot` 一次性抓取，**只能验证首屏渲染，不能点击**。组件重写里有真实缺陷
 * 只在交互后才暴露：状态写入路径、受控回环、过期结果覆盖、Effect 清理。
 * 纯函数测试同样证明不了这些——skill 明确写了「普通函数测试不证明 UI 生命周期正确」。
 *
 * 因此这里补一条**交互驱动**能力。不引入 puppeteer/playwright：
 * Node 22+ 内置 `WebSocket`，直接讲 CDP 即可，项目的 devDependencies 保持不变。
 * 这与「本 skill 不授权安装依赖」以及既有工具零依赖的约定一致。
 *
 * 端口用 `--remote-debugging-port=0` 让 Chrome 自选，再从 user-data-dir 里的
 * `DevToolsActivePort` 读回实际端口——避免固定端口撞车，也避免轮询一串候选端口。
 *
 * 用法：
 * ```js
 * const browser = await launchBrowser();
 * const page = await browser.newPage();
 * await page.goto("http://localhost:5173/#/rules");
 * await page.clickByText("降级");
 * console.log(await page.text("body"));
 * await browser.close();
 * ```
 */
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { setTimeout as delay } from "node:timers/promises";

const CHROME =
  process.env.CHROME_BIN ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

/** 等待文件出现并返回内容；用于读取 Chrome 自选的调试端口。 */
async function waitForFile(file, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (existsSync(file)) {
      const text = readFileSync(file, "utf8").trim();
      if (text) return text;
    }
    await delay(50);
  }
  throw new Error(`等待 ${file} 超时（${timeoutMs}ms）`);
}

/**
 * 一个 CDP 会话。
 *
 * 中文
 * ----
 * 用扁平会话（`flatten: true`）：每条命令带 `sessionId` 直接路由到目标页，
 * 不需要自己维护 targetId -> socket 的多路复用树。单页场景下这层复杂度不划算。
 */
class Connection {
  #socket;
  #nextId = 1;
  #pending = new Map();
  #listeners = new Set();
  #closed = false;

  constructor(socket) {
    this.#socket = socket;
    socket.addEventListener("message", (event) => this.#onMessage(event.data));
    socket.addEventListener("close", () => {
      this.#closed = true;
      for (const { reject } of this.#pending.values()) {
        reject(new Error("CDP 连接已关闭"));
      }
      this.#pending.clear();
    });
  }

  #onMessage(raw) {
    const message = JSON.parse(raw);
    if (message.id !== undefined) {
      const entry = this.#pending.get(message.id);
      if (!entry) return;
      this.#pending.delete(message.id);
      if (message.error) {
        entry.reject(
          new Error(`${message.error.message} (${JSON.stringify(message.error.data ?? null)})`),
        );
      } else {
        entry.resolve(message.result);
      }
      return;
    }
    for (const listener of this.#listeners) listener(message);
  }

  send(method, params = {}, sessionId) {
    if (this.#closed) return Promise.reject(new Error(`CDP 已关闭，无法发送 ${method}`));
    const id = this.#nextId++;
    const payload = { id, method, params };
    if (sessionId) payload.sessionId = sessionId;
    return new Promise((resolve, reject) => {
      this.#pending.set(id, { resolve, reject });
      this.#socket.send(JSON.stringify(payload));
    });
  }

  on(listener) {
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  }

  close() {
    this.#closed = true;
    try {
      this.#socket.close();
    } catch {
      // 关闭竞态下 socket 可能已断开；这里只关心不抛未处理异常。
    }
  }
}

/** 单个页面：所有交互断言都从这里发起。 */
class Page {
  #connection;
  #sessionId;
  #targetId;
  #consoleErrors = [];

  constructor(connection, sessionId, targetId) {
    this.#connection = connection;
    this.#sessionId = sessionId;
    this.#targetId = targetId;
  }

  get consoleErrors() {
    return this.#consoleErrors;
  }

  /** 供 CDP 事件监听回调写入；私有字段不能被类外部直接访问。 */
  recordConsoleError(text) {
    this.#consoleErrors.push(text);
  }

  /**
   * 关闭标签页。
   *
   * 中文
   * ----
   * 必须显式关闭。CDP 里 `Target.createTarget` 开的页面不会随 JS 垃圾回收消失，
   * 累积到几十个标签时 Chrome 内存与合成开销明显上升，整套用例越跑越慢。
   */
  async close() {
    await this.#connection.send("Target.closeTarget", { targetId: this.#targetId });
  }

  /** 发送一条 CDP 命令到本页面对应的目标。 */
  send(method, params) {
    return this.#connection.send(method, params, this.#sessionId);
  }

  async #evaluate(expression) {
    const result = await this.send("Runtime.evaluate", {
      expression,
      returnByValue: true,
      awaitPromise: true,
    });
    if (result.exceptionDetails) {
      const detail = result.exceptionDetails;
      const message = detail.exception?.description ?? detail.text ?? "未知页面异常";
      throw new Error(`页面求值失败: ${message}`);
    }
    return result.result?.value;
  }

  /** 等一次 `Page.loadEventFired`（带上限，避免无响应时挂死）。 */
  #nextLoad(timeoutMs = 20000) {
    return new Promise((resolve) => {
      const off = this.#connection.on((message) => {
        if (message.sessionId !== this.#sessionId) return;
        if (message.method === "Page.loadEventFired") {
          off();
          resolve();
        }
      });
      setTimeout(() => {
        off();
        resolve();
      }, timeoutMs);
    });
  }

  /**
   * 导航到 `url`，**保证是完整文档加载**。
   *
   * 中文
   * ----
   * 应用是 hash 路由，测试里的 URL 往往只有 hash 不同。这种情况下 `Page.navigate`
   * 走的是**同文档导航**：浏览器不重新加载文档，**组件 state 全部保留**。
   *
   * 后果实测过：在一个 page 里循环 goto 六个页面测「切语言后还剩多少中文」，而
   * locale 是 `useState`（不在 URL 里），于是第 2 页起就带着第 1 页切好的语言，
   * 整份测量报告都是污染的。看起来却「每个页面测出来都对」。
   *
   * 修法是先跳 `about:blank` 再跳目标，强制一次真实的文档替换。代价是多一次导航，
   * 换来「每个用例都从已知初始状态开始」。
   */
  async goto(url, { waitFor } = {}) {
    const blanked = this.#nextLoad();
    await this.send("Page.navigate", { url: "about:blank" });
    await blanked;

    const loaded = this.#nextLoad();
    await this.send("Page.navigate", { url });
    await loaded;

    if (waitFor) await this.waitFor(waitFor);
  }

  /**
   * 轮询直到 `expression` 为真值。
   *
   * 中文
   * ----
   * 用表达式轮询而不是固定 sleep：既更快，又不会在 CI 慢机上假阴性。
   * 失败时把最后一次的真实取值一并报出，避免只看到「超时」而无法定位。
   */
  async waitFor(expression, { timeoutMs = 8000, label } = {}) {
    const deadline = Date.now() + timeoutMs;
    let last;
    while (Date.now() < deadline) {
      last = await this.#evaluate(expression);
      if (last) return last;
      await delay(40);
    }
    throw new Error(
      `等待条件超时: ${label ?? expression}\n  表达式: ${expression}\n  最后取值: ${JSON.stringify(last)}`,
    );
  }

  /**
   * 定位、校验并点击目标元素。
   *
   * 中文
   * ----
   * 走 `Input.dispatchMouseEvent` 而不是在页面里调 `element.click()`：后者绕过命中
   * 测试与事件构造，只能验证「函数被调用」；前者才走完整派发链路，能暴露遮挡、
   * `pointer-events` 失效、事件被 `stopPropagation` 等真实问题。
   *
   * 派发前用 `document.elementFromPoint` **复核坐标处命中的就是目标**，不命中就
   * 重新滚动、重新测量再试（上限 4 次）。这一步是被实测逼出来的：
   *
   * - 应用 CSS 开了 `scroll-behavior: smooth`，`navigate()` 里也调
   *   `window.scrollTo({behavior:"smooth"})`。「量坐标 → 派发事件」之间页面仍在
   *   移动，于是点「熔断降级」实际命中「系统保护」——正好偏一行，即一个选项高度。
   * - 单纯把等待时间调大只能降低概率，不能消除；命中校验把它变成确定性重试。
   *
   * 滚动显式要求 `behavior: "instant"`，用来覆盖 CSS 的 `scroll-behavior: smooth`。
   */
  async #clickResolved(resolveExpr, describe) {
    await this.#waitScrollIdle();
    let last = null;
    for (let attempt = 1; attempt <= 4; attempt += 1) {
      const found = await this.#evaluate(`(() => {
        const node = (${resolveExpr});
        if (!node) return null;
        node.scrollIntoView({ block: "center", behavior: "instant" });
        const r = node.getBoundingClientRect();
        const x = r.x + r.width / 2;
        const y = r.y + r.height / 2;
        const hit = document.elementFromPoint(x, y);
        return {
          x, y, w: r.width, h: r.height,
          onTarget: !!hit && (hit === node || node.contains(hit)),
        };
      })()`);
      last = found;
      if (found && found.w > 0 && found.h > 0 && found.onTarget) {
        const base = { x: found.x, y: found.y, button: "left", clickCount: 1, buttons: 1 };
        await this.send("Input.dispatchMouseEvent", { type: "mouseMoved", ...base, buttons: 0 });
        await this.send("Input.dispatchMouseEvent", { type: "mousePressed", ...base });
        await this.send("Input.dispatchMouseEvent", { type: "mouseReleased", ...base, buttons: 0 });
        return found;
      }
      // 命中不符：页面可能仍在平滑滚动，稍等再试
      await delay(70);
    }
    if (!last) throw new Error(`点击目标不存在: ${describe}`);
    throw new Error(`点击目标在 4 次尝试内始终无法命中: ${describe}（尺寸 ${last.w}x${last.h}）`);
  }

  /**
   * 等页面滚动位置稳定下来。
   *
   * 中文
   * ----
   * 应用 CSS 开了 `scroll-behavior: smooth`，且 `navigate()` 里显式调用
   * `window.scrollTo({ top: 0, behavior: "smooth" })`。因此**点击派发之后页面仍在
   * 移动**：一次选项选择 → hash 变更 → 导航触发平滑回顶 → 紧接着再点下拉框，
   * 此时 mousedown 落点已经偏了。
   *
   * 这解释了为什么「量坐标 + `elementFromPoint` 校验」仍然不够：校验发生在派发
   * 之前，动画在派发与校验之间继续跑。实测症状是第二次点 combobox 打不开下拉，
   * 看上去像应用 bug，其实是点击落在了滚动中的错误位置。
   *
   * 判据取 `window.scrollY` 连续两次采样相同；上限 1.5s，避免真的卡住时无限等。
   */
  async #waitScrollIdle({ timeoutMs = 1500, intervalMs = 60 } = {}) {
    const deadline = Date.now() + timeoutMs;
    let previous = await this.#evaluate("window.scrollY");
    while (Date.now() < deadline) {
      await delay(intervalMs);
      const current = await this.#evaluate("window.scrollY");
      if (current === previous) return;
      previous = current;
    }
  }

  /** 按 CSS 选择器点击第 `index` 个匹配元素。 */
  async click(selector, { index = 0 } = {}) {
    await this.#clickResolved(
      `document.querySelectorAll(${JSON.stringify(selector)})[${index}] ?? null`,
      `${selector}[${index}]`,
    );
  }

  /** 按可见文字点击；用于没有稳定 test id 的控件。 */
  async clickByText(text, selector = "button, a, [role='tab'], [role='button'], label, [role='option']") {
    await this.#clickResolved(
      `[...document.querySelectorAll(${JSON.stringify(selector)})]
         .find((n) => (n.textContent ?? "").trim().includes(${JSON.stringify(text)})) ?? null`,
      `文字为「${text}」的 ${selector}`,
    );
  }

  /**
   * 向输入框插入文本。
   *
   * 中文
   * ----
   * 用 `Input.insertText` 而不是逐字符 `dispatchKeyEvent`：后者只发 key 事件，
   * 不会产生浏览器原生的 `input` 事件，**React 受控组件因此收不到 onChange**，
   * 输入框的值不会变。踩过这个坑：搜索框看起来「已输入」，但目录过滤没发生，
   * 空态永远不出现，一度被误判成应用缺陷。
   */
  async type(selector, value) {
    await this.click(selector);
    await this.send("Input.insertText", { text: value });
    // 让 React 完成一次受控更新再返回，避免调用方紧接着读 DOM 时读到旧值。
    await delay(60);
  }

  text(selector = "body") {
    return this.#evaluate(`(document.querySelector(${JSON.stringify(selector)})?.textContent ?? "")`);
  }

  count(selector) {
    return this.#evaluate(`document.querySelectorAll(${JSON.stringify(selector)}).length`);
  }

  value(selector) {
    return this.#evaluate(`(document.querySelector(${JSON.stringify(selector)})?.value ?? null)`);
  }

  hash() {
    return this.#evaluate("window.location.hash");
  }

  eval(expression) {
    return this.#evaluate(expression);
  }

  /**
   * 整页 HTML（含 `<html>` 根元素）。
   *
   * 中文
   * ----
   * 视觉基线工具用这个取代 `chrome --dump-dom`。区别不只是「少一次进程启动」：
   * CDP 模式下浏览器**先停在 `about:blank` 再导航**，而 `--dump-dom <URL>` 是从
   * 命令行直接导航 —— 实测后者在全新 `--user-data-dir` 下必然挂起（40 秒超时），
   * 前者稳定。
   *
   * 取的是 `documentElement.outerHTML` 而非 `DOM.getOuterHTML`：后者需要先
   * `DOM.getDocument` 再带 nodeId 递归取，会丢 doctype，且节点被 React 替换后
   * nodeId 可能失效。
   */
  async html() {
    // 必须自己补 DOCTYPE：`documentElement.outerHTML` 只含根元素本身，
    // 而 `chrome --dump-dom` 会输出 `<!DOCTYPE html>`。少了它，归一化后的 DOM
    // 与既有基线**每个用例都差这一个前缀**，29 个全不等价。
    const doctype = await this.#evaluate("document.doctype?.name ?? ''");
    const html = await this.#evaluate("document.documentElement.outerHTML");
    return doctype ? `<!DOCTYPE ${doctype}>\n${html}` : html;
  }

  /**
   * 整页截图（PNG 字节）。
   *
   * 中文
   * ----
   * 用 `Page.captureScreenshot` 而不是 `chrome --screenshot`，理由同 {@link html}。
   * `captureBeyondViewport: false` 是关键：基线要的是**视口内**那一屏，开启它会
   * 把 `content-visibility: auto` 的屏外内容也画进来，与既有基线不可比。
   */
  async screenshot() {
    const { data } = await this.send("Page.captureScreenshot", {
      format: "png",
      captureBeyondViewport: false,
      fromSurface: true,
    });
    return Buffer.from(data, "base64");
  }

  /**
   * 清掉该源的存储（localStorage / sessionStorage / cookie）。
   *
   * 中文
   * ----
   * CDP 模式下浏览器实例被复用，存储会**跨用例保留**；而每次全新 profile 时是空的。
   * 两者不等价：语言偏好与演示会话都存在 `localStorage` 里。捕获前清一次，
   * 才能让每个用例都从「未设置过偏好」的初始状态开始，与既有基线一致。
   */
  /**
   * 等布局与图表尺寸稳定。
   *
   * 中文
   * ----
   * `--dump-dom` 模式靠 `--virtual-time-budget=4000` 给渲染足够时间；CDP 模式没有
   * 这个机制，直接截图会抓到**图表还没 resize 完**的状态（实测 Nivo 的 `<svg>`
   * 宽度是 466 而非 702），于是同一份代码在两种模式下给出的 DOM 不一样。
   *
   * 判据是「几个 SVG 的 width/height 连续两次采样相同」——图表尺寸是最后一个稳定
   * 下来的量，它不再变就意味着布局与 ResizeObserver 都收敛了。
   */
  async waitForStableLayout({ samples = 2, intervalMs = 120, timeoutMs = 5000 } = {}) {
    const probe = `(() => {
      const svgs = [...document.querySelectorAll("svg[role='img']")]
        .map((el) => el.getAttribute("width") + "x" + el.getAttribute("height")).join("|");
      return document.readyState + "#" + svgs;
    })()`;
    const deadline = Date.now() + timeoutMs;
    let previous = await this.#evaluate(probe);
    let stable = 0;
    while (Date.now() < deadline) {
      await delay(intervalMs);
      const current = await this.#evaluate(probe);
      stable = current === previous ? stable + 1 : 0;
      previous = current;
      if (stable >= samples) return true;
    }
    return false;
  }

  async clearStorage(origin) {
    await this.send("Storage.clearDataForOrigin", {
      origin,
      storageTypes: "local_storage,session_storage,cookies",
    });
  }
}

/**
 * 启动 headless Chrome 并接上 CDP。
 *
 * 中文
 * ----
 * 返回值自带 `close()`，务必在测试结束调用：否则 Chrome 进程会变成孤儿，
 * 下次 `npm run dev` 的端口探测和后续基线捕获都会受干扰。
 */
export async function launchBrowser({ viewport = { width: 1280, height: 900 } } = {}) {
  const userDataDir = mkdtempSync(path.join(tmpdir(), "sen-e2e-"));
  const child = spawn(
    CHROME,
    [
      "--headless=new",
      "--disable-gpu",
      "--hide-scrollbars",
      "--no-sandbox",
      "--no-first-run",
      "--no-default-browser-check",
      "--disable-extensions",
      "--disable-background-timer-throttling",
      "--remote-debugging-port=0",
      `--user-data-dir=${userDataDir}`,
      "about:blank",
    ],
    { stdio: ["ignore", "pipe", "pipe"] },
  );

  // Chrome 崩溃时立刻抛错，而不是等到端口超时后给出误导性的连接错误。
  let crashed = null;
  child.on("exit", (code) => {
    crashed = new Error(`Chrome 提前退出，code=${code}`);
  });

  try {
    const activePort = await waitForFile(path.join(userDataDir, "DevToolsActivePort"));
    const port = activePort.split("\n")[0].trim();
    const response = await fetch(`http://127.0.0.1:${port}/json/version`);
    const { webSocketDebuggerUrl } = await response.json();

    const socket = new WebSocket(webSocketDebuggerUrl);
    await new Promise((resolve, reject) => {
      socket.addEventListener("open", resolve, { once: true });
      socket.addEventListener("error", () => reject(new Error("CDP WebSocket 连接失败")), {
        once: true,
      });
    });

    const connection = new Connection(socket);

    return {
      connection,
      async newPage() {
        const { targetId } = await connection.send("Target.createTarget", { url: "about:blank" });
        const { sessionId } = await connection.send("Target.attachToTarget", {
          targetId,
          flatten: true,
        });
        const page = new Page(connection, sessionId, targetId);
        await page.send("Page.enable");
        await page.send("Runtime.enable");
        await page.send("Emulation.setDeviceMetricsOverride", {
          width: viewport.width,
          height: viewport.height,
          deviceScaleFactor: 1,
          mobile: false,
        });
        connection.on((message) => {
          if (message.sessionId !== sessionId) return;
          if (message.method === "Runtime.consoleAPICalled" && message.params.type === "error") {
            page.recordConsoleError(
              message.params.args.map((a) => a.value ?? a.description ?? "").join(" "),
            );
          }
          if (message.method === "Runtime.exceptionThrown") {
            page.recordConsoleError(
              message.params.exceptionDetails.exception?.description ??
                message.params.exceptionDetails.text,
            );
          }
        });
        return page;
      },
      async close() {
        connection.close();
        child.kill("SIGTERM");
        // 给 Chrome 一点时间落盘 profile，避免强杀留下损坏的 user-data-dir。
        await delay(150);
        if (!child.killed) child.kill("SIGKILL");
        // 子进程句柄默认持有事件循环。不 unref 的话 `node --test` 跑完全部用例后
        // 会一直等 Chrome 退出——实测每轮多挂约 19 秒。
        child.unref();
        // 只清理本工具自己创建的临时 profile；前缀不符就放弃，绝不误删别处。
        if (path.basename(userDataDir).startsWith("sen-e2e-")) {
          try {
            rmSync(userDataDir, { recursive: true, force: true });
          } catch {
            // 临时目录清理失败不应让测试失败。
          }
        }
      },
      get crashed() {
        return crashed;
      },
    };
  } catch (error) {
    child.kill("SIGKILL");
    throw crashed ?? error;
  }
}

export const E2E_BASE_URL = process.env.BASE_URL ?? "http://localhost:5173";
