/**
 * 零依赖 Chromium DevTools Protocol 客户端。
 *
 * 中文
 * ----
 * 视觉基线工具（`tests/visual/capture-baseline.mjs`）只验证首屏渲染，不能点击。组件重写里有真实缺陷
 * 只在交互后才暴露：状态写入路径、受控回环、过期结果覆盖、Effect 清理。
 * 纯函数测试同样证明不了这些——skill 明确写了「普通函数测试不证明 UI 生命周期正确」。
 *
 * 因此这里补一条**交互驱动**能力。不引入 puppeteer/playwright：
 * Node 22+ 内置 `WebSocket`，通过 loopback DevTools endpoint 连接隔离启动的 Edge。
 * Edge 由 `scripts/test/run-edge-e2e.mjs` 使用临时 profile 启动；本模块只连接，绝不启动浏览器。
 *
 * 用法：
 * ```js
 * const browser = await connectE2EBrowser();
 * const page = await browser.newPage();
 * await page.goto("http://localhost:5173/#/rules");
 * await page.clickByText("降级");
 * console.log(await page.text("body"));
 * await browser.close();
 * ```
 */
import { setTimeout as delay } from "node:timers/promises";

/**
 * 一个 CDP 会话。
 *
 * 中文
 * ----
 * 用扁平会话（`flatten: true`）：每条命令带 `sessionId` 直接路由到目标页，
 * 不需要自己维护 targetId -> socket 的多路复用树。单页场景下这层复杂度不划算。
 */
export class Connection {
  #socket;
  #nextId = 1;
  #pending = new Map();
  #listeners = new Set();
  #closed = false;
  #timeoutMs;

  constructor(socket, { timeoutMs = 20000 } = {}) {
    this.#socket = socket;
    this.#timeoutMs = timeoutMs;
    socket.addEventListener("message", (event) => this.#onMessage(event.data));
    socket.addEventListener("close", () => {
      this.#closed = true;
      for (const { reject } of this.#pending.values()) {
        reject(new Error("CDP 连接已关闭"));
      }
      this.#pending.clear();
      this.#listeners.clear();
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
      const timeout = setTimeout(() => {
        this.#pending.delete(id);
        reject(new Error(`CDP command timed out: ${method}`));
      }, this.#timeoutMs);
      const settle = (callback) => (value) => {
        clearTimeout(timeout);
        callback(value);
      };
      this.#pending.set(id, { resolve: settle(resolve), reject: settle(reject) });
      try {
        this.#socket.send(JSON.stringify(payload));
      } catch (error) {
        this.#pending.delete(id);
        clearTimeout(timeout);
        reject(error);
      }
    });
  }

  on(listener) {
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  }

  close() {
    this.#closed = true;
    for (const { reject } of this.#pending.values()) reject(new Error("CDP connection closed"));
    this.#pending.clear();
    this.#listeners.clear();
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
          clearTimeout(timer);
          off();
          resolve();
        }
      });
      const timer = setTimeout(() => {
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
    // Move both vertical and horizontal scroll containers directly, avoiding
    // CSS smooth-scroll animations. Tables intentionally own horizontal
    // overflow on narrow layouts, so scrolling only the document can leave a
    // real action button outside the viewport even though its row is visible.
    await this.#evaluate(`(() => {
      const node = (${resolveExpr});
      if (!node) return false;
      const scrollable = [];
      for (let parent = node.parentElement; parent; parent = parent.parentElement) {
        const style = getComputedStyle(parent);
        if (
          (parent.scrollHeight > parent.clientHeight + 1 && /(auto|scroll|hidden|overlay)/.test(style.overflowY)) ||
          (parent.scrollWidth > parent.clientWidth + 1 && /(auto|scroll|hidden|overlay)/.test(style.overflowX))
        ) {
          scrollable.push(parent);
        }
      }
      const root = document.scrollingElement;
      if (root && (
        root.scrollHeight > root.clientHeight + 1 ||
        root.scrollWidth > root.clientWidth + 1
      )) scrollable.push(root);
      for (const container of scrollable) {
        const rect = node.getBoundingClientRect();
        const bounds = container === root
          ? { top: 0, height: innerHeight, left: 0, width: innerWidth }
          : (() => {
              const parentRect = container.getBoundingClientRect();
              return {
                top: parentRect.top + container.clientTop,
                height: container.clientHeight,
                left: parentRect.left + container.clientLeft,
                width: container.clientWidth,
              };
            })();
        if (container.scrollHeight > container.clientHeight + 1) {
          const deltaY = rect.top + rect.height / 2 - (bounds.top + bounds.height / 2);
          if (Math.abs(deltaY) > 1) container.scrollTop += deltaY;
        }
        if (container.scrollWidth > container.clientWidth + 1) {
          const right = bounds.left + bounds.width;
          const deltaX = rect.left < bounds.left
            ? rect.left - bounds.left
            : rect.right > right
              ? rect.right - right
              : 0;
          if (Math.abs(deltaX) > 1) container.scrollLeft += deltaX;
        }
      }
      return true;
    })()`);

    let last = null;
    let previousPosition = null;
    const deadline = Date.now() + 3000;
    while (Date.now() < deadline) {
      const found = await this.#evaluate(`(() => {
        const node = (${resolveExpr});
        if (!node) return null;
        const r = node.getBoundingClientRect();
        const x = r.x + r.width / 2;
        const y = r.y + r.height / 2;
        const hit = document.elementFromPoint(x, y);
        return {
          x, y, w: r.width, h: r.height,
          visible: r.bottom > 0 && r.right > 0 && r.top < innerHeight && r.left < innerWidth,
          onTarget: !!hit && (hit === node || node.contains(hit)),
          hit: hit ? {
            tag: hit.tagName,
            id: hit.id,
            classes: typeof hit.className === "string" ? hit.className : "",
            text: (hit.textContent ?? "").trim().slice(0, 100),
          } : null,
          scrollY: window.scrollY,
          viewport: { width: innerWidth, height: innerHeight },
          document: {
            root: document.scrollingElement?.tagName ?? null,
            scrollHeight: document.scrollingElement?.scrollHeight ?? null,
            clientHeight: document.scrollingElement?.clientHeight ?? null,
            scrollTop: document.scrollingElement?.scrollTop ?? null,
            body: document.body ? {
              height: getComputedStyle(document.body).height,
              position: getComputedStyle(document.body).position,
              overflow: getComputedStyle(document.body).overflow,
              scrollHeight: document.body.scrollHeight,
              clientHeight: document.body.clientHeight,
            } : null,
          },
          ancestors: (() => {
            const rows = [];
            for (let parent = node.parentElement; parent && rows.length < 16; parent = parent.parentElement) {
              const style = getComputedStyle(parent);
              rows.push({
                tag: parent.tagName,
                id: parent.id,
                classes: typeof parent.className === "string" ? parent.className : "",
                position: style.position,
                height: style.height,
                overflowY: style.overflowY,
                overflowX: style.overflowX,
                scrollTop: parent.scrollTop,
                scrollLeft: parent.scrollLeft,
                scrollHeight: parent.scrollHeight,
                scrollWidth: parent.scrollWidth,
                clientHeight: parent.clientHeight,
                clientWidth: parent.clientWidth,
              });
            }
            return rows;
          })(),
        };
      })()`);
      last = found;
      if (found && found.w > 0 && found.h > 0 && found.visible && found.onTarget) {
        const position = { x: found.x, y: found.y };
        if (
          previousPosition &&
          Math.abs(previousPosition.x - position.x) < 0.5 &&
          Math.abs(previousPosition.y - position.y) < 0.5
        ) {
          const base = { ...position, button: "left", clickCount: 1, buttons: 1 };
          await this.send("Input.dispatchMouseEvent", { type: "mousePressed", ...base });
          await this.send("Input.dispatchMouseEvent", {
            type: "mouseReleased",
            ...base,
            buttons: 0,
          });
          return found;
        }
        // Hover styles and async layout can move a target after pointer movement.
        // Require two consecutive hit-tested measurements at the same point.
        await this.send("Input.dispatchMouseEvent", {
          type: "mouseMoved",
          ...position,
          button: "none",
          buttons: 0,
        });
        previousPosition = position;
      } else {
        previousPosition = null;
      }
      // The target may still be moving due to the page's CSS smooth-scroll rule.
      await delay(70);
    }
    if (!last) throw new Error(`点击目标不存在: ${describe}`);
    throw new Error(`滚动后点击目标仍无法命中: ${describe}（状态 ${JSON.stringify(last)}）`);
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
  async clickByText(
    text,
    selector = "button, a, [role='tab'], [role='button'], label, [role='option']",
  ) {
    await this.#clickResolved(
      `[...document.querySelectorAll(${JSON.stringify(selector)})]
         .find((n) => {
           const rect = n.getBoundingClientRect();
           const style = getComputedStyle(n);
           return (n.textContent ?? "").trim().includes(${JSON.stringify(text)}) &&
             rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" &&
             style.display !== "none" && style.pointerEvents !== "none";
         }) ?? null`,
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
    return this.#evaluate(
      `(document.querySelector(${JSON.stringify(selector)})?.textContent ?? "")`,
    );
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

/** Resolve an HTTP DevTools origin or accept an explicit WebSocket endpoint. */
async function resolveDevToolsWebSocketUrl(endpoint) {
  let url;
  try {
    url = new URL(endpoint);
  } catch {
    throw new Error("SENTINEL_E2E_CDP_URL must be a valid loopback DevTools URL");
  }
  const hostname = url.hostname.toLowerCase();
  if (!["localhost", "127.0.0.1", "[::1]", "::1"].includes(hostname)) {
    throw new Error("E2E DevTools endpoint must be loopback-only");
  }
  if (url.protocol === "ws:" || url.protocol === "wss:") return url.href;
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error("SENTINEL_E2E_CDP_URL must use http(s) or ws(s)");
  }

  url.pathname = "/json/version";
  url.search = "";
  url.hash = "";
  let response;
  try {
    response = await fetch(url, { signal: AbortSignal.timeout(5000) });
  } catch {
    throw new Error("E2E DevTools discovery request failed");
  }
  if (!response.ok) throw new Error(`E2E DevTools discovery returned HTTP ${response.status}`);
  let document;
  try {
    document = await response.json();
  } catch {
    throw new Error("E2E DevTools discovery response was invalid");
  }
  if (typeof document.webSocketDebuggerUrl !== "string") {
    throw new Error("E2E DevTools endpoint did not provide a WebSocket URL");
  }
  const socketUrl = new URL(document.webSocketDebuggerUrl);
  if (!["localhost", "127.0.0.1", "[::1]", "::1"].includes(socketUrl.hostname.toLowerCase())) {
    throw new Error("E2E DevTools WebSocket endpoint must be loopback-only");
  }
  return socketUrl.href;
}

/** Connect to a loopback-only DevTools endpoint; never starts a browser process. */
export async function connectE2EBrowser({
  viewport = { width: 1280, height: 900 },
  cdpEndpoint = process.env.SENTINEL_E2E_CDP_URL,
} = {}) {
  if (!cdpEndpoint) {
    throw new Error(
      "SENTINEL_E2E_CDP_URL is required; run tests through the isolated Edge launcher.",
    );
  }
  const socket = new WebSocket(await resolveDevToolsWebSocketUrl(cdpEndpoint));
  await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error("E2E CDP WebSocket timed out")), 5000);
    socket.addEventListener(
      "open",
      () => {
        clearTimeout(timeout);
        resolve();
      },
      { once: true },
    );
    socket.addEventListener(
      "error",
      () => {
        clearTimeout(timeout);
        reject(new Error("E2E CDP WebSocket connection failed"));
      },
      { once: true },
    );
  });

  const connection = new Connection(socket);
  const pages = new Set();
  return {
    connection,
    async newPage() {
      const { targetId } = await connection.send("Target.createTarget", { url: "about:blank" });
      const { sessionId } = await connection.send("Target.attachToTarget", {
        targetId,
        flatten: true,
      });
      const page = new Page(connection, sessionId, targetId);
      pages.add(page);
      await page.send("Page.enable");
      await page.send("Runtime.enable");
      if (process.env.SENTINEL_E2E_MOCK_ADMIN_BASELINE === "1") {
        const origin = new URL(E2E_BASE_URL).origin;
        await page.send("Page.addScriptToEvaluateOnNewDocument", {
          source: `if(location.origin===${JSON.stringify(origin)}&&!location.hash.startsWith('#/setup')){if(localStorage.getItem('sentinel.mock.initialized')===null)localStorage.setItem('sentinel.mock.initialized','true');if(localStorage.getItem('sentinel.mock.role')===null)localStorage.setItem('sentinel.mock.role','admin');}`,
        });
      }
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
            message.params.args
              .map((argument) => argument.value ?? argument.description ?? "")
              .join(" "),
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
      await Promise.all(
        [...pages].map(async (page) => {
          try {
            await page.close();
          } catch {
            // The test may already have closed its page; only its own targets are affected.
          }
        }),
      );
      connection.close();
    },
    get crashed() {
      return null;
    },
  };
}

/** @deprecated Use connectE2EBrowser; retained while existing E2E specs migrate. */
export const connectIabBrowser = connectE2EBrowser;

export const E2E_BASE_URL = process.env.BASE_URL ?? "http://localhost:5173";
