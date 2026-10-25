import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const packageManifest = JSON.parse(
  readFileSync(new URL("../../package.json", import.meta.url), "utf8"),
);
const scripts = packageManifest.scripts;

test("CADENCE: daily check stays fast and milestone check owns the full non-browser suite", () => {
  assert.equal(scripts.check, "npm run check:fast");
  assert.equal(scripts["check:milestone"], "npm run check:full");
  assert.match(scripts["check:fast"], /typecheck/);
  assert.match(scripts["check:full"], /test:logic/);
  assert.match(scripts["check:full"], /test:http/);
  assert.doesNotMatch(scripts["check:fast"], /test:e2e|check:full/);
  assert.doesNotMatch(scripts["check:full"], /test:e2e/);
});

test("CADENCE: automated verify defaults to static-only and focused logic/HTTP runners remain explicit", () => {
  assert.equal(scripts.verify, "node scripts/verify.mjs --static-only");
  assert.equal(scripts["test:logic:focused"], "node scripts/test/run-focused.mjs logic");
  assert.equal(scripts["test:http:focused"], "node scripts/test/run-focused.mjs http");
  assert.match(
    readFileSync(new URL("../../docs/TESTING_CADENCE.md", import.meta.url), "utf8"),
    /Codex 内置浏览器/,
  );
  assert.match(
    readFileSync(new URL("../../docs/TESTING_CADENCE.md", import.meta.url), "utf8"),
    /全部计划实现完成后的最终验收/,
  );
});

test("CADENCE: GitHub runs the fast gate on ordinary events and reserves the full gate for manual milestones", () => {
  const workflow = readFileSync(
    new URL("../../../../../.github/workflows/dashboard.yml", import.meta.url),
    "utf8",
  );
  assert.match(workflow, /pull_request:/);
  assert.match(workflow, /push:/);
  assert.match(workflow, /npm run check:fast/);
  assert.match(workflow, /workflow_dispatch:/);
  assert.match(workflow, /default: fast/);
  assert.match(workflow, /inputs\.scope == 'milestone'/);
  assert.match(workflow, /npm run check:milestone/);
  assert.doesNotMatch(workflow, /CHROME_BIN|test:e2e|scripts\/verify\.mjs/);
});
