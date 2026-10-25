import { useTranslation } from "react-i18next";
import type { AccountManagementSnapshot } from "../../application/accountManagementWorkflow";
import { accountFeedbackKey } from "../../presentation/accountFeedback";
import { FeedbackPanel } from "../../../../shared/ui/FeedbackPanel";
import { ActionButton } from "../../../../shared/ui/ActionButton";

/** Mutation notice with explicit read-only recovery; never a retry-POST action. */
export function AccountCommandFeedback({
  snapshot,
  onInspect,
  onReadLatest,
}: {
  readonly snapshot: AccountManagementSnapshot;
  readonly onInspect: () => void;
  readonly onReadLatest?: () => void;
}) {
  const { t } = useTranslation();
  const key = accountFeedbackKey(snapshot);
  if (!key) return null;
  const status = snapshot.mutation.status;
  return (
    <FeedbackPanel
      copy={{ title: t("management.title"), description: t(key) }}
      tone={
        status === "success"
          ? "success"
          : status === "pending" || snapshot.inspecting
            ? "info"
            : status === "result-unknown" || status === "conflict"
              ? "warning"
              : "error"
      }
      isBusy={status === "pending" || snapshot.inspecting}
      actions={
        status === "result-unknown" ? (
          <ActionButton disabled={snapshot.inspecting} onClick={onInspect}>
            {t("shell.feedback.inspectOutcome")}
          </ActionButton>
        ) : status === "conflict" && onReadLatest ? (
          <ActionButton onClick={onReadLatest}>{t("shell.feedback.readLatest")}</ActionButton>
        ) : undefined
      }
    />
  );
}
