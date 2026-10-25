import assert from "node:assert/strict";
import test from "node:test";
import viteConfig from "../vite.config.mjs";
import { resolveConsoleApiProxyTarget, resolveConsoleBasePath } from "../vite.config.mjs";

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

test("DEV-API-PROXY accepts only a credential-free HTTP(S) origin", () => {
  assert.equal(resolveConsoleApiProxyTarget({}), undefined);
  assert.equal(
    resolveConsoleApiProxyTarget({
      SENTINEL_CONSOLE_API_PROXY_TARGET: "http://127.0.0.1:8210",
    }),
    "http://127.0.0.1:8210",
  );
  assert.equal(
    resolveConsoleApiProxyTarget({
      SENTINEL_CONSOLE_API_PROXY_TARGET: "https://console.example.test/",
    }),
    "https://console.example.test",
  );

  for (const target of [
    "",
    "console.example.test",
    "ftp://console.example.test",
    "http://user:secret@console.example.test",
    "http://console.example.test/api",
    "http://console.example.test/?debug=true",
    "http://console.example.test/#fragment",
  ]) {
    assert.throws(
      () => resolveConsoleApiProxyTarget({ SENTINEL_CONSOLE_API_PROXY_TARGET: target }),
      /SENTINEL_CONSOLE_API_PROXY_TARGET/,
      target,
    );
  }
});

test("API-PROXY routes the same-origin API through both dev and production preview", () => {
  const previousTarget = process.env.SENTINEL_CONSOLE_API_PROXY_TARGET;
  process.env.SENTINEL_CONSOLE_API_PROXY_TARGET = "http://127.0.0.1:8210";
  try {
    const config = viteConfig({ command: "serve", mode: "development" });
    const expectedProxy = {
      "/api": {
        target: "http://127.0.0.1:8210",
        changeOrigin: false,
      },
    };

    assert.deepEqual(config.server.proxy, expectedProxy);
    assert.deepEqual(config.preview.proxy, expectedProxy);
  } finally {
    if (previousTarget === undefined) delete process.env.SENTINEL_CONSOLE_API_PROXY_TARGET;
    else process.env.SENTINEL_CONSOLE_API_PROXY_TARGET = previousTarget;
  }
});
