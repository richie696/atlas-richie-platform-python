import { build } from "esbuild";
import { after } from "node:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

/** Bundle the actual TS modules for node:test; remove only this run's disposable directory. */
const directory = mkdtempSync(path.join(tmpdir(), "sentinel-f0-tests-"));
after(() => rmSync(directory, { recursive: true, force: true }));
const output = path.join(directory, "f0.test.mjs");
await build({
  entryPoints: [fileURLToPath(new URL("./suite.mjs", import.meta.url))],
  outfile: output,
  bundle: true,
  platform: "node",
  format: "esm",
  logLevel: "error",
  // `yaml` ships CommonJS only; its browser distribution is the same parser without the
  // node `process` require. The browser build is also what Vite resolves for the client,
  // so the harness and the application must exercise the same parser.
  alias: {
    yaml: fileURLToPath(
      new URL("../../node_modules/yaml/browser/dist/index.js", import.meta.url),
    ),
  },
});
await import(pathToFileURL(output).href);
