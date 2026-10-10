import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const sourceRoot = fileURLToPath(new URL("../../src/", import.meta.url));
const featureRoot = path.join(sourceRoot, "features");
const coreApiRoot = path.join(sourceRoot, "core", "api");
const sharedApiRoot = path.join(sourceRoot, "shared", "api");

function apiSources() {
  const files = [];
  function walk(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const current = path.join(directory, entry.name);
      if (entry.isDirectory()) walk(current);
      else if (/\.tsx?$/.test(entry.name) && current.split(path.sep).includes("api"))
        files.push(current);
    }
  }
  walk(featureRoot);
  walk(coreApiRoot);
  walk(sharedApiRoot);
  return files;
}

test("F6.2 API mappers do not assert unknown wire data into domain model types", () => {
  const modelAssertion =
    /\bas\s+(?:any|unknown|never|object|string|number|boolean|[A-Z][A-Za-z0-9_.]*(?:\[\])?)\b/g;
  assert.match("value as RuleSetSnapshot", modelAssertion);
  assert.doesNotMatch("value as const", modelAssertion);
  const violations = apiSources().flatMap((file) => {
    const source = readFileSync(file, "utf8");
    return [...source.matchAll(new RegExp(modelAssertion.source, "g"))].map((match) => ({
      file: path.relative(sourceRoot, file),
      assertion: match[0],
    }));
  });
  assert.deepEqual(violations, []);
});
