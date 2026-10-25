/** Browser demo handler registry; this module is loaded only for explicit mock mode. */
import { createFleetMockHandlers } from "../../features/overview/mock";
import { createApplicationsMockHandlers } from "../../features/applications/mock";
import { createRealtimeMockHandlers } from "../../features/realtime/mock";
import { createIncidentMockHandlers } from "../../features/faults/mock";
import { createHostAssociationMockHandlers } from "../../features/hosts/mock";
import { createSystemMockHandlers } from "../../features/system/mock";
import { createRuleSetMockHandlers } from "../../features/rules/mock";
import {
  createIdentityMockHandlers,
  createAccountManagementMockHandlers,
} from "../../features/identity/mock";
import { MOCK_APPLICATION_SCENARIO } from "./mockApplicationScenario";
import { MOCK_OBSERVATION_SCENARIO } from "./mockObservationScenario";
import { MOCK_INCIDENT_SCENARIO } from "./mockIncidentScenario";
import { createMockIdentityScenario, MOCK_BOOTSTRAP_PROFILE } from "./mockIdentityScenario";
import { MOCK_RULE_SCENARIO } from "./mockRuleScenario";
import { MOCK_SYSTEM_SCENARIO } from "./mockSystemScenario";
import { createMockScenarioClock, MOCK_SCENARIO_NOW_MS } from "./mockScenarioClock";

/** Create a fresh app-level HTTP mock assembly with isolated handler state. */
export function createAppConsoleMockAssembly(nowMs: number = MOCK_SCENARIO_NOW_MS) {
  const mockClock = createMockScenarioClock(nowMs);
  const applicationsHandlers = createApplicationsMockHandlers(MOCK_APPLICATION_SCENARIO, mockClock);
  const fleetHandlers = createFleetMockHandlers(MOCK_APPLICATION_SCENARIO);
  const realtimeHandlers = createRealtimeMockHandlers(MOCK_OBSERVATION_SCENARIO);
  const incidentHandlers = createIncidentMockHandlers(MOCK_INCIDENT_SCENARIO, mockClock);
  const hostAssociationMock = createHostAssociationMockHandlers(mockClock);
  const identityScenario = createMockIdentityScenario(
    import.meta.env?.VITE_CONSOLE_MOCK_BOOTSTRAP_PROFILE ?? MOCK_BOOTSTRAP_PROFILE.Initialized,
  );
  const mockAdministrator = identityScenario.accounts.find((account) => account.builtIn);
  if (!mockAdministrator)
    throw new Error("The demo identity scenario must define a built-in admin");
  const systemMock = createSystemMockHandlers(
    MOCK_SYSTEM_SCENARIO,
    mockAdministrator.id,
    mockClock,
  );
  const ruleSetMock = createRuleSetMockHandlers(
    MOCK_RULE_SCENARIO,
    mockAdministrator.id,
    mockClock,
    systemMock.readRegisteredSources,
  );
  const identityHandlers = createIdentityMockHandlers(identityScenario);
  const accountHandlers = createAccountManagementMockHandlers(identityScenario, mockClock);

  return Object.freeze({
    nowMs,
    handlers: Object.freeze([
      ...applicationsHandlers,
      ...realtimeHandlers,
      ...incidentHandlers,
      ...systemMock.handlers,
      ...ruleSetMock.handlers,
      ...identityHandlers,
      ...accountHandlers,
      ...fleetHandlers,
      ...hostAssociationMock.handlers,
    ]),
  });
}

export const APP_CONSOLE_MOCK_HANDLERS = createAppConsoleMockAssembly().handlers;
