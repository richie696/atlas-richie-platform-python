import assert from "node:assert/strict";
import { test } from "node:test";
import { readdirSync, readFileSync } from "node:fs";
import { createInstance } from "i18next";
import { AppError, AppErrorKind, StateStore } from "@richie696/react-framework";
import {
  METRIC_BASIS,
  METRIC_DENOMINATOR,
  METRIC_ID,
  metricQueryKey,
  validMetricQuery,
  validMetricReading,
  validMetricSeries,
  validMetricBundle,
  withinObservationWindow,
  validObservationWindow,
  MAX_OBSERVATION_POINTS,
} from "../../src/shared/model/observation";
import { observationMetricReadings } from "../../src/shared/api/observationContractExamples";
import {
  metricDisplayValue,
  formatMetricReading,
  metricPlot,
  observationNavigation,
  observationWindowFromRoute,
  OBSERVATION_HEALTH_LABEL_KEY,
} from "../../src/shared/presentation/observation";
import { createFleetResource } from "../../src/features/overview/application/fleetResource";
import {
  fleetQueryKey,
  validFleetQuery,
  validFleetSnapshot,
} from "../../src/features/overview/model/fleet";
import {
  trendEventCoordinate,
  buildTrendPlot,
  formatTrendTime,
} from "../../src/shared/ui/charts/trendPlot";
import { pathFor, routeFromPath } from "../../src/app/router/route.constants";
import { TIME_RANGE_MS } from "../../src/shared/types/navigation";
import {
  applicationForEnvironment,
  resolveEnvironmentId,
} from "../../src/features/applications/model/observationCatalog";
import { formatLocaleNumber } from "../../src/shared/presentation/formatLocaleNumber";
import { formatAccountLastLogin } from "../../src/features/identity/presentation/accountTime";
import { formatUtcDateTime, formatUtcInstant } from "../../src/shared/presentation/utcDateTime";
import {
  getSystemTimeZone,
  setSystemTimeZone,
} from "../../src/shared/presentation/systemTimeZone";
import { assembleMessageCatalog } from "../../src/app/i18n/catalog";
import { navigationItemsForAccess } from "../../src/app/router/navigation";
import { IDENTITY_ROLES } from "../../src/features/identity/model/account";
import { rolePresentationFor } from "../../src/features/identity/presentation/rolePresentation";
import { accountFeedbackKey } from "../../src/features/identity/presentation/accountFeedback";
import { withoutInstanceSelection } from "../../src/features/applications/model/instanceNavigation";
import { catalogFor, catalogQuery, detailFor, instanceFor } from "../fixtures/instances";
import {
  INSTANCE_HEALTH,
  INSTANCE_LAYER,
  instanceSelection,
  validInstanceObservation,
} from "../../src/features/applications/model/instanceObservation";
import { query, fromMs, toMs, bundleFor, snapshotFor } from "../fixtures/observations";
const access = () => new StateStore({ ownerKey: "test-owner-epoch", allowed: true });
const observe = (state) => ({ read: state.getSnapshot, subscribe: state.subscribe });
const deferred = () => {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
};

test("APP-ENVIRONMENT: retain only an application registered in the destination environment", () => {
  const applications = [
    { id: "app-one", environmentId: "test-env", name: "app-one" },
    { id: "app-one", environmentId: "prod-env", name: "app-one" },
    { id: "app-two", environmentId: "prod-env", name: "app-two" },
  ];
  assert.equal(applicationForEnvironment(applications, "prod-env", "app-one"), "app-one");
  assert.equal(applicationForEnvironment(applications, "test-env", "app-two"), null);
  assert.equal(applicationForEnvironment(applications, "prod-env", null), null);
});

test("APP-ENVIRONMENT: explicit route scope survives catalog failure but is validated after recovery", () => {
  const catalog = {
    asOfMs: Date.parse("2026-10-15T00:00:00Z"),
    environments: [{ id: "prod-env", name: "Production" }],
    applications: [{ id: "orders", environmentId: "prod-env", name: "Orders" }],
  };

  assert.equal(resolveEnvironmentId(null, "prod-env", "orders"), "prod-env");
  assert.equal(resolveEnvironmentId(null, "unconfirmed-env", null), "unconfirmed-env");
  assert.equal(resolveEnvironmentId(null, undefined, "orders"), null);
  assert.equal(resolveEnvironmentId(catalog, "prod-env", "orders"), "prod-env");
  assert.equal(resolveEnvironmentId(catalog, "unconfirmed-env", "orders"), null);
  assert.equal(resolveEnvironmentId(catalog, undefined, "orders"), "prod-env");
  assert.equal(resolveEnvironmentId(catalog, undefined, null), "prod-env");
});

test("MOCK-SCENARIO: fleet and instance fixtures share the app-owned identity, window, and QPS facts", () => {
  const fleet = snapshotFor({ ...query, pageSize: 10 });
  const instances = catalogFor({ ...catalogQuery, pageSize: 10 });
  assert.equal(fleet.query.context.environmentId, catalogQuery.context.environmentId);
  assert.deepEqual(fleet.query.context.window, catalogQuery.context.window);
  assert.deepEqual(
    fleet.applications.items.map(({ appId }) => appId),
    ["app-one", "app-two", "app-three"],
  );
  const observedApplicationIds = new Set(instances.items.map(({ appId }) => appId));
  for (const { appId, metrics } of fleet.applications.items.filter((item) =>
    observedApplicationIds.has(item.appId),
  )) {
    const fleetQps = metrics.find(({ metric }) => metric === "http_qps")?.value;
    const instanceQps = instances.items
      .filter((instance) => instance.appId === appId)
      .map(
        (instance) => instance.processMetrics.find(({ metric }) => metric === "http_qps")?.value,
      );
    assert.ok(instanceQps.length > 0, `Expected demo instances for ${appId}`);
    assert.equal(
      instanceQps.reduce((sum, value) => sum + value, 0),
      fleetQps,
      `${appId} QPS must equal its process observations`,
    );
  }
  assert.equal(
    fleet.metrics.summary.find(({ metric }) => metric === "http_qps")?.value,
    fleet.applications.items.reduce(
      (total, application) =>
        total + (application.metrics.find(({ metric }) => metric === "http_qps")?.value ?? 0),
      0,
    ),
  );
});

test("INSTANCE-SELECTION-CLEAR: explicit selection clearing removes merged URL identity and scope", () => {
  const existing = {
      environmentId: "test-env",
      appId: "app-one",
      range: "1h",
      from: new Date(fromMs).toISOString(),
      to: new Date(toMs).toISOString(),
      instanceId: "not-real",
      metricScope: INSTANCE_LAYER.Process,
    },
    merged = { ...existing, ...withoutInstanceSelection({ search: "instance" }) },
    parsed = routeFromPath(pathFor("applications", merged));
  assert.equal("instanceId" in parsed.context, false);
  assert.equal("metricScope" in parsed.context, false);
  assert.equal(parsed.context.search, "instance");
});

test("INSTANCE-SCOPE: detail never borrows metrics across host, container and process layers", () => {
  const selected = instanceFor(1);
  const scopes = [INSTANCE_LAYER.Host, INSTANCE_LAYER.Container, INSTANCE_LAYER.Process];
  for (const scope of scopes) {
    const request = instanceSelection(selected, query.context, scope);
    const result = detailFor(request);
    assert.equal(validInstanceObservation(result, request), true);
    assert.equal(result.instance.processEpoch, request.processEpoch);
    assert.equal(result.instance.ruleReceipt.processEpoch, request.processEpoch);
    assert.equal(result.metrics !== null, scope === INSTANCE_LAYER.Process);
    if (result.metrics) assert.equal(result.metrics.query.context.scope, scope);
  }
});

test("OBS-WINDOW: UTC across midnight uses [from,to), finite bounded intervals, not clock text comparisons", () => {
  assert.equal(validObservationWindow(query.context.window), true);
  assert.equal(withinObservationWindow(fromMs, query.context.window), true);
  assert.equal(withinObservationWindow(toMs, query.context.window), false);
  for (const window of [
    { fromMs, toMs: fromMs },
    { fromMs: toMs, toMs: fromMs },
    { fromMs, toMs: fromMs + 8 * 24 * 3600_000 },
    { fromMs: NaN, toMs },
    { fromMs: fromMs + 0.5, toMs },
  ])
    assert.equal(validObservationWindow(window), false);
});
test("OBS-QUERY: complete semantic identity, unordered metric selection, bounded point count and no duplicate metric", () => {
  const bundle = bundleFor(),
    input = bundle.query;
  assert.equal(validMetricQuery(input), true);
  assert.equal(
    metricQueryKey({ ...input, metrics: [...input.metrics].reverse() }),
    metricQueryKey(input),
  );
  for (const context of [
    { ...query.context, environmentId: "other" },
    { ...query.context, appId: "other" },
    { ...query.context, appId: "one", instanceId: "instance" },
    { ...query.context, scope: "host" },
    { ...query.context, resource: "resource" },
    { ...query.context, window: { fromMs: fromMs + 1, toMs } },
  ])
    assert.notEqual(metricQueryKey({ ...input, context }), metricQueryKey(input));
  for (const inputBad of [
    { ...input, stepMs: 1 },
    { ...input, stepMs: 0 },
    { ...input, metrics: ["http_qps", "http_qps"] },
    { ...input, metrics: ["unknown"] },
    { ...input, metrics: [] },
    { ...input, context: { ...query.context, appId: null, instanceId: "instance" } },
  ])
    assert.equal(validMetricQuery(inputBad), false);
});
test("OBS-METRIC: ratios never become percent twice; unavailable TPS is not inferred from QPS or zero", () => {
  const bundle = bundleFor(),
    cpu = bundle.summary.find((item) => item.metric === "cpu_ratio"),
    tps = bundle.summary.find((item) => item.metric === "tps");
  assert.equal(validMetricReading(cpu, query.context.window), true);
  assert.equal(metricDisplayValue(cpu.metric, cpu.value), 49);
  assert.equal(cpu.value, 0.49);
  assert.equal(metricDisplayValue(tps.metric, tps.value), null);
  assert.equal(validMetricReading({ ...cpu, value: 1.1 }, query.context.window), false);
  assert.equal(validMetricReading({ ...cpu, unit: "milliseconds" }, query.context.window), false);
  assert.equal(
    validMetricReading({ ...cpu, denominator: METRIC_BASIS.ElapsedSeconds }, query.context.window),
    false,
  );
  assert.equal(
    validMetricReading({ ...tps, value: 0, sampledAtMs: fromMs }, query.context.window),
    false,
  );
  assert.equal(validMetricReading({ ...cpu, value: NaN }, query.context.window), false);
  assert.equal(validMetricReading({ ...cpu, value: Infinity }, query.context.window), false);
  assert.equal(validMetricReading({ ...cpu, sampledAtMs: toMs }, query.context.window), false);
  const cpuSeries = bundle.series.find((item) => item.metric === "cpu_ratio");
  assert.equal(
    validMetricSeries(
      { ...cpuSeries, denominator: METRIC_BASIS.ElapsedSeconds },
      query.context.window,
    ),
    false,
  );
  assert.equal(cpuSeries.samples.length, 15);
  assert.equal(cpuSeries.samples[0].atMs, fromMs);
  assert.equal(cpuSeries.samples.at(-1).atMs, fromMs + 14 * query.stepMs);
  assert.equal(cpuSeries.samples.at(-1).value, cpu.value);
  assert.ok(new Set(cpuSeries.samples.map(({ value }) => value)).size > 1);
  assert.equal(
    validMetricReading(
      { ...cpu, coverage: { expected: 2, reporting: 3, inventorySource: "test-inventory" } },
      query.context.window,
    ),
    false,
  );
  assert.equal(validMetricReading({ ...cpu, quality: "available" }, query.context.window), true);
  assert.equal(
    validMetricReading(
      {
        ...cpu,
        quality: "available",
        coverage: { ...cpu.coverage, reporting: (cpu.coverage.expected ?? 1) - 1 },
      },
      query.context.window,
    ),
    false,
  );
  assert.equal(
    validMetricReading(
      { ...cpu, coverage: { expected: 4, reporting: 0, inventorySource: "test-inventory" } },
      query.context.window,
    ),
    false,
  );
  assert.equal(
    validMetricReading(
      { ...tps, coverage: { expected: 4, reporting: 3, inventorySource: "test-inventory" } },
      query.context.window,
    ),
    false,
  );
  const plot = metricPlot(bundle.series.find((item) => item.metric === "cpu_ratio"));
  assert.equal(plot.points.length, 15);
  assert.equal(plot.points.at(-1).cpu, 49);
  assert.ok(new Set(plot.points.map(({ cpu }) => cpu)).size > 1);
});

test("OBS-DENOMINATOR: metric aggregation bases have explicit cross-layer semantics", () => {
  assert.deepEqual(METRIC_DENOMINATOR, {
    http_qps: METRIC_BASIS.CompletedRequests,
    resource_entry_rate: METRIC_BASIS.AttemptedEntries,
    tps: METRIC_BASIS.BusinessTransactions,
    rt_p95: METRIC_BASIS.CompletedRequests,
    blocked_ratio: METRIC_BASIS.AttemptedEntries,
    cpu_ratio: METRIC_BASIS.CpuCores,
    memory_ratio: METRIC_BASIS.MemoryLimit,
    memory_bytes: METRIC_BASIS.Processes,
  });
  const unavailable = observationMetricReadings(Object.keys(METRIC_DENOMINATOR));
  assert.deepEqual(
    Object.fromEntries(unavailable.map(({ metric, denominator }) => [metric, denominator])),
    METRIC_DENOMINATOR,
  );
});

test("MOCK-SERIES: scenario profiles are deterministic, step-bounded and absent facts stay unavailable", () => {
  const first = bundleFor();
  const second = bundleFor();
  assert.deepEqual(first.series, second.series);

  const twoMinute = bundleFor(query.context, 120_000);
  const qps = twoMinute.series.find(({ metric }) => metric === "http_qps");
  assert.equal(qps.samples.length, 8);
  assert.ok(qps.samples.every(({ atMs }) => atMs >= fromMs && atMs < toMs));
  assert.equal(qps.samples.at(-1).value, 189);
  assert.ok(new Set(qps.samples.map(({ value }) => value)).size > 1);

  const unknown = bundleFor({ ...query.context, appId: "missing-app" });
  assert.deepEqual(unknown.series.find(({ metric }) => metric === "http_qps").samples, []);
  assert.deepEqual(unknown.series.find(({ metric }) => metric === "tps").samples, []);
});
test("I18N-INTL: metric numbers follow the selected locale without changing protocol values", () => {
  const reading = Object.freeze({
    metric: "http_qps",
    value: 1234.5,
    unit: "requests_per_second",
    sampledAtMs: fromMs,
    quality: "available",
    coverage: Object.freeze({ expected: 1, reporting: 1, inventorySource: "test" }),
  });
  const protocolValue = reading.value;
  assert.equal(formatMetricReading(reading, "en-US"), "1,234.5");
  assert.equal(formatMetricReading(reading, "de-DE"), "1.234,5");
  assert.equal(reading.value, protocolValue);
});
test("OBS-SERIES: missing samples stay gaps, timestamps must be unique/ordered/in-window and capacity bounded", () => {
  const series = bundleFor().series[0];
  assert.equal(validMetricSeries(series, query.context.window), true);
  for (const samples of [
    [...series.samples].reverse(),
    [series.samples[0], series.samples[0]],
    [{ atMs: toMs, value: 1 }],
    Array.from({ length: MAX_OBSERVATION_POINTS + 1 }, (_, index) => ({
      atMs: fromMs + index,
      value: 1,
    })),
  ])
    assert.equal(validMetricSeries({ ...series, samples }, query.context.window), false);
  assert.equal(
    validMetricSeries({ ...series, quality: "available", samples: [] }, query.context.window),
    false,
  );
  assert.equal(
    validMetricSeries({ ...series, quality: "not_integrated" }, query.context.window),
    false,
  );
});
test("OBS-INVENTORY: unknown denominator retains real partial values but cannot claim complete coverage or invent an inventory source", () => {
  const reading = bundleFor().summary[0],
    coverage = { expected: null, reporting: 3, inventorySource: null };
  assert.equal(
    validMetricReading({ ...reading, coverage, quality: "partial" }, query.context.window),
    true,
  );
  assert.equal(
    validMetricReading({ ...reading, coverage, quality: "available" }, query.context.window),
    false,
  );
  assert.equal(
    validMetricReading(
      { ...reading, coverage: { ...coverage, inventorySource: "authoritative-inventory" } },
      query.context.window,
    ),
    false,
  );
  assert.equal(
    validMetricReading(
      { ...reading, coverage: { expected: 4, reporting: 3, inventorySource: null } },
      query.context.window,
    ),
    false,
  );
});
test("OBS-BUNDLE: wrong app/window/step, omitted metrics, duplicated annotations and mixed units are protocol errors", () => {
  const value = bundleFor(
    { ...query.context, appId: "app-one", scope: "application" },
    query.stepMs,
  );
  assert.equal(validMetricBundle(value, value.query), true);
  const tpsSeries = value.series.find((item) => item.metric === METRIC_ID.Tps);
  const replaceTpsSeries = (replacement) =>
    value.series.map((item) => (item.metric === METRIC_ID.Tps ? replacement : item));
  for (const bad of [
    { ...value, query: { ...value.query, context: { ...query.context, appId: "wrong" } } },
    { ...value, query: { ...value.query, stepMs: 120_000 } },
    { ...value, summary: value.summary.slice(1) },
    { ...value, series: value.series.slice(1) },
    { ...value, series: replaceTpsSeries({ ...tpsSeries, source: "other-reporter" }) },
    {
      ...value,
      series: replaceTpsSeries({ ...tpsSeries, quality: "no_samples" }),
    },
    {
      ...value,
      series: replaceTpsSeries({
        ...tpsSeries,
        coverage: { expected: 1, reporting: 0, inventorySource: "other-inventory" },
      }),
    },
    { ...value, annotations: [value.annotations[0], value.annotations[0]] },
    { ...value, annotations: [{ ...value.annotations[0], atMs: toMs }] },
  ])
    assert.equal(validMetricBundle(bad, value.query), false);
});
test("OBS-ANNOTATION: a publication between samples is rendered at its actual UTC coordinate, excluding window end", () => {
  const points = metricPlot(bundleFor().series[0]).points,
    plot = buildTrendPlot(points, "qps");
  assert.equal(trendEventCoordinate(fromMs + 30_000, plot, [fromMs, toMs]), fromMs + 30_000);
  assert.equal(trendEventCoordinate(toMs, plot, [fromMs, toMs]), null);
  assert.equal(trendEventCoordinate(fromMs - 1, plot, [fromMs, toMs]), null);
  assert.equal(
    trendEventCoordinate("14:02", buildTrendPlot([{ time: "14:02", qps: 1 }], "qps")),
    "14:02",
  );
  assert.equal(
    trendEventCoordinate("14:03", buildTrendPlot([{ time: "14:02", qps: 1 }], "qps")),
    null,
  );
  assert.match(formatTrendTime(fromMs, "en-US", true, "UTC"), /23:55/);
});
test("OBS-DRILLDOWN: exact window survives routing without translating identities or recomputing relative time", () => {
  const navigation = observationNavigation(query.context),
    parsed = routeFromPath(
      pathFor("applications", { ...navigation, appId: "app-one", instanceId: "instance-one" }),
    );
  assert.equal(parsed.context.from, new Date(fromMs).toISOString());
  assert.equal(parsed.context.to, new Date(toMs).toISOString());
  assert.equal(parsed.context.environmentId, "test-env");
  assert.equal(parsed.context.instanceId, "instance-one");
});
test("OBS-ROUTE-WINDOW: a valid exact window wins over a relative label; invalid bounds use one stable anchor", () => {
  assert.deepEqual(
    observationWindowFromRoute(
      new Date(fromMs).toISOString(),
      new Date(toMs).toISOString(),
      "1h",
      toMs + TIME_RANGE_MS["1h"],
    ),
    { fromMs, toMs },
  );
  const anchor = toMs + 10_000;
  assert.deepEqual(observationWindowFromRoute("invalid", undefined, "1h", anchor), {
    fromMs: anchor - TIME_RANGE_MS["1h"],
    toMs: anchor,
  });
});
test("FLEET-DRILLDOWN: incidents keep fleet scope while rule coverage targets its exact application", () => {
  const fleetContext = observationNavigation(query.context);
  const incidents = routeFromPath(pathFor("faults", fleetContext));
  assert.equal(incidents.route, "faults");
  assert.equal(incidents.context.environmentId, "test-env");
  assert.equal(incidents.context.appId, "all");
  assert.equal(incidents.context.from, new Date(fromMs).toISOString());
  assert.equal(incidents.context.to, new Date(toMs).toISOString());

  const rowContext = observationNavigation({
    ...query.context,
    appId: "app-three",
    scope: "application",
  });
  const rules = routeFromPath(pathFor("rules", rowContext));
  assert.equal(rules.route, "rules");
  assert.equal(rules.context.environmentId, "test-env");
  assert.equal(rules.context.appId, "app-three");
  assert.equal(rules.context.metricScope, "application");
  assert.equal(rules.context.from, new Date(fromMs).toISOString());
  assert.equal(rules.context.to, new Date(toMs).toISOString());
});
test("FLEET-SNAPSHOT: global totals are not the current page; wrong app/denominator/counters/read time rejected", () => {
  const value = snapshotFor();
  assert.equal(validFleetSnapshot(value, query), true);
  assert.equal(value.totalApplications, 3);
  assert.equal(value.applications.items.length, 2);
  assert.notEqual(fleetQueryKey({ ...query, page: 2 }), fleetQueryKey(query));
  assert.notEqual(fleetQueryKey({ ...query, search: "one" }), fleetQueryKey(query));
  for (const bad of [
    { ...value, attentionApplications: 4 },
    { ...value, applications: { ...value.applications, total: 4 } },
    { ...value, applications: { ...value.applications, page: 2 } },
    { ...value, metrics: { ...value.metrics, asOfMs: toMs + 1 } },
  ])
    assert.equal(validFleetSnapshot(bad, query), false);
  const single = {
      ...query,
      context: { ...query.context, appId: "app-one", scope: "application" },
    },
    singleValue = snapshotFor(single);
  assert.equal(validFleetSnapshot(singleValue, single), true);
  assert.equal(
    validFleetSnapshot(
      {
        ...singleValue,
        applications: { ...singleValue.applications, items: value.applications.items },
      },
      single,
    ),
    false,
  );
  for (const badQuery of [
    { ...query, page: 0 },
    { ...query, pageSize: 101 },
    { ...query, context: { ...query.context, appId: "one", scope: "fleet" } },
    { ...query, context: { ...query.context, instanceId: "i" } },
  ])
    assert.equal(validFleetQuery(badQuery), false);
});
test("FLEET-PROJECTION: environment totals stay global while search and pagination only project directory rows", () => {
  const firstPage = snapshotFor(query);
  const secondPage = snapshotFor({ ...query, page: 2 });
  const filtered = snapshotFor({ ...query, search: "one" });
  const noMatches = snapshotFor({ ...query, search: "missing" });
  const application = snapshotFor({
    ...query,
    context: { ...query.context, appId: "app-one", scope: "application" },
  });

  for (const snapshot of [firstPage, secondPage, filtered, noMatches]) {
    assert.equal(snapshot.totalApplications, 3);
    assert.equal(snapshot.attentionApplications, 1);
    assert.deepEqual(snapshot.attentionTargets, ["app-one"]);
  }
  assert.deepEqual(
    firstPage.applications.items.map(({ appId }) => appId),
    ["app-one", "app-two"],
  );
  assert.deepEqual(
    firstPage.applications.items.map((application) => [
      application.appId,
      application.metrics.find(({ metric }) => metric === "http_qps")?.value,
    ]),
    [
      ["app-one", 42],
      ["app-two", 84],
    ],
  );
  assert.equal(firstPage.metrics.summary.find(({ metric }) => metric === "http_qps")?.value, 189);
  assert.deepEqual(
    secondPage.applications.items.map(({ appId }) => appId),
    ["app-three"],
  );
  assert.equal(secondPage.applications.total, 3);
  assert.deepEqual(
    filtered.applications.items.map(({ appId }) => appId),
    ["app-one"],
  );
  assert.equal(filtered.applications.total, 1);
  assert.equal(noMatches.applications.items.length, 0);
  assert.equal(noMatches.applications.total, 0);
  assert.equal(validFleetSnapshot(noMatches, { ...query, search: "missing" }), true);
  assert.equal(application.totalApplications, 1);
  assert.equal(application.attentionApplications, 1);
  assert.equal(application.applications.total, 1);
  assert.deepEqual(
    application.applications.items.map(({ appId }) => appId),
    ["app-one"],
  );
  assert.deepEqual(application.applications.items[0].metrics, application.metrics.summary);
  assert.equal(application.metrics.query.context.appId, "app-one");
  assert.equal(application.metrics.query.context.scope, "application");
  const qpsSamples = application.metrics.series
    .find(({ metric }) => metric === "http_qps")
    ?.samples.map(({ value }) => value);
  assert.equal(qpsSamples.length, 15);
  assert.equal(qpsSamples.at(-1), 42);
  assert.ok(new Set(qpsSamples).size > 1);
});
test("FLEET-OWNER: first revocation clears completed observations, next owner never receives previous data or late response", async () => {
  const state = access();
  let pending, signal;
  const resource = createFleetResource(
    {
      readFleet: async (input, s) => {
        signal = s;
        if (pending) return pending.promise;
        return snapshotFor(input);
      },
    },
    observe(state),
  );
  await resource.load(query);
  assert.equal(resource.getSnapshot().status, "partial");
  const seen = [];
  const unsubscribe = resource.subscribe(() => seen.push(resource.getSnapshot()));
  seen.length = 0;
  state.set({ ownerKey: "test-owner-epoch", allowed: false });
  assert.equal(seen[0].status, "denied");
  assert.ok(seen.every((value) => !("data" in value)));
  await assert.rejects(resource.load(query), (error) => error.kind === AppErrorKind.FORBIDDEN);
  state.set({ ownerKey: "next-owner", allowed: true });
  assert.equal(resource.getSnapshot().status, "idle");
  pending = deferred();
  const old = resource.load(query);
  state.set({ ownerKey: "third-owner", allowed: true });
  assert.equal(signal.aborted, true);
  pending.resolve(snapshotFor(query));
  await assert.rejects(old);
  assert.equal(resource.getSnapshot().status, "idle");
  unsubscribe();
  resource.dispose();
});
test("FLEET-REFRESH: failed same-key read keeps labeled stale data; changed key cannot lend it and mismatch never becomes ready", async () => {
  const state = access();
  let mode = "success";
  const resource = createFleetResource(
    {
      readFleet: async (input) => {
        if (mode === "offline") throw new AppError(AppErrorKind.NETWORK, "synthetic offline");
        if (mode === "wrong") return snapshotFor(query);
        return snapshotFor(input);
      },
    },
    observe(state),
  );
  await resource.load(query);
  mode = "offline";
  await assert.rejects(resource.load(query));
  assert.equal(resource.getSnapshot().status, "stale");
  assert.equal(resource.getSnapshot().data.query, query);
  const changed = { ...query, context: { ...query.context, environmentId: "other-env" } };
  mode = "wrong";
  await assert.rejects(resource.load(changed));
  assert.equal(resource.getSnapshot().status, "error");
  assert.ok(!("data" in resource.getSnapshot()));
  assert.equal(resource.getSnapshot().error.code, "invalid_observation");
  resource.dispose();
});
test("FLEET-EMPTY: no directory and filtered empty are explicit, while unintegrated metrics retain honest partial observations", async () => {
  const resource = createFleetResource(
    { readFleet: async (input) => snapshotFor(input) },
    observe(access()),
  );
  await resource.load({ ...query, search: "not-found" });
  assert.equal(resource.getSnapshot().status, "filtered-empty");
  await resource.load({
    ...query,
    context: { ...query.context, appId: "not-found", scope: "application" },
  });
  assert.equal(resource.getSnapshot().status, "empty");
  await resource.load(query);
  assert.equal(resource.getSnapshot().status, "partial");
  resource.dispose();
});

test("F5.2 overview QPS follows UI locale without changing the numeric observation", () => {
  const qps = 1234.5;
  assert.equal(formatLocaleNumber(qps, "en-US"), "1,234.5");
  assert.equal(formatLocaleNumber(qps, "de-DE"), "1.234,5");
  assert.equal(formatLocaleNumber(qps, "ja-JP"), "1,234.5");
  assert.equal(qps, 1234.5);
});

test("F5.2 instance QPS follows UI locale without changing the numeric observation", () => {
  const qps = 12_345;
  assert.equal(formatLocaleNumber(qps, "en-US"), "12,345");
  assert.equal(formatLocaleNumber(qps, "de-DE"), "12.345");
  assert.equal(formatLocaleNumber(qps, "ja-JP"), "12,345");
  assert.equal(qps, 12_345);
});

test("F5.2 account login timestamps follow UI locale while remaining explicitly zoned", () => {
  const instant = "2026-10-08T05:00:00Z";
  const original = getSystemTimeZone();
  try {
    setSystemTimeZone("Asia/Shanghai");
    for (const locale of ["zh-CN", "en-US", "ja-JP"]) {
      // The zone is named explicitly so a reader can tell which zone the wall clock belongs to.
      assert.match(formatAccountLastLogin(instant, locale), / GMT\+8$/);
      assert.equal(new Date(instant).toISOString(), "2026-10-08T05:00:00.000Z");
    }
    assert.notEqual(
      formatAccountLastLogin(instant, "en-US"),
      formatAccountLastLogin(instant, "ja-JP"),
    );
    // The same wire instant rendered in another configured zone names that zone instead.
    setSystemTimeZone("UTC");
    assert.match(formatAccountLastLogin(instant, "en-US"), / GMT\+0$/);
  } finally {
    setSystemTimeZone(original);
  }
});

test("F5.2 observed UTC instants use locale date conventions without changing the instant", () => {
  const instant = Date.UTC(2026, 9, 8, 5, 0, 0);
  const original = getSystemTimeZone();
  try {
    setSystemTimeZone("Asia/Shanghai");
    const chinese = formatUtcDateTime(instant, "zh-CN");
    const english = formatUtcDateTime(instant, "en-US");
    const japanese = formatUtcDateTime(instant, "ja-JP");
    assert.match(chinese, / GMT\+8$/);
    assert.match(english, / GMT\+8$/);
    assert.match(japanese, / GMT\+8$/);
    assert.notEqual(chinese, english);
    assert.notEqual(english, japanese);
    // 05:00 UTC is 13:00 in the configured zone: the wall clock moved, the instant did not.
    assert.match(english, /1:00:00 PM/);
    assert.equal(new Date(instant).toISOString(), "2026-10-08T05:00:00.000Z");
  } finally {
    setSystemTimeZone(original);
  }
});

test("F5.2 shared UTC formatter supports compact page timestamps and locale-independent zone semantics", () => {
  // 06:59Z and 07:01Z straddle the America/New_York daylight-saving change, so the same
  // configured zone reports a different offset on either side of it.
  const beforeDaylightSavingChange = Date.UTC(2026, 2, 8, 6, 59, 0);
  const afterDaylightSavingChange = Date.UTC(2026, 2, 8, 7, 1, 0);
  const original = getSystemTimeZone();
  try {
    setSystemTimeZone("Asia/Shanghai");
    for (const locale of ["zh-CN", "en-US", "ja-JP"]) {
      const compact = formatUtcDateTime(beforeDaylightSavingChange, locale, {
        dateStyle: "short",
        timeStyle: "medium",
      });
      const markerless = formatUtcInstant(afterDaylightSavingChange, locale, {
        dateStyle: "short",
        timeStyle: "medium",
      });
      assert.match(compact, / GMT\+8$/);
      // The compact formatter carries no zone marker of its own; the caller owns that.
      assert.doesNotMatch(markerless, / GMT[+-]/);
      assert.notEqual(
        compact,
        formatUtcDateTime(afterDaylightSavingChange, locale, {
          dateStyle: "short",
          timeStyle: "medium",
        }),
      );
    }
    // Zone semantics belong to the configured zone, not to the host machine: a zone with a
    // daylight-saving change keeps the same gap between the two instants.
    setSystemTimeZone("America/New_York");
    const before = formatUtcDateTime(beforeDaylightSavingChange, "en-US", {
      dateStyle: "short",
      timeStyle: "medium",
    });
    const after = formatUtcDateTime(afterDaylightSavingChange, "en-US", {
      dateStyle: "short",
      timeStyle: "medium",
    });
    assert.match(before, / GMT-5$/);
    assert.match(after, / GMT-4$/);
    assert.notEqual(before, after);
  } finally {
    setSystemTimeZone(original);
  }
  assert.equal(new Date(beforeDaylightSavingChange).toISOString(), "2026-03-08T06:59:00.000Z");
  assert.equal(new Date(afterDaylightSavingChange).toISOString(), "2026-03-08T07:01:00.000Z");
});

test("F5.2 finite navigation, role, health and status keys render in every locale", async () => {
  const locales = ["zh-CN", "en-US", "ja-JP"];
  const catalogs = Object.fromEntries(
    locales.map((locale) => {
      const bundles = Object.fromEntries(
        readdirSync(`src/app/i18n/messages/${locale}`)
          .filter((name) => name.endsWith(".json"))
          .map((name) => [
            name.slice(0, -5),
            JSON.parse(readFileSync(`src/app/i18n/messages/${locale}/${name}`, "utf8")),
          ]),
      );
      return [locale, assembleMessageCatalog(locale, bundles)];
    }),
  );
  const i18n = createInstance();
  await i18n.init({
    resources: Object.fromEntries(
      locales.map((locale) => [locale, { translation: catalogs[locale] }]),
    ),
    supportedLngs: locales,
    fallbackLng: false,
    nsSeparator: false,
    interpolation: { escapeValue: false },
  });
  const navigation = [...navigationItemsForAccess(true), ...navigationItemsForAccess(false)].map(
    (item) => item.i18nKey,
  );
  const roleKeys = IDENTITY_ROLES.flatMap((role) => {
    const copy = rolePresentationFor(role.id);
    return [copy.labelKey, copy.descriptionKey];
  });
  const feedbackKeys = [
    accountFeedbackKey({ authorized: false, inspecting: false, mutation: { status: "idle" } }),
    accountFeedbackKey({ authorized: true, inspecting: true, mutation: { status: "idle" } }),
    ...[
      { status: "pending" },
      { status: "success" },
      { status: "result-unknown" },
      { status: "conflict" },
      { status: "error", error: { code: "account_username_taken" } },
      { status: "error", error: { code: "account_last_admin" } },
      { status: "error", error: { code: "account_built_in" } },
      { status: "error", error: { code: "other" } },
    ].map((mutation) => accountFeedbackKey({ authorized: true, inspecting: false, mutation })),
  ].filter((key) => key !== null);
  const keys = [
    ...new Set([
      ...navigation,
      ...roleKeys,
      ...Object.values(OBSERVATION_HEALTH_LABEL_KEY),
      ...feedbackKeys,
    ]),
  ];
  for (const locale of locales)
    for (const key of keys) {
      assert.ok(catalogs[locale][key], `${locale} must define ${key}`);
      const rendered = i18n.t(key, { lng: locale });
      assert.notEqual(rendered, key, `${locale} must translate ${key}`);
      assert.ok(!rendered.includes("{{"), `${locale}/${key} left interpolation unresolved`);
    }
});

test("F5.2 instance health labels match the server-owned finite observation vocabulary", () => {
  assert.deepEqual(
    Object.keys(OBSERVATION_HEALTH_LABEL_KEY).sort(),
    [...Object.values(INSTANCE_HEALTH)].sort(),
  );
});
