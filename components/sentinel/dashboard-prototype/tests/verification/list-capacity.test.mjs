import assert from "node:assert/strict";
import { createInstance } from "i18next";
import { createServer } from "vite";
import { test } from "node:test";

test("F5.6 instance directory accepts the 100-row API ceiling and renders the complete bounded page", async () => {
  const vite = await createServer({
    configFile: false,
    root: process.cwd(),
    appType: "custom",
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false, ws: false },
  });
  try {
    const [{ ObservedInstanceDirectory }, { InstanceCatalogQuerySchema }] = await Promise.all([
      vite.ssrLoadModule("/src/features/applications/ui/ObservedInstanceDirectory.tsx"),
      vite.ssrLoadModule("/src/features/applications/api/instanceWire.ts"),
    ]);
    const [{ createElement }, { renderToStaticMarkup }, { I18nextProvider }] = await Promise.all([
      import("react"),
      import("react-dom/server"),
      import("react-i18next"),
    ]);
    const query = {
      context: {
        environmentId: "production",
        appId: null,
        instanceId: null,
        resource: null,
        scope: "fleet",
        window: { from: "2026-10-12T00:00:00.000Z", to: "2026-10-12T01:00:00.000Z" },
      },
      page: 1,
      pageSize: 100,
      search: "",
      attentionOnly: false,
    };
    assert.equal(InstanceCatalogQuerySchema.safeParse(query).success, true);
    assert.equal(InstanceCatalogQuerySchema.safeParse({ ...query, pageSize: 101 }).success, false);

    const items = Array.from({ length: 100 }, (_, index) => ({
      appId: "orders",
      environmentId: "production",
      instanceId: `worker-${String(index + 1).padStart(3, "0")}`,
      hostId: `host-${index % 4}`,
      containerId: `container-${index + 1}`,
      processId: String(10_000 + index),
      processEpoch: `epoch-${index + 1}`,
      health: "healthy",
      lastReportAtMs: null,
      supportedScopes: ["process"],
      ruleReceipt: {
        state: "applied",
        desiredVersionId: "v1",
        appliedVersionId: "v1",
        processEpoch: `epoch-${index + 1}`,
        receivedAtMs: null,
      },
      processMetrics: [],
    }));
    const catalog = {
      query: { context: query.context, page: 1, pageSize: 100, search: "", attentionOnly: false },
      asOfMs: Date.parse("2026-10-12T01:00:00.000Z"),
      coverage: { expected: 100, reporting: 100, inventorySource: "bounded-test" },
      totalInstances: 100,
      attentionInstances: 0,
      filteredTotal: 100,
      items,
    };
    const i18n = createInstance();
    await i18n.init({
      lng: "en-US",
      fallbackLng: false,
      nsSeparator: false,
      resources: { "en-US": { translation: {} } },
    });
    const startedAt = performance.now();
    const markup = renderToStaticMarkup(
      createElement(
        I18nextProvider,
        { i18n },
        createElement(ObservedInstanceDirectory, {
          catalog,
          selection: null,
          onSelect() {},
          onPage() {},
        }),
      ),
    );
    const renderMs = performance.now() - startedAt;
    assert.equal((markup.match(/data-observed-instance=/g) ?? []).length, 100);
    assert.ok(markup.includes("worker-001") && markup.includes("worker-100"));
    console.log(
      `F5.6 SSR capacity sample: 100 rows, ${markup.length} HTML chars, ${renderMs.toFixed(2)} ms (Node SSR only)`,
    );
  } finally {
    await vite.close();
  }
});
