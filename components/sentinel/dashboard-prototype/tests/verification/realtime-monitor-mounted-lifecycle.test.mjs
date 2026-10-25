import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { Window } from "happy-dom";
import { createInstance } from "i18next";
import { AppError, AppErrorKind } from "@richie696/react-framework";
import { createServer } from "vite";

test("F5.6 mounted realtime page owns one poll loop through StrictMode replay and releases it on pause/unmount", async () => {
  const browser = new Window({ url: "http://localhost/realtime" });
  const priorGlobals = new Map();
  const installGlobal = (name, value) => {
    priorGlobals.set(name, Object.getOwnPropertyDescriptor(globalThis, name));
    Object.defineProperty(globalThis, name, { configurable: true, writable: true, value });
  };
  for (const name of [
    "window",
    "document",
    "navigator",
    "HTMLElement",
    "Element",
    "Node",
    "Event",
    "MutationObserver",
    "requestAnimationFrame",
    "cancelAnimationFrame",
  ])
    installGlobal(name, browser[name] ?? browser.document);
  installGlobal("IS_REACT_ACT_ENVIRONMENT", true);

  const activePollTimers = new Map();
  const realSetInterval = globalThis.setInterval;
  const realClearInterval = globalThis.clearInterval;
  globalThis.setInterval = (callback, delay, ...args) => {
    const timer = realSetInterval(callback, delay, ...args);
    if (delay === 500) activePollTimers.set(timer, delay);
    return timer;
  };
  globalThis.clearInterval = (timer) => {
    activePollTimers.delete(timer);
    return realClearInterval(timer);
  };

  let vite;
  let root;
  let mounted = false;
  let act;
  let monitor;
  let unsubscribeCount = 0;
  let subscribeCount = 0;
  const requests = [];
  try {
    vite = await createServer({
      configFile: false,
      root: process.cwd(),
      appType: "custom",
      optimizeDeps: { noDiscovery: true, include: [] },
      server: { middlewareMode: true, hmr: false, ws: false },
    });
    const [
      { createRealtimeMonitor },
      { validRealtimeSelection },
      { LiveMonitoringPage },
      { AstryxProvider },
      React,
      { createRoot },
      { I18nextProvider },
    ] = await Promise.all([
      vite.ssrLoadModule("/src/features/realtime/application/realtimeMonitor.ts"),
      vite.ssrLoadModule("/src/features/realtime/model/monitoring.ts"),
      vite.ssrLoadModule("/src/features/realtime/ui/LiveMonitoringPage.tsx"),
      vite.ssrLoadModule("/src/app/providers/AstryxProvider.tsx"),
      import("react"),
      import("react-dom/client"),
      import("react-i18next"),
    ]);
    act = React.act;

    const realtimeMessages = JSON.parse(
      await readFile(new URL("../../src/app/i18n/messages/en-US/realtime.json", import.meta.url)),
    );
    const observationMessages = JSON.parse(
      await readFile(
        new URL("../../src/app/i18n/messages/en-US/observation.json", import.meta.url),
      ),
    );
    const applicationsMessages = JSON.parse(
      await readFile(
        new URL("../../src/app/i18n/messages/en-US/applications.json", import.meta.url),
      ),
    );
    const shellMessages = JSON.parse(
      await readFile(new URL("../../src/app/i18n/messages/en-US/shell.json", import.meta.url)),
    );
    const i18n = createInstance();
    await i18n.init({
      lng: "en-US",
      fallbackLng: false,
      nsSeparator: false,
      resources: {
        "en-US": {
          translation: {
            ...realtimeMessages,
            ...observationMessages,
            ...applicationsMessages,
            ...shellMessages,
          },
        },
      },
    });
    const { loadAstryxLocaleCatalog } = await vite.ssrLoadModule(
      "/src/app/i18n/astryxLocaleCatalogs.ts",
    );
    await loadAstryxLocaleCatalog("en-US");

    const selection = {
      context: {
        environmentId: "test-environment",
        appId: null,
        instanceId: null,
        resource: null,
        scope: "fleet",
        window: { fromMs: Date.UTC(2026, 9, 1), toMs: Date.UTC(2026, 9, 1, 1) },
      },
      metrics: ["http_qps"],
      stepMs: 60_000,
      windowMode: "rolling",
    };
    assert.equal(validRealtimeSelection(selection), true, "the mounted route selection is valid");
    const monitorOwner = createRealtimeMonitor(
      {
        readMetrics: (_query, signal) => {
          const request = { signal };
          requests.push(request);
          return new Promise((_resolve, reject) => {
            signal.addEventListener(
              "abort",
              () => reject(new AppError(AppErrorKind.CANCELLED, "Synthetic monitor cleanup")),
              { once: true },
            );
          });
        },
      },
      undefined,
      { intervalMs: 500, timeoutMs: 5_000 },
    );
    monitor = {
      ...monitorOwner,
      start(input) {
        monitorOwner.start(input);
      },
      cancel() {
        monitorOwner.cancel();
      },
      subscribe(listener) {
        subscribeCount += 1;
        const unsubscribe = monitorOwner.subscribe(listener);
        return () => {
          unsubscribeCount += 1;
          unsubscribe();
        };
      },
    };
    const host = browser.document.createElement("main");
    browser.document.body.append(host);

    const render = async () => {
      root = createRoot(host);
      mounted = true;
      await React.act(async () => {
        root.render(
          React.createElement(
            React.StrictMode,
            null,
            React.createElement(
              I18nextProvider,
              { i18n },
              React.createElement(
                AstryxProvider,
                null,
                React.createElement(LiveMonitoringPage, {
                  monitor,
                  selection,
                  onSelectionChange: () => {},
                  environments: [{ id: "test-environment", name: "Test environment" }],
                  applications: [],
                  instances: [],
                  selectedInstanceId: null,
                  instanceCatalogLoading: false,
                  queryReady: true,
                  instanceTargetMissing: false,
                  instanceTargetUnsupported: false,
                }),
              ),
            ),
          ),
        );
        await Promise.resolve();
        await Promise.resolve();
      });
      await React.act(async () => new Promise((resolve) => setTimeout(resolve, 10)));
    };

    await render();
    assert.equal(
      activePollTimers.size,
      1,
      "StrictMode setup-cleanup-setup must retain exactly one active polling timer",
    );
    assert.equal(
      requests.length,
      1,
      "the StrictMode probe's scheduled first tick is canceled before it can issue duplicate HTTP work",
    );
    assert.equal(requests[0].signal.aborted, false, "the replayed setup owns the active read");
    assert.equal(
      subscribeCount - unsubscribeCount,
      1,
      "only one React store subscription survives replay",
    );
    await new Promise((resolve) => setTimeout(resolve, 550));
    assert.equal(requests.length, 1, "a slow active read is not overlapped on later polling ticks");
    assert.equal(activePollTimers.size, 1, "the single polling timer remains owned while mounted");

    await React.act(async () => monitorOwner.pause());
    assert.equal(activePollTimers.size, 0, "pause clears the polling timer immediately");
    assert.equal(requests[0].signal.aborted, true, "pause aborts the in-flight request");
    const pausedRequestCount = requests.length;
    await new Promise((resolve) => setTimeout(resolve, 650));
    assert.equal(requests.length, pausedRequestCount, "paused monitoring does not poll again");

    await React.act(async () => {
      monitorOwner.resume();
      await new Promise((resolve) => setTimeout(resolve, 10));
    });
    assert.equal(activePollTimers.size, 1, "resume acquires a single replacement timer");
    assert.equal(
      requests.length,
      pausedRequestCount + 1,
      "resume immediately reads the latest window",
    );
    assert.equal(requests.at(-1).signal.aborted, false);

    await React.act(async () => root.unmount());
    mounted = false;
    assert.equal(activePollTimers.size, 0, "unmount clears the active polling timer");
    assert.equal(requests.at(-1).signal.aborted, true, "unmount aborts the active HTTP read");
    assert.equal(subscribeCount, unsubscribeCount, "unmount releases the external-store listener");
    const unmountedRequestCount = requests.length;
    await new Promise((resolve) => setTimeout(resolve, 650));
    assert.equal(requests.length, unmountedRequestCount, "no requests occur after unmount");

    await render();
    assert.equal(activePollTimers.size, 1, "a real remount can safely reacquire the owner");
    assert.equal(requests.at(-1).signal.aborted, false, "remounted page owns a fresh request");
    await React.act(async () => root.unmount());
    mounted = false;
    assert.equal(activePollTimers.size, 0);
    assert.equal(subscribeCount, unsubscribeCount);
    monitorOwner.dispose();
    host.remove();
  } finally {
    if (root && mounted && act) await act(async () => root.unmount());
    monitor?.dispose();
    if (vite) await vite.close();
    globalThis.setInterval = realSetInterval;
    globalThis.clearInterval = realClearInterval;
    browser.happyDOM.abort();
    browser.close();
    for (const [name, descriptor] of priorGlobals) {
      if (descriptor) Object.defineProperty(globalThis, name, descriptor);
      else delete globalThis[name];
    }
  }
});
