import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { createServer } from "vite";

test("T06.6 access revalidation swaps neutral chrome inside the stable AppShell owner", async () => {
  let vite;
  try {
    vite = await createServer({
      configFile: false,
      root: process.cwd(),
      appType: "custom",
      optimizeDeps: { noDiscovery: true, include: [] },
      server: { middlewareMode: true, hmr: false, ws: false },
    });
    const [{ AccessPendingHeader }, React, { renderToStaticMarkup }] = await Promise.all([
      vite.ssrLoadModule("/src/app/shell/AccessPendingHeader.tsx"),
      import("react"),
      import("react-dom/server"),
    ]);
    const markup = renderToStaticMarkup(React.createElement(AccessPendingHeader));
    const appSource = await readFile(new URL("../../src/app/App.tsx", import.meta.url), "utf8");
    const styleSource = await readFile(
      new URL("../../src/app/shell/AppShell.module.scss", import.meta.url),
      "utf8",
    );

    assert.match(markup, /<header[^>]*aria-hidden="true"/);
    assert.equal((markup.match(/<i\b/g) ?? []).length, 9);
    assert.doesNotMatch(markup, /operator-admin|operator|admin/);
    assert.match(appSource, /const accessPending = decision\.kind !== "allow" \|\| !identity/);
    assert.match(appSource, /decision\.kind === "denied" \?/);
    assert.match(appSource, /decision\.kind === "unavailable" \?/);
    assert.match(
      appSource,
      /header=\{\s*accessPending \|\| !identity \?\s*\(\s*<AccessPendingHeader \/>/,
    );
    assert.match(
      appSource,
      /\{accessPending \? <section data-route-state="access-pending">\{accessFeedback\}<\/section> : page\}/,
    );
    assert.match(
      styleSource,
      /\.content:has\(\[data-route-state="loading"\], \[data-route-state="access-pending"\]\)\s*\{\s*min-height:\s*100vh;/,
    );
  } finally {
    await vite?.close();
  }
});
