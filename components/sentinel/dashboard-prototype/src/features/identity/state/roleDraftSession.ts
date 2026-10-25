import {
  createRoleDraftSnapshot,
  restoreRoleDraftSnapshot,
  roleDraftIsDirty,
  type RoleDraft,
} from "../model/accountManagement";

const ROLE_DRAFT_STORAGE_PREFIX = "atlas-richie.sentinel.identity.role-draft.v1";
const ROLE_DRAFT_STORAGE_MAX_LENGTH = 2048;

/** Minimal browser-storage seam so persistence behavior can be tested without a DOM. */
export interface RoleDraftStorage {
  readonly getItem: (key: string) => string | null;
  readonly setItem: (key: string, value: string) => void;
  readonly removeItem: (key: string) => void;
}

/**
 * Build an owner- and target-scoped session key. The opaque session epoch is
 * not a credential; it prevents another authenticated session from restoring
 * this tab's unsaved role edit.
 */
export function roleDraftSessionKey(sessionEpoch: string, accountId: string): string {
  return `${ROLE_DRAFT_STORAGE_PREFIX}:${encodeURIComponent(sessionEpoch)}:${encodeURIComponent(accountId)}`;
}

/** Read a strict, non-sensitive draft snapshot; corrupt or stale data is ignored. */
export function readRoleDraftSession(
  storage: RoleDraftStorage,
  sessionEpoch: string,
  accountId: string,
): RoleDraft | null {
  const key = roleDraftSessionKey(sessionEpoch, accountId);
  try {
    const raw = storage.getItem(key);
    if (raw === null) return null;
    if (raw.length > ROLE_DRAFT_STORAGE_MAX_LENGTH) {
      storage.removeItem(key);
      return null;
    }
    let candidate: unknown;
    try {
      candidate = JSON.parse(raw);
    } catch {
      storage.removeItem(key);
      return null;
    }
    const restored = restoreRoleDraftSnapshot(accountId, candidate);
    if (restored === null) storage.removeItem(key);
    return restored;
  } catch {
    return null;
  }
}

/** Persist only a dirty role edit; storage failure degrades to the in-memory editor. */
export function writeRoleDraftSession(
  storage: RoleDraftStorage,
  sessionEpoch: string,
  draft: RoleDraft,
): void {
  const key = roleDraftSessionKey(sessionEpoch, draft.accountId);
  try {
    if (!roleDraftIsDirty(draft)) {
      storage.removeItem(key);
      return;
    }
    const snapshot = JSON.stringify(createRoleDraftSnapshot(draft));
    if (snapshot.length <= ROLE_DRAFT_STORAGE_MAX_LENGTH) storage.setItem(key, snapshot);
    else storage.removeItem(key);
  } catch {
    // Browser storage is optional; editing and saving remain available in memory.
  }
}

/** Return tab-scoped browser storage when available (including privacy-mode failures). */
export function getRoleDraftSessionStorage(): RoleDraftStorage | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
}
