import assert from "node:assert/strict";
import { test } from "node:test";
import {
  reporterFreshness,
  REPORTER_STALE_AFTER_MS,
} from "../../src/features/hosts/presentation/reporterStatus";

test("HOST-ASSOCIATION-REPORTER: derives freshness from accepted heartbeat, not enrollment alone", () => {
  const asOfMs = Date.parse("2026-10-17T12:00:00.000Z");
  assert.equal(
    reporterFreshness({ reporterActive: true, lastReceivedAt: "2026-10-17T11:59:30.000Z" }, asOfMs),
    "active",
  );
  assert.equal(
    reporterFreshness(
      {
        reporterActive: true,
        lastReceivedAt: new Date(asOfMs - REPORTER_STALE_AFTER_MS - 1).toISOString(),
      },
      asOfMs,
    ),
    "stale",
  );
  assert.equal(
    reporterFreshness({ reporterActive: true, lastReceivedAt: null }, asOfMs),
    "unknown",
  );
  assert.equal(
    reporterFreshness({ reporterActive: false, lastReceivedAt: null }, asOfMs),
    "unavailable",
  );
});
