import { useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import type { OwnPasswordWorkflow } from "../application/ownPasswordWorkflow";
import type { OwnPasswordReceipt } from "../api/ownPasswordPort";
import type { SessionIdentity } from "../model/controlPlaneAccess";
import type { PasswordIssue } from "../model/passwordPolicy";
import { usePasswordForm } from "../state/usePasswordForm";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { FeedbackPanel } from "../../../shared/ui/FeedbackPanel";
import { IdentityIntro } from "./components/IdentityIntro";
import { IdentityPanel } from "./components/IdentityPanel";
import { PasswordFields } from "./components/PasswordFields";
import styles from "./Identity.module.scss";
import { useBeforeUnloadGuard } from "../../../shared/state/useBeforeUnloadGuard";

/**
 * Own-account password entry. App supplies a stable session-bound workflow and
 * identity, never a URL-selected target. Known errors preserve correctable inputs;
 * success clears them before the app applies the server's session disposition.
 * Unknown writes are investigated by reauthentication, not repeated here.
 */
export function OwnPasswordPage({
  workflow,
  identity,
  onConfirmed,
  onReauthenticate,
}: {
  readonly workflow: OwnPasswordWorkflow;
  readonly identity: SessionIdentity;
  readonly onConfirmed: (receipt: OwnPasswordReceipt) => void;
  readonly onReauthenticate: () => void;
}) {
  const { t } = useTranslation();
  const form = usePasswordForm();
  const { clear } = form;
  const snapshot = useExternalSnapshot(workflow);
  const unresolved = ["pending", "result-unknown"].includes(snapshot.status);
  useBeforeUnloadGuard(
    Object.values(form.values).some((value) => value !== "") || unresolved,
    unresolved,
    clear,
  );
  const [issue, setIssue] = useState<PasswordIssue | null>(null);
  const confirmed = useRef<OwnPasswordReceipt | null>(null);
  useEffect(() => () => workflow.cancel(), [workflow]);
  useEffect(() => {
    if (snapshot.status !== "success" || confirmed.current === snapshot.result) return;
    confirmed.current = snapshot.result;
    clear();
    onConfirmed(snapshot.result);
  }, [snapshot, clear, onConfirmed]);
  const locked = ["pending", "result-unknown", "success"].includes(snapshot.status);
  const errorKey =
    "error" in snapshot
      ? snapshot.error.code === "current_password_invalid"
        ? "password.remote.currentInvalid"
        : snapshot.error.code === "validation_failed"
          ? "password.remote.policy"
          : snapshot.error.code === "rate_limited"
            ? "password.remote.rateLimited"
            : snapshot.error.code === "unauthenticated" || snapshot.error.code === "csrf_failed"
              ? "password.remote.session"
              : "password.remote.failed"
      : "password.remote.failed";
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const result = form.submit();
    setIssue(result.status === "invalid" ? result.issue : null);
    if (result.status === "accepted") void workflow.submit(form.values).catch(() => {});
  };
  return (
    <section data-own-password>
      <IdentityIntro
        eyebrow="SYSTEM / PASSWORD"
        title={t("changePassword.intro.title")}
        description={t("changePassword.intro.description", { username: identity.username })}
      />
      {issue && (
        <FeedbackPanel
          tone="error"
          copy={{ title: t("password.remote.title"), description: t(issue.key, issue.params) }}
        />
      )}
      {snapshot.status !== "idle" && (
        <FeedbackPanel
          tone={
            snapshot.status === "success"
              ? "success"
              : snapshot.status === "pending"
                ? "info"
                : snapshot.status === "result-unknown"
                  ? "warning"
                  : "error"
          }
          isBusy={snapshot.status === "pending"}
          copy={{
            title: t("password.remote.title"),
            description: t(
              snapshot.status === "success"
                ? "password.remote.success"
                : snapshot.status === "pending"
                  ? "password.remote.pending"
                  : snapshot.status === "result-unknown"
                    ? "password.remote.unknown"
                    : errorKey,
            ),
          }}
          actions={
            snapshot.status === "result-unknown" ? (
              <ActionButton
                onClick={() => {
                  clear();
                  onReauthenticate();
                }}
              >
                {t("password.remote.reauthenticate")}
              </ActionButton>
            ) : undefined
          }
        />
      )}
      <IdentityPanel
        title={t("changePassword.panel.title")}
        subtitle={t("password.remote.subtitle")}
      >
        <form className={styles["password-form"]} onSubmit={submit}>
          <PasswordFields form={form} disabled={locked} />
          <div className={styles["identity-form-actions"]}>
            <ActionButton type="submit" disabled={locked}>
              {t("changePassword.submit")}
            </ActionButton>
          </div>
        </form>
      </IdentityPanel>
    </section>
  );
}
