import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createInstance } from "i18next";
import { createServer } from "vite";
import { test } from "node:test";

test("not-integrated metrics render an explicit unavailable chart state without plotting fabricated data", async () => {
  const vite = await createServer({
    configFile: false,
    root: process.cwd(),
    appType: "custom",
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false, ws: false },
  });
  try {
    const [
      { MetricCharts },
      { ChartThemeProvider },
      { createElement },
      { renderToStaticMarkup },
      { I18nextProvider },
    ] = await Promise.all([
      vite.ssrLoadModule("/src/shared/ui/observation/MetricCharts.tsx"),
      vite.ssrLoadModule("/src/shared/ui/charts/ChartThemeProvider.tsx"),
      import("react"),
      import("react-dom/server"),
      import("react-i18next"),
    ]);
    const locales = [
      ["zh-CN", "该指标尚未接入采集"],
      ["en-US", "Metric collection is not integrated"],
      ["ja-JP", "このメトリクスの収集は未統合です"],
    ];
    const fromMs = Date.parse("2026-10-12T00:00:00Z");
    const toMs = fromMs + 60_000;
    const coverage = { expected: null, reporting: 0, inventorySource: null };
    const bundle = {
      query: {
        context: {
          environmentId: "production",
          appId: null,
          instanceId: null,
          resource: null,
          scope: "fleet",
          window: { fromMs, toMs },
        },
        metrics: ["tps"],
        stepMs: 10_000,
      },
      asOfMs: toMs,
      summary: [
        {
          metric: "tps",
          unit: "transactions_per_second",
          source: "console-unavailable",
          denominator: "business_transactions",
          coverage,
          quality: "not_integrated",
          value: null,
          sampledAtMs: null,
        },
      ],
      series: [
        {
          metric: "tps",
          unit: "transactions_per_second",
          source: "console-unavailable",
          denominator: "business_transactions",
          coverage,
          quality: "not_integrated",
          samples: [],
        },
      ],
      annotations: [],
    };
    for (const [locale, expectedEmptyMessage] of locales) {
      const [observation, shell] = await Promise.all([
        readFile(
          new URL(`../../src/app/i18n/messages/${locale}/observation.json`, import.meta.url),
          "utf8",
        ),
        readFile(
          new URL(`../../src/app/i18n/messages/${locale}/shell.json`, import.meta.url),
          "utf8",
        ),
      ]);
      const i18n = createInstance();
      await i18n.init({
        lng: locale,
        fallbackLng: false,
        nsSeparator: false,
        resources: {
          [locale]: {
            translation: { ...JSON.parse(observation), ...JSON.parse(shell) },
          },
        },
      });
      const markup = renderToStaticMarkup(
        createElement(
          I18nextProvider,
          { i18n },
          createElement(
            ChartThemeProvider,
            { revision: 0 },
            createElement(MetricCharts, { bundle }),
          ),
        ),
      );
      assert.ok(markup.includes(expectedEmptyMessage), `${locale} explains collection state`);
      assert.ok(markup.includes(i18n.t("observation.quality.notIntegrated")));
      assert.doesNotMatch(markup, /nivo|\"y\":0/);
    }
  } finally {
    await vite.close();
  }
});

test("unavailable monitoring keeps the metric cards and chart panels mounted in every locale", async () => {
  const vite = await createServer({
    configFile: false,
    root: process.cwd(),
    appType: "custom",
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false, ws: false },
  });
  try {
    const [
      { MetricUnavailableView },
      { ChartThemeProvider },
      { createElement },
      { renderToStaticMarkup },
      { I18nextProvider },
    ] = await Promise.all([
      vite.ssrLoadModule("/src/shared/ui/observation/MetricUnavailableView.tsx"),
      vite.ssrLoadModule("/src/shared/ui/charts/ChartThemeProvider.tsx"),
      import("react"),
      import("react-dom/server"),
      import("react-i18next"),
    ]);
    const locales = [
      ["zh-CN", "监控指标区域", "暂无可确认的采样数据"],
      ["en-US", "Monitoring metrics", "No confirmed samples are available yet"],
      ["ja-JP", "監視メトリクス", "確認済みのサンプルはまだありません"],
    ];
    for (const [locale, areaLabel, emptyMessage] of locales) {
      const [observation, shell] = await Promise.all([
        readFile(
          new URL(`../../src/app/i18n/messages/${locale}/observation.json`, import.meta.url),
          "utf8",
        ),
        readFile(
          new URL(`../../src/app/i18n/messages/${locale}/shell.json`, import.meta.url),
          "utf8",
        ),
      ]);
      const i18n = createInstance();
      await i18n.init({
        lng: locale,
        fallbackLng: false,
        nsSeparator: false,
        resources: {
          [locale]: {
            translation: { ...JSON.parse(observation), ...JSON.parse(shell) },
          },
        },
      });
      const markup = renderToStaticMarkup(
        createElement(
          I18nextProvider,
          { i18n },
          createElement(ChartThemeProvider, { revision: 0 }, createElement(MetricUnavailableView)),
        ),
      );
      assert.ok(markup.includes(`aria-label="${areaLabel}"`), `${locale} labels the metrics area`);
      assert.equal(
        (markup.match(/data-metric-card=/g) ?? []).length,
        6,
        `${locale} renders six KPI cards`,
      );
      assert.equal((markup.match(/data-observation-state="unavailable"/g) ?? []).length, 1);
      assert.ok(markup.includes(emptyMessage), `${locale} explains the empty state`);
      assert.equal(
        (markup.match(/chart-empty/g) ?? []).length,
        12,
        `${locale} renders six empty charts`,
      );
      assert.doesNotMatch(
        markup,
        /<strong>0(?:<|\s)/,
        "unavailable metrics are not rendered as zero",
      );
      assert.equal(
        (markup.match(/<strong>—/g) ?? []).length,
        6,
        "KPI cards use unavailable markers",
      );
    }
  } finally {
    await vite.close();
  }
});

test("realtime can show metric-level partial state without duplicating a page-level warning", async () => {
  const vite = await createServer({
    configFile: false,
    root: process.cwd(),
    appType: "custom",
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false, ws: false },
  });
  try {
    const [{ ObservationQueryView }, { createElement }, { renderToStaticMarkup }] =
      await Promise.all([
        vite.ssrLoadModule("/src/shared/ui/observation/ObservationQueryView.tsx"),
        import("react"),
        import("react-dom/server"),
      ]);
    const snapshot = { status: "partial", key: "monitoring", receivedAt: 10, data: {} };
    const markup = renderToStaticMarkup(
      createElement(ObservationQueryView, {
        snapshot,
        onRetry: () => undefined,
        showPartialFeedback: false,
        children: () => createElement("p", null, "metric-cards-remain-visible"),
      }),
    );
    assert.match(markup, /data-query-state="partial"/);
    assert.match(markup, /metric-cards-remain-visible/);
    assert.doesNotMatch(markup, /部分指标或实例没有有效样本/);
  } finally {
    await vite.close();
  }
});
