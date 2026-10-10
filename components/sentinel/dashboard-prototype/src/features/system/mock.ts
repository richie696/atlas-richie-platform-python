import { createSourceRegistrationMockHandlers } from "./fixtures/sourceRegistrationMockHandlers";
import { createSystemObservationMockHandlers } from "./fixtures/systemObservationMockHandlers";

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
  return Object.freeze({
    handlers: Object.freeze([
      ...createSystemObservationMockHandlers(
        { ...scenario, sourceId: scenario.primarySource.id, administratorId },
        now,
      ),
      ...sources.handlers,
    ]),
    readRegisteredSources: sources.readRegisteredSources,
    reset: sources.reset,
  });
}
