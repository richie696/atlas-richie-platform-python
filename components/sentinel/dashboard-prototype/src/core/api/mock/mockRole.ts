/**
 * Role selector for the explicitly enabled browser mock backend only.
 * Production session state never reads this browser key; live authorization is
 * exclusively returned by the Console server.
 */
export const MOCK_ROLE_STORAGE_KEY = "sentinel.mock.role";

export type MockRole = "admin" | "view";

let volatilePrincipal: MockRole | null | undefined;
let volatileStorage: Storage | null | undefined;
const volatilePasswords = new Map<string, string>();

/** Mock-only credentials stay in memory and never enter browser storage or logs. */
export function readMockPassword(username: string, fallback: string): string {
  return volatilePasswords.get(username) ?? fallback;
}

/** Keep password reset flows coherent inside the explicit in-memory Mock backend. */
export function writeMockPassword(username: string, password: string): void {
  volatilePasswords.set(username, password);
}

export function readMockPrincipal(): MockRole | null {
  if (typeof window === "undefined") return volatilePrincipal ?? null;
  try {
    const storage = window.localStorage;
    if (volatilePrincipal !== undefined) {
      if (volatileStorage === undefined || volatileStorage === storage) return volatilePrincipal;
      volatilePrincipal = undefined;
      volatileStorage = undefined;
    }
    const stored = storage.getItem(MOCK_ROLE_STORAGE_KEY);
    return stored === "admin" || stored === "view" ? stored : null;
  } catch {
    return volatilePrincipal ?? null;
  }
}

export function writeMockPrincipal(role: MockRole | null): void {
  if (typeof window === "undefined") {
    volatilePrincipal = role;
    volatileStorage = null;
    return;
  }
  let storage: Storage | undefined;
  try {
    storage = window.localStorage;
    const storedPrincipal = role ?? "anonymous";
    storage.setItem(MOCK_ROLE_STORAGE_KEY, storedPrincipal);
    if (storage.getItem(MOCK_ROLE_STORAGE_KEY) !== storedPrincipal) {
      volatilePrincipal = role;
      volatileStorage = storage;
      return;
    }
    volatilePrincipal = undefined;
    volatileStorage = undefined;
  } catch {
    // Mock storage is optional and never participates in live authentication.
    volatilePrincipal = role;
    volatileStorage = storage;
  }
}
