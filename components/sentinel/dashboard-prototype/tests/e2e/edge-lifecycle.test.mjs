import assert from "node:assert/strict";
import { test } from "node:test";
import { shouldKeepEdge } from "../../scripts/test/edge-lifecycle.mjs";

test("manual review may retain a visible Edge session", () => {
  assert.equal(shouldKeepEdge({ requested: true, headless: false }), true);
});

test("retaining services never retains an invisible headless Edge session", () => {
  assert.equal(shouldKeepEdge({ requested: true, headless: true }), false);
});

test("Edge closes after E2E unless explicitly retained for review", () => {
  assert.equal(shouldKeepEdge({ requested: false, headless: false }), false);
  assert.equal(shouldKeepEdge({ requested: false, headless: true }), false);
});
