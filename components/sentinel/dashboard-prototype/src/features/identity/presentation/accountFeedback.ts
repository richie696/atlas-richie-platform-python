import type { AccountManagementSnapshot } from "../application/accountManagementWorkflow";
import type { TranslationKey } from "../../../shared/types/translation";

/** Stable safe message keys; raw server messages and credentials never become UI copy. */
export function accountFeedbackKey(snapshot: AccountManagementSnapshot): TranslationKey | null {
  if (!snapshot.authorized) return "management.denied";
  if (snapshot.inspecting) return "management.inspecting";
  const command = snapshot.mutation;
  if (command.status === "idle") return null;
  if (command.status === "pending") return "management.pending";
  if (command.status === "success") return "management.success";
  if (command.status === "result-unknown") return "management.unknown";
  const code = "error" in command ? command.error.code : undefined;
  if (code === "account_username_taken") return "management.usernameTaken";
  if (code === "account_last_admin") return "management.lastAdmin";
  if (code === "account_built_in") return "management.builtIn";
  if (command.status === "conflict") return "management.conflict";
  return "management.failed";
}
