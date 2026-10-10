import { IDENTITY_ROLE, IDENTITY_ROLES, roleFor, type IdentityRoleId } from "../model/account";
import type { AccountRecord } from "../model/accountManagement";
import type { QuerySnapshot } from "../../../shared/state/queryResource";
import type { TranslationKey } from "../../../shared/types/translation";

/** Role meanings/permissions stay in model; their labels never become role IDs. */
const ROLE_COPY = Object.freeze({
  [IDENTITY_ROLE.Admin]: {
    labelKey: "roles.role.admin.title",
    descriptionKey: "roles.role.admin.description",
  },
  [IDENTITY_ROLE.View]: {
    labelKey: "roles.role.view.title",
    descriptionKey: "roles.role.view.description",
  },
} satisfies Record<
  IdentityRoleId,
  { readonly labelKey: TranslationKey; readonly descriptionKey: TranslationKey }
>);

export const ROLE_OPTIONS = Object.freeze(
  IDENTITY_ROLES.map((role) => Object.freeze({ ...role, ...ROLE_COPY[role.id] })),
);

/** Read-only UI projection, not authorization or server response validation. */
export function rolePresentationFor(id: IdentityRoleId) {
  const role = roleFor(id);
  return { ...role, ...ROLE_COPY[role.id] };
}

/**
 * Copy for a deep-linked account option absent from the loaded directory page.
 * Only an authoritative empty detail read means "not found"; an old-key snapshot
 * or a failed read must not be projected as account absence.
 */
export function roleTargetFallbackCopy(
  snapshot: QuerySnapshot<AccountRecord | null>,
): TranslationKey {
  switch (snapshot.status) {
    case "empty":
      return "management.read.empty";
    case "denied":
      return "management.denied";
    case "error":
      return "management.read.failed";
    case "stale":
      return "management.read.stale";
    case "partial":
      return "management.read.partial";
    case "idle":
    case "loading":
    case "refreshing":
    case "ready":
    case "filtered-empty":
      // A ready value for another URL target is stale for this option. It is not
      // evidence that the selected account is missing.
      return "management.read.loading";
  }
}

/** Static account facts that explain why the role editor is intentionally locked. */
export function roleEditRestrictionCopy(record: AccountRecord): TranslationKey | null {
  if (record.status === "disabled") return "roles.restriction.disabled";
  if (record.builtIn) return "roles.restriction.builtIn";
  if (record.lastActiveAdmin) return "roles.restriction.lastAdmin";
  return null;
}
