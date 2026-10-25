import assert from "node:assert/strict";
import { test } from "node:test";
import { hostMetricsQueryStepMs } from "../../src/features/realtime/application/hostMetricsResources";

test("HOST-METRICS-QUERY: keeps source charts fresh with a bounded query resolution", () => {
  assert.equal(hostMetricsQueryStepMs(15 * 60 * 1000), 3_000);
  assert.equal(hostMetricsQueryStepMs(60 * 60 * 1000), 12_000);
  assert.equal(hostMetricsQueryStepMs(1), 1_000);
  assert.throws(() => hostMetricsQueryStepMs(0), RangeError);
  assert.throws(() => hostMetricsQueryStepMs(Number.NaN), RangeError);
});
