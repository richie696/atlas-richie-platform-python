import assert from "node:assert/strict";
import { test } from "node:test";
import { AppError, AppErrorKind } from "@richie696/react-framework";
import { realtimeReadCopy } from "../../src/features/realtime/presentation/realtimeReadCopy";
import { bundleFor } from "../fixtures/observations";

const offline = new AppError(AppErrorKind.NETWORK, "private transport detail");

test("REALTIME-READ-COPY: network failures get localized copy while stale data is retained", () => {
  const snapshot = {
    status: "stale",
    key: "scope-one",
    data: bundleFor(),
    receivedAt: 123,
    error: offline,
  };

  assert.deepEqual(realtimeReadCopy(snapshot), {
    stale: "observation.read.staleNetwork",
  });
});

test("REALTIME-READ-COPY: first network failure uses recovery guidance without exposing the raw error", () => {
  const snapshot = { status: "error", key: "scope-one", error: offline };

  assert.deepEqual(realtimeReadCopy(snapshot), {
    error: "observation.read.errorNetwork",
  });
  assert.doesNotMatch(JSON.stringify(realtimeReadCopy(snapshot)), /private transport detail/);
});

test("REALTIME-READ-COPY: non-network failures retain shared feedback wording", () => {
  const timedOut = new AppError(AppErrorKind.TIMEOUT, "private timeout detail");

  assert.equal(realtimeReadCopy({ status: "error", key: "scope-one", error: timedOut }), undefined);
  assert.equal(
    realtimeReadCopy({
      status: "stale",
      key: "scope-one",
      data: bundleFor(),
      receivedAt: 123,
      error: timedOut,
    }),
    undefined,
  );
});
