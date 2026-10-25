import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const packageScript = path.join(projectRoot, "scripts", "package-console-assets.mjs");

function createFixture(t, { files, manifestFiles = files } = {}) {
  const root = mkdtempSync(path.join(os.tmpdir(), "sentinel-console-web-package-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const clientRoot = path.join(root, "client");
  const webRoot = path.join(root, "web-output");
  mkdirSync(path.join(clientRoot, ".vite"), { recursive: true });

  const manifest = {
    "src/main.tsx": {
      file: "assets/app-0123456789abcdef.js",
      isEntry: true,
      css: ["assets/app-0123456789abcdef.css"],
      assets: [],
    },
    "src/route.tsx": {
      file: "assets/route-fedcba9876543210.js",
      isDynamicEntry: true,
    },
  };
  for (const file of files) {
    const target = path.join(clientRoot, file);
    mkdirSync(path.dirname(target), { recursive: true });
    writeFileSync(target, `fixture:${file}`);
  }
  writeFileSync(path.join(clientRoot, "index.html"), "<!doctype html><title>Sentinel</title>");
  writeFileSync(
    path.join(clientRoot, ".vite", "manifest.json"),
    JSON.stringify(manifestFiles === files ? manifest : manifestFiles),
  );

  return { root, clientRoot, webRoot };
}

function runPackager({ clientRoot, webRoot }) {
  return spawnSync(process.execPath, [packageScript], {
    encoding: "utf8",
    env: {
      ...process.env,
      SENTINEL_DASHBOARD_CLIENT_BUILD_DIR: clientRoot,
      SENTINEL_CONSOLE_WEB_OUTPUT_DIR: webRoot,
    },
  });
}

test("isolated packaging copies exactly manifest-linked live assets with verified hashes", (t) => {
  const files = [
    "assets/app-0123456789abcdef.js",
    "assets/app-0123456789abcdef.css",
    "assets/route-fedcba9876543210.js",
  ];
  const fixture = createFixture(t, { files });
  const result = runPackager(fixture);

  assert.equal(result.status, 0, result.stderr || result.stdout);
  const marker = JSON.parse(
    readFileSync(path.join(fixture.webRoot, ".dashboard-assets.json"), "utf8"),
  );
  assert.equal(marker.schemaVersion, 1);
  assert.deepEqual(
    marker.files.map((file) => file.path),
    [
      "assets/app-0123456789abcdef.css",
      "assets/app-0123456789abcdef.js",
      "assets/route-fedcba9876543210.js",
      "index.html",
    ],
  );
  for (const entry of marker.files) {
    const bytes = readFileSync(path.join(fixture.webRoot, entry.path));
    assert.equal(entry.bytes, bytes.length);
    assert.equal(entry.sha256, createHash("sha256").update(bytes).digest("hex"));
  }
  assert.equal(existsSync(path.join(fixture.webRoot, "mockServiceWorker.js")), false);
});

test("isolated packaging refuses to replace any existing output directory", (t) => {
  const files = [
    "assets/app-0123456789abcdef.js",
    "assets/app-0123456789abcdef.css",
    "assets/route-fedcba9876543210.js",
  ];
  const fixture = createFixture(t, { files });
  mkdirSync(fixture.webRoot);
  writeFileSync(path.join(fixture.webRoot, "user-data.txt"), "keep");

  const result = runPackager(fixture);

  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /Refusing to replace isolated Console web output directory/);
  assert.equal(readFileSync(path.join(fixture.webRoot, "user-data.txt"), "utf8"), "keep");
});

test("isolated packaging rejects unsafe manifest paths before creating output", (t) => {
  const files = [
    "assets/app-0123456789abcdef.js",
    "assets/app-0123456789abcdef.css",
    "assets/route-fedcba9876543210.js",
  ];
  const manifestFiles = {
    "src/main.tsx": {
      file: "../outside.js",
      isEntry: true,
    },
  };
  const fixture = createFixture(t, { files, manifestFiles });

  const result = runPackager(fixture);

  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /Unsafe production asset path/);
  assert.equal(existsSync(fixture.webRoot), false);
});

test("isolated packaging rejects Demo service worker before creating output", (t) => {
  const files = [
    "assets/app-0123456789abcdef.js",
    "assets/app-0123456789abcdef.css",
    "assets/route-fedcba9876543210.js",
    "mockServiceWorker.js",
  ];
  const manifestFiles = {
    "src/main.tsx": {
      file: "assets/app-0123456789abcdef.js",
      isEntry: true,
      css: ["assets/app-0123456789abcdef.css"],
      assets: [],
    },
    "src/route.tsx": {
      file: "assets/route-fedcba9876543210.js",
      isDynamicEntry: true,
    },
    "src/mockServiceWorker.ts": { file: "mockServiceWorker.js" },
  };
  const fixture = createFixture(t, { files, manifestFiles });

  const result = runPackager(fixture);

  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /must not contain the Demo service worker/);
  assert.equal(existsSync(fixture.webRoot), false);
});
