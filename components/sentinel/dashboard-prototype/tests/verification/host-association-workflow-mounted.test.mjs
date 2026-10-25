import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { Window } from "happy-dom";
import { createInstance } from "i18next";
import { createServer } from "vite";

test("T05.4 host association requires explicit target selection and stays role/freshness aware", async () => {
  const browser = new Window({ url: "http://localhost/#/hosts?environment=production" });
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
    "MouseEvent",
    "MutationObserver",
    "requestAnimationFrame",
    "cancelAnimationFrame",
  ]) {
    installGlobal(name, browser[name] ?? browser.document);
  }
  installGlobal("IS_REACT_ACT_ENVIRONMENT", true);

  let vite;
  let root;
  let act;
  try {
    vite = await createServer({
      configFile: false,
      root: process.cwd(),
      appType: "custom",
      optimizeDeps: { noDiscovery: true, include: [] },
      server: { middlewareMode: true, hmr: false, ws: false },
    });
    const [
      { HostDirectoryPage },
      { SessionProvider },
      { ChartThemeProvider },
      React,
      { createRoot },
      { I18nextProvider },
    ] = await Promise.all([
      vite.ssrLoadModule("/src/features/hosts/ui/HostDirectoryPage.tsx"),
      vite.ssrLoadModule("/src/core/session/SessionProvider.tsx"),
      vite.ssrLoadModule("/src/shared/ui/charts/ChartThemeProvider.tsx"),
      import("react"),
      import("react-dom/client"),
      import("react-i18next"),
    ]);
    act = React.act;

    const [applications, observation, shell] = await Promise.all(
      ["applications", "observation", "shell"].map(async (name) =>
        JSON.parse(
          await readFile(
            new URL(`../../src/app/i18n/messages/en-US/${name}.json`, import.meta.url),
            "utf8",
          ),
        ),
      ),
    );
    const i18n = createInstance();
    await i18n.init({
      lng: "en-US",
      fallbackLng: false,
      nsSeparator: false,
      resources: { "en-US": { translation: { ...applications, ...observation, ...shell } } },
    });

    const host = browser.document.createElement("main");
    browser.document.body.append(host);
    root = createRoot(host);
    const now = Date.now();
    let association = null;
    const mutationCalls = [];
    let requestSequence = 0;
    const sourcesPort = {
      async readSources() {
        return {
          items: [
            {
              id: "prometheus-production",
              displayName: "Production Prometheus",
              environmentId: "production",
              enabled: true,
            },
          ],
        };
      },
    };
    const metricsPort = {
      async read() {
        return {
          quality: "available",
          hosts: [
            {
              hostId: "host-01",
              identity: [{ name: "host_id", value: "host-01" }],
              metrics: [
                {
                  metric: "host_cpu_busy_ratio",
                  unit: "ratio",
                  quality: "available",
                  samples: [{ at: new Date(now - 1_000).toISOString(), value: 0.25 }],
                },
              ],
            },
          ],
        };
      },
    };
    const associationPort = {
      async read(_environmentId, filters) {
        if (filters.appId && filters.instanceId) {
          return {
            environmentId: "production",
            asOf: new Date(now).toISOString(),
            page: 1,
            pageSize: filters.pageSize,
            total: 0,
            associatedHostIds: [],
            hostIdsComplete: true,
            items: [],
          };
        }
        const items = association ? [association] : [];
        return {
          environmentId: "production",
          asOf: new Date(now).toISOString(),
          page: 1,
          pageSize: filters.pageSize,
          total: items.length,
          associatedHostIds: association ? [association.hostId] : [],
          hostIdsComplete: true,
          items,
        };
      },
      async associate(input) {
        mutationCalls.push({ kind: "associate", input });
        association = {
          sourceId: input.sourceId,
          environmentId: input.environmentId,
          hostId: input.hostId,
          appId: input.appId,
          instanceId: input.instanceId,
          processId: "pid-synthetic-01",
          revision: "11111111-1111-4111-8111-111111111111",
          provenance: "operator_confirmed",
          currentEpoch: "22222222-2222-4222-8222-222222222222",
          lastReceivedAt: new Date(now - 5 * 60_000).toISOString(),
          reporterActive: true,
          createdAt: new Date(now - 60_000).toISOString(),
        };
        return association;
      },
      async remove(input) {
        mutationCalls.push({ kind: "remove", input });
        association = null;
        return { removed: true };
      },
      async readOperation(requestKey) {
        return { status: "not_found", requestKey };
      },
    };

    const render = async (roleId) =>
      act(async () => {
        root.render(
          React.createElement(
            I18nextProvider,
            { i18n },
            React.createElement(
              SessionProvider,
              { session: { roleId, capabilities: [] } },
              React.createElement(
                ChartThemeProvider,
                { revision: "sentinel-dark" },
                React.createElement(HostDirectoryPage, {
                  environmentId: "production",
                  sourcesPort,
                  metricsPort,
                  associationPort,
                  navigate() {},
                }),
              ),
            ),
          ),
        );
        await new Promise((resolve) => setTimeout(resolve, 0));
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
    const button = (label) => {
      const found = [...host.querySelectorAll("button")].find((candidate) =>
        candidate.textContent?.trim().includes(label),
      );
      assert.ok(found, `expected button: ${label}`);
      return found;
    };
    const field = (labelText) => {
      const label = [...host.querySelectorAll("label")].find(
        (candidate) => candidate.textContent?.trim() === labelText,
      );
      assert.ok(label, `expected accessible field label: ${labelText}`);
      const input = browser.document.getElementById(label.htmlFor);
      assert.ok(input, `expected input linked to field label: ${labelText}`);
      return input;
    };
    const setInput = (input, value) => {
      const setter = Object.getOwnPropertyDescriptor(
        browser.HTMLInputElement.prototype,
        "value",
      ).set;
      setter.call(input, value);
      input.dispatchEvent(new browser.Event("input", { bubbles: true }));
    };

    await render("admin");
    assert.match(
      host.textContent ?? "",
      /Select a host to enable managing its runtime associations/,
    );
    assert.equal(
      [...host.querySelectorAll("label")].some(
        (label) => label.textContent?.trim() === "Application ID",
      ),
      false,
      "no mutation target is implicit",
    );

    await act(async () => button("host-01").click());
    assert.equal(field("Application ID").value, "");
    await act(async () => {
      setInput(field("Application ID"), "orders");
      setInput(field("Instance ID"), "worker-01");
    });
    await act(async () => {
      button("Associate worker").click();
      await new Promise((resolve) => setTimeout(resolve, 0));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    assert.equal(mutationCalls.length, 1);
    assert.equal(mutationCalls[0].kind, "associate");
    assert.equal(mutationCalls[0].input.hostId, "host-01");
    assert.equal(mutationCalls[0].input.appId, "orders");
    assert.equal(mutationCalls[0].input.instanceId, "worker-01");
    assert.match(host.textContent ?? "", /Reporter heartbeat is stale/);

    await render("view");
    assert.match(host.textContent ?? "", /Reporter heartbeat is stale/);
    assert.equal(
      [...host.querySelectorAll("button")].some((candidate) =>
        ["Associate worker", "Remove association"].includes(candidate.textContent?.trim() ?? ""),
      ),
      false,
      "view can inspect stale association state but has no write controls",
    );

    await render("admin");
    await act(async () => {
      button("Remove association").click();
      await new Promise((resolve) => setTimeout(resolve, 0));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    assert.equal(mutationCalls.length, 2);
    assert.equal(mutationCalls[1].kind, "remove");
    assert.equal(mutationCalls[1].input.expectedRevision, "11111111-1111-4111-8111-111111111111");
    assert.match(host.textContent ?? "", /No runtime worker is associated with this host/);

    await act(async () => root.unmount());
    host.remove();
  } finally {
    if (root && act) await act(async () => root.unmount());
    if (vite) await vite.close();
    browser.happyDOM.abort();
    for (const [name, descriptor] of priorGlobals) {
      if (descriptor) Object.defineProperty(globalThis, name, descriptor);
      else delete globalThis[name];
    }
  }
});
