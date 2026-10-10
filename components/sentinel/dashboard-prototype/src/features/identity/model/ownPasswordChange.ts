import {
  validatePasswordChange,
  type PasswordChangeDraft,
  type PasswordIssue,
} from "./passwordPolicy";

/** Write-only own-password input. The authenticated server session selects the actor. */
export interface OwnPasswordChange {
  readonly currentPassword: string;
  readonly newPassword: string;
}

/** Validate locally and omit confirmation/target fields; passwords are never trimmed. */
export function prepareOwnPasswordChange(
  draft: PasswordChangeDraft,
):
  | { readonly status: "invalid"; readonly issues: readonly PasswordIssue[] }
  | { readonly status: "valid"; readonly input: OwnPasswordChange } {
  const issues = validatePasswordChange(draft);
  return issues.length
    ? { status: "invalid", issues }
    : {
        status: "valid",
        input: { currentPassword: draft.current, newPassword: draft.next },
      };
}
