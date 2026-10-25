/** Runtime API mode is a transport concern; feature code never branches on it. */
export type ConsoleRuntimeMode = "mock" | "live";

/** Validated destination consumed by the single Console HTTP transport. */
export interface ConsoleRuntimeConfiguration {
  readonly mode: ConsoleRuntimeMode;
  readonly apiBaseUrl: string;
}

export interface ConsoleRuntimeEnvironment {
  readonly mode?: string;
  readonly apiBaseUrl?: string;
}

/** Only the explicit mock runtime installs browser request handlers. */
export function requiresConsoleMockInterception(mode: ConsoleRuntimeMode): boolean {
  return mode === "mock";
}

/** A live-only artifact cannot load handlers, fixture providers, or mock roles. */
export type ConsoleBuildProfile = "demo" | "live-only";

/** Resolve explicit mock/live policy and reject unsafe or ambiguous API origins. */
export function resolveConsoleRuntimeConfiguration(
  environment: ConsoleRuntimeEnvironment,
  pageOrigin: string,
  buildProfile: ConsoleBuildProfile,
): ConsoleRuntimeConfiguration {
  const mode = environment.mode ?? (buildProfile === "demo" ? "mock" : "live");
  if (mode !== "mock" && mode !== "live") {
    throw new Error("Set VITE_CONSOLE_MODE to 'mock' or 'live' before starting the dashboard");
  }

  if (mode === "mock") {
    if (buildProfile === "live-only") {
      throw new Error("Mock mode is unavailable in the live-only production build");
    }
    if (environment.apiBaseUrl) {
      throw new Error("VITE_CONSOLE_API_BASE_URL is not allowed in mock mode");
    }
    return Object.freeze({ mode, apiBaseUrl: originOf(pageOrigin) });
  }

  if (!environment.apiBaseUrl && buildProfile !== "live-only") {
    throw new Error("VITE_CONSOLE_API_BASE_URL is required in live mode");
  }
  return Object.freeze({
    mode,
    apiBaseUrl: originOf(environment.apiBaseUrl ?? pageOrigin),
  });
}

function originOf(value: string): string {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error("Console API base URL must be an absolute HTTP(S) origin");
  }
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.pathname !== "/" ||
    url.search ||
    url.hash
  ) {
    throw new Error("Console API base URL must be an origin without credentials, path or query");
  }
  return url.origin;
}
