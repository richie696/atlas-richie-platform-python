import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

test("demo-only shell chrome follows the resolved runtime mode, not the Vite build profile", async () => {
  const appSource = await readFile(new URL("../../src/app/App.tsx", import.meta.url), "utf8");

  assert.match(appSource, /const runtime = useConsoleRuntime\(\)/);
  assert.match(appSource, /banner=\{runtime\.mode === "mock" \? <StatusBanner \/> : undefined\}/);
  assert.match(appSource, /footer=\{runtime\.mode === "mock" \? <Footer \/> : undefined\}/);
  assert.doesNotMatch(appSource, /__SENTINEL_CONSOLE_BUILD_PROFILE__ === "demo" \? <StatusBanner/);
});
