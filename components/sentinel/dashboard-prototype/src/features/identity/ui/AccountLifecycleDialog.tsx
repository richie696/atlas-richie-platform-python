import { useEffect, useId, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import type { AccountManagementWorkflow } from "../application/accountManagementWorkflow";
import { generateAccountPassword } from "../application/generateAccountPassword";
import type { AccountRecord } from "../model/accountManagement";
import { PASSWORD_MIN_LENGTH, PASSWORD_MAX_LENGTH } from "../model/passwordPolicy";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { DialogFrame } from "../../../shared/ui/DialogFrame";
import { TextField } from "../../../shared/ui/TextField";
import { useBeforeUnloadGuard } from "../../../shared/state/useBeforeUnloadGuard";
import { AccountCommandFeedback } from "./components/AccountCommandFeedback";
import styles from "./Identity.module.scss";

/** Feature-owned lifecycle intent. Passwords are transient and cleared before the request settles. */
export function AccountLifecycleDialog({
  workflow,
  kind,
  account,
  onOwnPasswordReset,
  onClose,
}: {
  readonly workflow: AccountManagementWorkflow;
  readonly kind: "reset_password" | "delete";
  readonly account: AccountRecord;
  readonly onOwnPasswordReset: () => void;
  readonly onClose: () => void;
}) {
  const { t } = useTranslation();
  const formId = useId();
  const snapshot = useExternalSnapshot(workflow);
  const [target, setTarget] = useState(account);
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [generationFailed, setGenerationFailed] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [invalid, setInvalid] = useState(false);
  const locked =
    snapshot.inspecting || ["pending", "result-unknown"].includes(snapshot.mutation.status);
  useBeforeUnloadGuard(password !== "" || confirmation !== "" || locked, locked, () =>
    setPassword(""),
  );
  useEffect(() => {
    if (!snapshot.authorized) {
      onClose();
      return;
    }
    if (submitted && snapshot.operation?.kind === kind && snapshot.mutation.status === "success") {
      if (kind === "reset_password" && target.id === workflow.ownerAccountId) onOwnPasswordReset();
      onClose();
    }
  }, [
    snapshot.authorized,
    snapshot.operation?.kind,
    snapshot.mutation.status,
    submitted,
    kind,
    target.id,
    workflow.ownerAccountId,
    onOwnPasswordReset,
    onClose,
  ]);
  const close = () => {
    setPassword("");
    onClose();
  };
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (locked) return;
    if (kind === "delete" && confirmation !== target.username) {
      setInvalid(true);
      return;
    }
    if (
      kind === "reset_password" &&
      (password.length < PASSWORD_MIN_LENGTH || password.length > PASSWORD_MAX_LENGTH)
    ) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    setSubmitted(true);
    const pending =
      kind === "reset_password"
        ? workflow.resetPassword(target, password)
        : workflow.deleteAccount(target);
    setPassword("");
    void pending.catch(() => {});
  };
  return (
    <DialogFrame
      isOpen
      isBusy={locked}
      onOpenChange={(open) => {
        if (!open && !locked) close();
      }}
      title={t(
        kind === "reset_password" ? "accounts.action.resetPassword" : "accounts.action.delete",
      )}
      subtitle={t("management.statusImpact", { username: target.username })}
      actions={
        <>
          <ActionButton disabled={locked} onClick={close}>
            {t("accountDialog.action.cancel")}
          </ActionButton>
          <ActionButton type="submit" form={formId} disabled={locked}>
            {t(
              kind === "reset_password"
                ? "accounts.action.resetPassword"
                : "accounts.action.delete",
            )}
          </ActionButton>
        </>
      }
    >
      {submitted && (
        <AccountCommandFeedback
          snapshot={snapshot}
          onInspect={() => void workflow.inspect().catch(() => {})}
          onReadLatest={() =>
            void workflow
              .select(target.id)
              .then((latest) => {
                if (latest) {
                  setTarget(latest);
                  setSubmitted(false);
                } else close();
              })
              .catch(() => {})
          }
        />
      )}
      <form id={formId} onSubmit={submit} className={styles["account-dialog-form"]}>
        <p>{t(kind === "reset_password" ? "management.resetImpact" : "management.deleteImpact")}</p>
        {kind === "reset_password" && (
          <>
            <TextField
              label={t("management.newPassword")}
              type={showPassword ? "text" : "password"}
              autoComplete="new-password"
              value={password}
              onChange={setPassword}
              disabled={locked}
              hint={t("accountDialog.passwordHint", {
                min: PASSWORD_MIN_LENGTH,
                max: PASSWORD_MAX_LENGTH,
              })}
              error={
                invalid
                  ? t("management.passwordInvalid", {
                      min: PASSWORD_MIN_LENGTH,
                      max: PASSWORD_MAX_LENGTH,
                    })
                  : undefined
              }
            />
            <div className={styles["identity-actions"]}>
              <ActionButton
                disabled={locked}
                onClick={() => {
                  try {
                    setPassword(generateAccountPassword());
                    setInvalid(false);
                    setGenerationFailed(false);
                    setShowPassword(true);
                  } catch {
                    setGenerationFailed(true);
                  }
                }}
              >
                {t("management.generatePassword")}
              </ActionButton>
              <ActionButton
                disabled={locked || password === ""}
                onClick={() => setShowPassword((visible) => !visible)}
              >
                {t(showPassword ? "login.remote.hidePassword" : "login.remote.showPassword")}
              </ActionButton>
            </div>
            {generationFailed && <p role="alert">{t("management.passwordGenerationFailed")}</p>}
          </>
        )}
        {kind === "delete" && (
          <TextField
            label={t("management.confirmAccountName")}
            value={confirmation}
            onChange={setConfirmation}
            disabled={locked}
            autoComplete="off"
            error={invalid ? t("management.confirmAccountNameMismatch") : undefined}
          />
        )}
      </form>
    </DialogFrame>
  );
}
