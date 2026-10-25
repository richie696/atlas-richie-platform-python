import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createInstance } from "i18next";
import { createServer } from "vite";
import { test } from "node:test";

const protocolAsOfMs = Date.parse("2026-10-15T04:00:00Z");

function protocols() {
  return {
    asOfMs: protocolAsOfMs,
    items: [
      {
        kind: "agent-reporting",
        supported: ["atlas-richie.reporting/v1"],
        active: "atlas-richie.reporting/v1",
        compatibility: "compatible",
        observedAtMs: protocolAsOfMs - 1000,
      },
      {
        kind: "rule-config",
        supported: [],
        active: null,
        compatibility: "unknown",
        observedAtMs: null,
      },
      {
        kind: "cluster-token",
        supported: [],
        active: null,
        compatibility: "unknown",
        observedAtMs: null,
      },
    ],
  };
}

function agentPage() {
  return {
    asOfMs: protocolAsOfMs,
    page: 1,
    pageSize: 20,
    total: 21,
    items: [
      {
        environmentId: "prod",
        appId: "orders",
        instanceId: "orders-worker-old",
        processId: "pid-old",
        reporterId: "reporter-old",
        boundary: "agent-reporting",
        collectorSupported: ["atlas-richie.reporting/v1"],
        runtimeVersion: "atlas-richie.reporting/v2",
        compatibility: "incompatible",
        observedAtMs: protocolAsOfMs - 2000,
      },
      {
        environmentId: "prod",
        appId: "orders",
        instanceId: "orders-worker-new",
        processId: "pid-new",
        reporterId: "reporter-new",
        boundary: "agent-reporting",
        collectorSupported: ["atlas-richie.reporting/v1"],
        runtimeVersion: null,
        compatibility: "unknown",
        observedAtMs: null,
      },
    ],
  };
}

function incidentPage() {
  return {
    asOfMs: protocolAsOfMs,
    page: 1,
    pageSize: 20,
    total: 1,
    items: [
      {
        environmentId: "prod",
        appId: "orders",
        instanceId: "orders-worker-old",
        processId: "pid-old",
        reporterId: "reporter-old",
        boundary: "incident-events",
        collectorSupported: ["atlas-richie.incident-events/v1"],
        runtimeVersion: null,
        compatibility: "unknown",
        observedAtMs: null,
      },
    ],
  };
}

test("SYSTEM-PROTOCOL-WORKERS: mounted panel renders per-worker compatibility and paged state in all locales", async () => {
  const vite = await createServer({
    configFile: false,
    root: process.cwd(),
    appType: "custom",
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false, ws: false },
  });
  try {
    const [{ ObservedProtocolsPanel }, React, { renderToStaticMarkup }, { I18nextProvider }] =
      await Promise.all([
        vite.ssrLoadModule("/src/features/system/ui/ObservedProtocolsPanel.tsx"),
        import("react"),
        import("react-dom/server"),
        import("react-i18next"),
      ]);
    const locales = ["zh-CN", "en-US", "ja-JP"];
    for (const locale of locales) {
      const systemMessages = JSON.parse(
        await readFile(
          new URL(`../../src/app/i18n/messages/${locale}/system.json`, import.meta.url),
          "utf8",
        ),
      );
      const i18n = createInstance();
      await i18n.init({
        lng: locale,
        fallbackLng: false,
        nsSeparator: false,
        resources: { [locale]: { translation: systemMessages } },
      });
      const createReadyResource = (key, value) => {
        const listeners = new Set();
        let snapshot = { status: "idle" };
        const resource = {
          keyOf: () => key,
          getSnapshot: () => snapshot,
          subscribe(listener) {
            listeners.add(listener);
            return () => listeners.delete(listener);
          },
          async load() {
            snapshot = { status: "ready", key, data: value, receivedAt: protocolAsOfMs };
            listeners.forEach((listener) => listener());
            return value;
          },
          cancel() {},
          reset() {},
          dispose() {},
        };
        return resource;
      };
      const protocolResource = createReadyResource("protocols", protocols());
      const workerResource = createReadyResource("workers", agentPage());
      const incidentResource = createReadyResource("incidents", incidentPage());
      await protocolResource.load(null);
      await workerResource.load({ page: 1, pageSize: 20 });
      await incidentResource.load({ page: 1, pageSize: 20 });
      const markup = renderToStaticMarkup(
        React.createElement(
          I18nextProvider,
          { i18n },
          React.createElement(ObservedProtocolsPanel, {
            resource: protocolResource,
            agentReportingResource: workerResource,
            incidentEventResource: incidentResource,
          }),
        ),
      );
      const incompatibleLabel = i18n.t("system.observed.compatibility.incompatible");
      const unknownLabel = i18n.t("system.observed.compatibility.unknown");
      const pageLabel = i18n.t("system.observed.workerProtocols.page", { page: 1, pages: 2 });
      assert.ok(markup.includes('data-system-protocol-worker="orders-worker-old"'), locale);
      assert.ok(
        markup.includes('data-system-protocol-boundary="incident-event-workers-title"'),
        locale,
      );
      assert.ok(markup.includes('data-system-protocol-worker="orders-worker-new"'), locale);
      assert.ok(markup.includes(incompatibleLabel), locale);
      assert.ok(markup.includes(unknownLabel), locale);
      assert.ok(markup.includes(pageLabel), locale);
      assert.ok(markup.includes("atlas-richie.reporting/v2"), locale);
      assert.ok(markup.includes("atlas-richie.incident-events/v1"), locale);
      assert.ok(markup.includes("aria-label="), locale);
      assert.doesNotMatch(markup, /certificate-principal|private-principal/);
    }
  } finally {
    await vite.close();
  }
});
