import { nextAccountStatus } from "../model/account";
import { accountStatusIssue, type AccountRecord } from "../model/accountManagement";
import type { TranslationKey } from "../../../shared/types/translation";

/** Localized explanation for a status action blocked by a protected account fact. */
export function accountStatusRestrictionCopy(record: AccountRecord): TranslationKey | null {
  const issue = accountStatusIssue(record, nextAccountStatus(record.status));
  if (issue === "built_in") return "management.builtIn";
  if (issue === "last_admin") return "management.lastAdmin";
  return null;
}
