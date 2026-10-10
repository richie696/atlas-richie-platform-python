import assert from "node:assert/strict";
import { readdir, readFile, stat } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const liveRoot = path.resolve(
  process.env.SENTINEL_LIVE_BUILD_DIR ?? path.join(projectRoot, "dist/client"),
);
const demoRoot = path.resolve(
  process.env.SENTINEL_DEMO_BUILD_DIR ?? path.join(projectRoot, "dist/demo/client"),
);

async function listFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(
    entries.map(async (entry) => {
      const entryPath = path.join(directory, entry.name);
      return entry.isDirectory() ? listFiles(entryPath) : [entryPath];
    }),
  );
  return nested.flat();
}

async function artifactText(files) {
  const readable = files.filter((file) => /\.(?:html|js|json|css)$/.test(file));
  return (await Promise.all(readable.map((file) => readFile(file, "utf8")))).join("\n");
}

test("BUILD-LIVE: production artifact excludes mock worker, handlers, legacy gateway, and demo identity", async () => {
  const files = await listFiles(liveRoot);
  const names = files.map((file) => path.basename(file));
  const text = await artifactText(files);

  for (const marker of [
    "mockServiceWorker.js",
    "mockConsoleHandlers",
    "consoleMockHandlers",
    "LegacyDemoGatewayProvider",
    "fixtureGateway",
    "sentinel.mock.role",
    "sentinel.mock.initialized",
    "account-admin",
    "account-view",
    "demo-admin",
  ]) {
    assert.equal(text.includes(marker), false, `live build contains ${marker}`);
    assert.equal(
      names.some((name) => name.includes(marker)),
      false,
      `live artifact emits ${marker}`,
    );
  }
  assert.equal(names.includes("mockServiceWorker.js"), false);
  assert.ok(await stat(path.join(liveRoot, "index.html")));
});

test("BUILD-CHUNKS: vendor boundaries keep each emitted JavaScript chunk below Vite's 500 KiB warning", async () => {
  const chunkLimitBytes = 500 * 1024;

  for (const [profile, root] of [
    ["live", liveRoot],
    ["demo", demoRoot],
  ]) {
    const files = (await listFiles(root)).filter((file) => file.endsWith(".js"));
    assert.ok(files.length > 0, `${profile} profile emits JavaScript chunks`);
    const chunks = await Promise.all(
      files.map(async (file) => ({ file, bytes: (await stat(file)).size })),
    );
    const oversized = chunks.filter((chunk) => chunk.bytes > chunkLimitBytes);
    assert.deepEqual(
      oversized,
      [],
      `${profile} profile has no JavaScript chunk above ${chunkLimitBytes} bytes`,
    );
  }
});

test("BUILD-I18N-LAZY: non-active Astryx catalogs are emitted as deferred locale chunks", async () => {
  const manifest = JSON.parse(await readFile(path.join(liveRoot, ".vite/manifest.json"), "utf8"));
  const entry = Object.values(manifest).find((item) => item.isEntry === true);
  assert.ok(entry, "live build has an app entry");

  const keyFor = (locale) =>
    Object.keys(manifest).find((key) => key.includes(`/locales/${locale}.json`));
  const visit = (key, includeDynamic, visited = new Set()) => {
    if (visited.has(key)) return visited;
    visited.add(key);
    const item = manifest[key];
    for (const dependency of item.imports ?? []) visit(dependency, includeDynamic, visited);
    if (includeDynamic)
      for (const dependency of item.dynamicImports ?? [])
        visit(dependency, includeDynamic, visited);
    return visited;
  };
  const entryKey = Object.keys(manifest).find((key) => manifest[key] === entry);
  assert.ok(entryKey);
  const initial = visit(entryKey, false);
  const complete = visit(entryKey, true);

  for (const locale of ["zh-CN", "ja-JP"]) {
    const catalogKey = keyFor(locale);
    assert.ok(catalogKey, `live build emits the ${locale} Astryx catalog`);
    assert.equal(initial.has(catalogKey), false, `${locale} is not a static entry dependency`);
    assert.equal(
      complete.has(catalogKey),
      true,
      `${locale} is reachable through a deferred import`,
    );
  }
});

test("BUILD-CHART-LAZY: Nivo line renderer remains outside the initial asset closure", async () => {
  const manifestPath = path.join(liveRoot, ".vite/manifest.json");
  const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  const entryKey = Object.keys(manifest).find((key) => manifest[key].isEntry === true);
  const chartKey = Object.keys(manifest).find((key) =>
    key.endsWith("node_modules/@nivo/line/dist/nivo-line.mjs"),
  );
  assert.ok(entryKey, "live build has an app entry");
  assert.ok(chartKey, "live build emits the Nivo line module");

  const visit = (key, includeDynamic, visited = new Set()) => {
    if (visited.has(key)) return visited;
    visited.add(key);
    const item = manifest[key];
    for (const dependency of item.imports ?? []) visit(dependency, includeDynamic, visited);
    if (includeDynamic)
      for (const dependency of item.dynamicImports ?? [])
        visit(dependency, includeDynamic, visited);
    return visited;
  };
  const initial = visit(entryKey, false);
  const complete = visit(entryKey, true);
  assert.equal(initial.has(chartKey), false, "Nivo is not a static app dependency");
  assert.equal(complete.has(chartKey), true, "Nivo is reachable through a deferred import");

  const report = JSON.parse(
    await readFile(path.join(liveRoot, ".vite/bundle-report.json"), "utf8"),
  );
  const chartChunk = report.deferred.find((item) => item.entry === chartKey);
  assert.ok(chartChunk, "bundle report measures the deferred chart chunk");
  assert.ok(
    chartChunk.additionalAfterInitial.files.some((file) => file.file.includes("nivo-line")),
    "the deferred dependency maps to an emitted Nivo chunk",
  );
});

test("BUILD-SETUP-LAZY: first-run database/source commands stay out of the auth startup closure", async () => {
  const manifest = JSON.parse(await readFile(path.join(liveRoot, ".vite/manifest.json"), "utf8"));
  const entryKey = Object.keys(manifest).find((key) => manifest[key].isEntry === true);
  assert.ok(entryKey, "live build has an app entry");

  const visit = (key, includeDynamic, visited = new Set()) => {
    if (visited.has(key)) return visited;
    visited.add(key);
    const item = manifest[key];
    for (const dependency of item.imports ?? []) visit(dependency, includeDynamic, visited);
    if (includeDynamic)
      for (const dependency of item.dynamicImports ?? [])
        visit(dependency, includeDynamic, visited);
    return visited;
  };
  const initial = visit(entryKey, false);
  const complete = visit(entryKey, true);
  const textFor = async (keys) =>
    (
      await Promise.all(
        [...keys]
          .map((key) => manifest[key]?.file)
          .filter((file) => typeof file === "string" && file.endsWith(".js"))
          .map((file) => readFile(path.join(liveRoot, file), "utf8")),
      )
    ).join("\n");
  const initialText = await textFor(initial);
  const completeText = await textFor(complete);

  for (const setupOnlyMarker of [
    "database-check",
    "source-check",
    "/api/v1/system/bootstrap/initialize",
  ]) {
    assert.equal(
      initialText.includes(setupOnlyMarker),
      false,
      `initial auth closure contains setup-only endpoint ${setupOnlyMarker}`,
    );
    assert.equal(
      completeText.includes(setupOnlyMarker),
      true,
      `lazy setup route does not retain endpoint ${setupOnlyMarker}`,
    );
  }
});

test("BUILD-DEMO: explicit demo artifact retains browser HTTP mocks and isolated worker", async () => {
  const files = await listFiles(demoRoot);
  const names = files.map((file) => path.basename(file));
  const text = await artifactText(files);

  assert.ok(names.includes("mockServiceWorker.js"));
  for (const marker of [
    "mockConsoleHandlers",
    "sentinel.mock.role",
    "account-admin",
    "account-view",
  ]) {
    assert.ok(text.includes(marker), `demo build does not include ${marker}`);
  }
  for (const marker of ["LegacyDemoGatewayProvider", "fixtureGateway"]) {
    assert.equal(text.includes(marker), false, `demo build retains obsolete ${marker}`);
  }
  assert.ok(await stat(path.join(demoRoot, "index.html")));
});
