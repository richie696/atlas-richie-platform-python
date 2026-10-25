import { useEffect, useId, useState, type FormEvent } from "react";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import { useTranslation } from "react-i18next";
import type { AccountManagementWorkflow } from "../application/accountManagementWorkflow";
import { IDENTITY_ROLE, type AccountDraft, type AccountDraftIssue } from "../model/account";
import { PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH } from "../model/passwordPolicy";
import { prepareAccountCreation } from "../model/accountManagement";
import { DialogFrame } from "../../../shared/ui/DialogFrame";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { FeedbackPanel } from "../../../shared/ui/FeedbackPanel";
import { AccountFields } from "./components/AccountFields";
import { AccountCommandFeedback } from "./components/AccountCommandFeedback";
import styles from "./Identity.module.scss";
import { useBeforeUnloadGuard } from "../../../shared/state/useBeforeUnloadGuard";

const EMPTY: AccountDraft = Object.freeze({
  username: "",
  password: "",
  roleId: IDENTITY_ROLE.View,
});
/**
 * The caller mounts this dialog only while open. Close/unmount releases secrets.
 * Pending/unknown cannot dismiss or replay; only confirmed create clears and closes.
 * Known rejection preserves correctable inputs. No ID generation or account store mutation.
 */
export function CreateAccountDialog({
  workflow,
  onClose,
}: {
  readonly workflow: AccountManagementWorkflow;
  readonly onClose: () => void;
}) {
  const { t } = useTranslation(),
    formId = useId();
  const snapshot = useExternalSnapshot(workflow);
  const [draft, setDraft] = useState(EMPTY),
    [issue, setIssue] = useState<AccountDraftIssue | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const close = () => {
    setDraft(EMPTY);
    setIssue(null);
    onClose();
  };
  useEffect(() => {
    if (
      !snapshot.authorized ||
      (submitted && snapshot.mutation.status === "success" && snapshot.operation?.kind === "create")
    ) {
      onClose();
    }
  }, [snapshot.authorized, snapshot.mutation.status, snapshot.operation?.kind, submitted, onClose]);
  const locked =
    !snapshot.authorized ||
    snapshot.inspecting ||
    ["pending", "result-unknown"].includes(snapshot.mutation.status);
  useBeforeUnloadGuard(
    snapshot.authorized &&
      (draft.username !== "" || draft.password !== "" || draft.roleId !== EMPTY.roleId || locked),
    snapshot.authorized && locked,
    () => setDraft(EMPTY),
  );
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (locked) return;
    const prepared = prepareAccountCreation(draft);
    setIssue(prepared.status === "invalid" ? prepared.issues[0] : null);
    if (prepared.status === "valid") {
      setSubmitted(true);
      void workflow.create(prepared.input).catch(() => {});
    }
  };
  return (
    <DialogFrame
      isOpen
      onOpenChange={(open) => {
        if (!open && !locked) close();
      }}
      title={t("accountDialog.title")}
      subtitle={t("accountDialog.subtitle")}
      isBusy={locked}
      actions={
        <>
          <ActionButton disabled={locked} onClick={close}>
            {t("accountDialog.action.cancel")}
          </ActionButton>
          <ActionButton type="submit" form={formId} disabled={locked}>
            {t("accountDialog.action.create")}
          </ActionButton>
        </>
      }
    >
      {submitted && (
        <AccountCommandFeedback
          snapshot={snapshot}
          onInspect={() => void workflow.inspect().catch(() => {})}
        />
      )}
      {issue && (
        <FeedbackPanel
          tone="error"
          copy={{ title: t("management.title"), description: t(issue.key, issue.params) }}
        />
      )}
      <form id={formId} className={styles["account-dialog-form"]} onSubmit={submit}>
        <AccountFields draft={draft} onChange={setDraft} disabled={locked} />
        <p className={styles["account-dialog-password-note"]}>
          {t("accountDialog.passwordHint", { min: PASSWORD_MIN_LENGTH, max: PASSWORD_MAX_LENGTH })}
        </p>
      </form>
    </DialogFrame>
  );
}
