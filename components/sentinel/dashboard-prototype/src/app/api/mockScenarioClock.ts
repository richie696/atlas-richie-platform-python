/** One captured wall-clock instant shared by every handler in this demo runtime. */
export const MOCK_SCENARIO_NOW_MS = Date.now();

/** Create an immutable clock for one mock-handler assembly or deterministic test. */
export function createMockScenarioClock(nowMs: number = MOCK_SCENARIO_NOW_MS): () => number {
  if (!Number.isSafeInteger(nowMs) || nowMs < 0)
    throw new RangeError(
      "Mock scenario time must be a non-negative safe integer in epoch milliseconds",
    );
  return () => nowMs;
}
