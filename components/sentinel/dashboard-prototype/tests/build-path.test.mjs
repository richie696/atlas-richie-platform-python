import assert from "node:assert/strict";
import test from "node:test";
import { resolveConsoleBasePath } from "../vite.config.mjs";

test("BUILD-BASE-PATH defaults to origin root and accepts a canonical prefix", () => {
  assert.equal(resolveConsoleBasePath({}), "/");
  assert.equal(
    resolveConsoleBasePath({ SENTINEL_CONSOLE_BASE_PATH: "/ops/sentinel/" }),
    "/ops/sentinel/",
  );
});

test("BUILD-BASE-PATH rejects ambiguous or unsafe path forms", () => {
  for (const basePath of [
    "",
    "ops/sentinel/",
    "/ops/sentinel",
    "/ops//sentinel/",
    "/ops/../sentinel/",
    "/ops/%2e%2e/sentinel/",
    "/ops/sentinel/?mode=demo",
    "/ops/sentinel/#/overview",
    "//ops/sentinel/",
    "/api/",
    "/api/dashboard/",
  ]) {
    assert.throws(
      () => resolveConsoleBasePath({ SENTINEL_CONSOLE_BASE_PATH: basePath }),
      /SENTINEL_CONSOLE_BASE_PATH/,
      basePath,
    );
  }
});
