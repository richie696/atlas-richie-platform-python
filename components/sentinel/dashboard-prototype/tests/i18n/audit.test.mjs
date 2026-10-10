import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { test } from "node:test";

test("I18N-AUDIT: UI copy is scanned while app API and mock scenario content stays business data", () => {
  const audit = spawnSync(process.execPath, ["tests/i18n/audit.mjs", "--summary"], {
    encoding: "utf8",
  });
  const output = `${audit.stdout}${audit.stderr}`;

  assert.equal(audit.status, 0, output);
  assert.match(audit.stdout, /合计\s+0\s+0\s+共 0 处/);
  assert.doesNotMatch(audit.stdout, /mockObservationScenario|mockRuleScenario/);
});
