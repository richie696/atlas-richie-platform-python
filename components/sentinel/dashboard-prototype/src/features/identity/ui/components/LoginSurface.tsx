import { useState, type FormEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { LockKeyIcon as LockKey } from "@phosphor-icons/react";
import { ActionButton } from "../../../../shared/ui/ActionButton";
import { TextField } from "../../../../shared/ui/TextField";
import {
  validateLoginCredentials,
  type LoginCredentials,
  type LoginIssue,
} from "../../model/account";
import { FeedbackPanel } from "../../../../shared/ui/FeedbackPanel";
import identityStyles from "../Identity.module.scss";
import introStyles from "../../../../shared/ui/Intro.module.scss";
import actionStyles from "../../../../shared/ui/ActionButton.module.scss";
import { scopedClasses } from "../../../../shared/ui/styles/scopedClasses";

const modules = [identityStyles, introStyles, actionStyles] as const;
const EMPTY_CREDENTIALS: LoginCredentials = Object.freeze({ username: "", password: "" });

/** Login form state is deliberately local so unmounting after confirmed access drops credentials. */
function LoginCredentialForm({
  onCredentialsEdited,
  onSubmit,
  disabled,
  submitDisabled,
  allowPasswordReveal,
}: {
  readonly onCredentialsEdited: () => void;
  readonly onSubmit: (credentials: LoginCredentials) => void;
  readonly disabled: boolean;
  readonly submitDisabled: boolean;
  readonly allowPasswordReveal: boolean;
}) {
  const { t } = useTranslation();
  const [credentials, setCredentials] = useState<LoginCredentials>(EMPTY_CREDENTIALS);
  const [issue, setIssue] = useState<LoginIssue | null>(null);
  const [revealed, setRevealed] = useState(false);
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const issues = validateLoginCredentials(credentials);
    setIssue(issues[0] ?? null);
    if (issues.length === 0) onSubmit(credentials);
  };
  const editUsername = (username: string) => {
    onCredentialsEdited();
    setCredentials((current) => ({ ...current, username }));
    setIssue(null);
  };
  const editPassword = (password: string) => {
    onCredentialsEdited();
    setCredentials((current) => ({ ...current, password }));
    setIssue(null);
  };
  return (
    <>
      {issue && (
        <FeedbackPanel
          tone="error"
          copy={{ title: t("login.title"), description: t(issue.key, issue.params) }}
        />
      )}
      <form className={scopedClasses(modules, "password-form")} onSubmit={submit}>
        <TextField
          label={t("login.field.username")}
          autoComplete="username"
          value={credentials.username}
          onChange={editUsername}
          disabled={disabled}
        />
        <TextField
          label={t("login.field.password")}
          type={revealed ? "text" : "password"}
          autoComplete="current-password"
          value={credentials.password}
          onChange={editPassword}
          disabled={disabled}
        />
        {allowPasswordReveal && (
          <ActionButton
            variant="ghost"
            aria-pressed={revealed}
            onClick={() => setRevealed((value) => !value)}
          >
            {t(revealed ? "login.remote.hidePassword" : "login.remote.showPassword")}
          </ActionButton>
        )}
        <ActionButton
          className={scopedClasses(modules, "primary-button login-submit")}
          type="submit"
          disabled={disabled || submitDisabled}
        >
          <LockKey size={17} />
          {t("login.submit")}
        </ActionButton>
      </form>
    </>
  );
}

/** Shared login anatomy. The credential form owns transient secret state and is discarded on unmount. */
export function LoginSurface({
  onCredentialsEdited,
  onSubmit,
  feedback,
  disabled = false,
  submitDisabled = false,
  showForm = true,
  allowPasswordReveal = false,
  description,
  demoNotice,
}: {
  readonly onCredentialsEdited: () => void;
  readonly onSubmit: (credentials: LoginCredentials) => void;
  readonly feedback?: ReactNode;
  readonly disabled?: boolean;
  /** Disable only command submission while keeping credentials editable. */
  readonly submitDisabled?: boolean;
  readonly showForm?: boolean;
  readonly allowPasswordReveal?: boolean;
  readonly description?: string;
  readonly demoNotice?: string;
}) {
  const { t } = useTranslation();
  return (
    <div className={scopedClasses(modules, "login-page")}>
      <div className={scopedClasses(modules, "login-card")}>
        <div className={scopedClasses(modules, "login-brand")}>
          <span className={scopedClasses(modules, "login-mark")} aria-hidden="true">
            ↗
          </span>
          <span>
            Atlas Richie <b>Sentinel</b>
          </span>
        </div>
        <span className={scopedClasses(modules, "eyebrow")}>OPERATIONS CONSOLE</span>
        <h1>{t("login.title")}</h1>
        {description && (
          <p className={scopedClasses(modules, "login-description")}>{description}</p>
        )}
        {demoNotice && (
          <p className={scopedClasses(modules, "identity-notice login-demo-notice")} role="note">
            {demoNotice}
          </p>
        )}
        {feedback}
        {showForm && (
          <LoginCredentialForm
            onCredentialsEdited={onCredentialsEdited}
            onSubmit={onSubmit}
            disabled={disabled}
            submitDisabled={submitDisabled}
            allowPasswordReveal={allowPasswordReveal}
          />
        )}
      </div>
    </div>
  );
}
