/**
 * Decide whether the isolated Edge process should remain open after E2E.
 * Headless sessions are never useful for manual review and must not outlive
 * their test run, even when the tested application services are retained.
 *
 * @param {{ requested: boolean, headless: boolean }} options
 * @returns {boolean}
 */
export function shouldKeepEdge({ requested, headless }) {
  return requested && !headless;
}
