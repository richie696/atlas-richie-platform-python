import {
  requiresConsoleMockInterception,
  type ConsoleRuntimeConfiguration,
} from "./consoleRuntimeConfiguration";
import type { RequestHandler } from "msw";

/** Start HTTP-level mocking before React mounts; live mode deliberately installs no interceptor. */
export async function startConsoleInterception(
  configuration: ConsoleRuntimeConfiguration,
  featureHandlers: readonly RequestHandler[] = [],
): Promise<void> {
  if (!requiresConsoleMockInterception(configuration.mode)) return;
  const [{ setupWorker }, { CONSOLE_MOCK_HANDLERS }] = await Promise.all([
    import("msw/browser"),
    import("./consoleMockHandlers"),
  ]);
  await setupWorker(...featureHandlers, ...CONSOLE_MOCK_HANDLERS).start();
}
