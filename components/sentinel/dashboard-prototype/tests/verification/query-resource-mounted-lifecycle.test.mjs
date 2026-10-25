import assert from "node:assert/strict";
import { test } from "node:test";
import { Window } from "happy-dom";
import { createServer } from "vite";

test("F5.6 mounted query Hook keeps one StrictMode subscription and releases it on replacement/unmount", async () => {
  const browser = new Window({ url: "http://localhost/" });
  const priorGlobals = new Map();
  const installGlobal = (name, value) => {
    priorGlobals.set(name, Object.getOwnPropertyDescriptor(globalThis, name));
    Object.defineProperty(globalThis, name, { configurable: true, writable: true, value });
  };
  installGlobal("window", browser);
  installGlobal("document", browser.document);
  installGlobal("navigator", browser.navigator);
  installGlobal("HTMLElement", browser.HTMLElement);
  installGlobal("Node", browser.Node);
  installGlobal("Event", browser.Event);
  installGlobal("MutationObserver", browser.MutationObserver);
  installGlobal("IS_REACT_ACT_ENVIRONMENT", true);

  let vite;
  let root;
  let mounted = false;
  let act;
  try {
    vite = await createServer({
      configFile: false,
      root: process.cwd(),
      appType: "custom",
      optimizeDeps: { noDiscovery: true, include: [] },
      server: { middlewareMode: true, hmr: false, ws: false },
    });
    const [{ QueryLifecycleProbe, createQueryResource }, React, { createRoot }] = await Promise.all(
      [
        vite.ssrLoadModule("/tests/e2e/probes/QueryLifecycleProbe.tsx"),
        import("react"),
        import("react-dom/client"),
      ],
    );
    act = React.act;
    const pendingReads = [];
    const base = createQueryResource({
      keyOf: ({ session, application }) => `${session}:${application}`,
      read: (_query, signal) => new Promise((resolve) => pendingReads.push({ resolve, signal })),
      classify: () => "ready",
    });
    const listeners = new Set();
    let subscribeCalls = 0;
    let unsubscribeCalls = 0;
    let loadCalls = 0;
    let cancelCalls = 0;
    const resource = {
      keyOf: base.keyOf,
      getSnapshot: base.getSnapshot,
      subscribe(listener) {
        subscribeCalls += 1;
        const unsubscribe = base.subscribe(listener);
        listeners.add(listener);
        return () => {
          unsubscribeCalls += 1;
          listeners.delete(listener);
          unsubscribe();
        };
      },
      load(query) {
        loadCalls += 1;
        return base.load(query);
      },
      cancel() {
        cancelCalls += 1;
        base.cancel();
      },
      reset: base.reset,
      dispose: base.dispose,
    };
    const host = browser.document.createElement("main");
    const container = browser.document.createElement("div");
    host.append(container);
    browser.document.body.append(host);
    root = createRoot(container);
    mounted = true;

    const firstQuery = { session: "session-one", application: "orders" };
    await React.act(async () => {
      root.render(
        React.createElement(
          React.StrictMode,
          null,
          React.createElement(QueryLifecycleProbe, { resource, query: firstQuery }),
        ),
      );
    });
    assert.equal(
      listeners.size,
      1,
      "StrictMode replay must leave exactly one external-store listener",
    );
    assert.equal(loadCalls, 2, "StrictMode effect setup is replayed, not suppressed");
    assert.equal(pendingReads.length, 2);
    assert.equal(pendingReads[0].signal.aborted, true, "replayed cleanup cancels its first read");
    assert.equal(pendingReads[1].signal.aborted, false, "the replayed setup owns the active read");

    const nextQuery = { session: "session-two", application: "orders" };
    await React.act(async () => {
      root.render(
        React.createElement(
          React.StrictMode,
          null,
          React.createElement(QueryLifecycleProbe, { resource, query: nextQuery }),
        ),
      );
    });
    assert.equal(listeners.size, 1, "query replacement must not duplicate the subscription");
    assert.equal(loadCalls, 3);
    assert.equal(
      pendingReads[1].signal.aborted,
      true,
      "the prior query is canceled on replacement",
    );
    assert.equal(pendingReads[2].signal.aborted, false);

    await React.act(async () => root.unmount());
    mounted = false;
    assert.equal(listeners.size, 0, "unmount must detach the useSyncExternalStore listener");
    assert.equal(unsubscribeCalls, subscribeCalls);
    assert.ok(cancelCalls >= 3, "effect replay, replacement, and final unmount cancel owned reads");
    assert.equal(pendingReads[2].signal.aborted, true, "final unmount aborts the active read");

    await React.act(async () => {
      for (const read of pendingReads) read.resolve(["late result"]);
      await Promise.resolve();
    });
    assert.equal(
      base.getSnapshot().status,
      "idle",
      "ignored late resolutions cannot repopulate an unmounted owner",
    );
    base.dispose();
    host.remove();
  } finally {
    if (root && mounted && act) await act(async () => root.unmount());
    if (vite) await vite.close();
    browser.happyDOM.abort();
    browser.close();
    for (const [name, descriptor] of priorGlobals) {
      if (descriptor) Object.defineProperty(globalThis, name, descriptor);
      else delete globalThis[name];
    }
  }
});
