import { createSourceRegistrationMockHandlers } from "./fixtures/sourceRegistrationMockHandlers";
import { createSystemObservationMockHandlers } from "./fixtures/systemObservationMockHandlers";
import { createMonitoringSourceMockHandlers } from "./fixtures/monitoringSourceMockHandlers";
import { http, HttpResponse } from "msw";
import { CONSOLE_HEADER } from "../../core/api/protocol/common";

interface SystemMockScenario {
  readonly environmentId: string;
  readonly applicationId: string;
  readonly bindingId: string;
  readonly publicationId: string;
  readonly primarySource: Parameters<typeof createSourceRegistrationMockHandlers>[0][number];
  readonly sourceCheck: Parameters<typeof createSourceRegistrationMockHandlers>[1];
  readonly connections: Parameters<typeof createSystemObservationMockHandlers>[0]["connections"];
  readonly protocols: Parameters<typeof createSystemObservationMockHandlers>[0]["protocols"];
  readonly auditEvents: Parameters<typeof createSystemObservationMockHandlers>[0]["auditEvents"];
}

/** Create isolated system-management handlers from the application-owned demo scenario. */
export function createSystemMockHandlers(
  scenario: SystemMockScenario,
  administratorId: string,
  now: () => number = Date.now,
) {
  const sources = createSourceRegistrationMockHandlers(
    [scenario.primarySource],
    scenario.sourceCheck,
    now,
  );
  const monitoringSources = createMonitoringSourceMockHandlers(now);
  let timeZone = "Asia/Shanghai";
  let settingsRevision = 1;
  return Object.freeze({
    handlers: Object.freeze([
      ...createSystemObservationMockHandlers(
        { ...scenario, sourceId: scenario.primarySource.id, administratorId },
        now,
      ),
      ...sources.handlers,
      ...monitoringSources.handlers,
      http.get("*/api/v1/system/settings", ({ request }) =>
        HttpResponse.json(
          { timeZone, revision: settingsRevision },
          {
            headers: {
              [CONSOLE_HEADER.RequestId]:
                request.headers.get(CONSOLE_HEADER.RequestId) ?? "mock-settings-read",
            },
          },
        ),
      ),
      http.put("*/api/v1/system/settings", async ({ request }) => {
        const body = (await request.json()) as { timeZone?: unknown };
        if (typeof body.timeZone !== "string")
          return HttpResponse.json({ error: { code: "invalid_request" } }, { status: 400 });
        timeZone = body.timeZone;
        settingsRevision += 1;
        return HttpResponse.json(
          { timeZone, revision: settingsRevision },
          {
            headers: {
              [CONSOLE_HEADER.RequestId]:
                request.headers.get(CONSOLE_HEADER.RequestId) ?? "mock-settings-write",
            },
          },
        );
      }),
    ]),
    readRegisteredSources: sources.readRegisteredSources,
    reset: sources.reset,
    resetMonitoringSources: monitoringSources.reset,
  });
}
