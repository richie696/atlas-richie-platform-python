import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { loginFeedback } from "../presentation/loginFeedback";
import type { LoginCredentials } from "../model/account";
import type { SessionIdentity } from "../model/controlPlaneAccess";
import { useAuthentication } from "../state/AuthenticationProvider";
import { LoginSurface } from "./components/LoginSurface";
import { FeedbackPanel } from "../../../shared/ui/FeedbackPanel";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { useLoginCooldown } from "../state/useLoginCooldown";

/**
 * Async login container observing the app's sole authentication owner. A POST
 * alone never navigates: independent session confirmation must resolve identity.
 * Preserve correctable inputs on failure; unknown writes expose only explicit
 * session investigation. Caller owns safe return navigation and setup routing.
 */
export function LoginEntryPage({
  onAuthenticated,
  onSetupRequired,
  demoMode = false,
}: {
  readonly onAuthenticated: (identity: SessionIdentity) => void;
  readonly onSetupRequired: () => void;
  /** True only when the app assembly selected the isolated synthetic demo profile. */
  readonly demoMode?: boolean;
}) {
  const { workflow, snapshot } = useAuthentication();
  const { t } = useTranslation();
  const { retryAfterSeconds, recordRateLimit } = useLoginCooldown();
  const notified = useRef<{ owner: object; epoch: string } | null>(null);
  const setupNotified = useRef<object | null>(null);
  const access = snapshot.access,
    login = snapshot.login;
  const authenticated = access.phase === "resolved" && access.facts.kind === "authenticated";
  const setupRequired =
    access.phase === "resolved" &&
    access.facts.kind === "uninitialized" &&
    access.facts.setupAvailable;
  useEffect(() => {
    if (access.phase !== "resolved") return;
    if (access.facts.kind === "authenticated") {
      const identity = access.facts.identity;
      if (notified.current?.owner === workflow && notified.current.epoch === identity.sessionEpoch)
        return;
      notified.current = { owner: workflow, epoch: identity.sessionEpoch };
      onAuthenticated(identity);
    } else if (
      access.facts.kind === "uninitialized" &&
      access.facts.setupAvailable &&
      setupNotified.current !== workflow
    ) {
      setupNotified.current = workflow;
      onSetupRequired();
    }
  }, [access, workflow, onAuthenticated, onSetupRequired]);
  const anonymous = access.phase === "resolved" && access.facts.kind === "anonymous";
  const hasAttempt = login.status !== "idle";
  const locked = !anonymous || login.status === "pending" || login.status === "result-unknown";
  const showForm = anonymous || (hasAttempt && !authenticated && !setupRequired);
  const feedback = loginFeedback(snapshot, retryAfterSeconds);
  const submit = (credentials: LoginCredentials) => {
    if (retryAfterSeconds > 0 || locked) return;
    void workflow.login(credentials).catch((error: unknown) => recordRateLimit(error));
  };
  return (
    <LoginSurface
      onCredentialsEdited={() => {
        workflow.clearLoginFailure();
      }}
      onSubmit={submit}
      disabled={locked}
      submitDisabled={retryAfterSeconds > 0}
      showForm={showForm}
      allowPasswordReveal
      description={t("login.description")}
      demoNotice={demoMode ? t("login.demoNotice") : undefined}
      feedback={
        feedback && (
          <FeedbackPanel
            tone={feedback.tone}
            isBusy={feedback.busy}
            copy={{ title: t("login.title"), description: t(feedback.key, feedback.values) }}
            actions={
              feedback.canInspect ? (
                <ActionButton onClick={() => void workflow.inspectSession().catch(() => {})}>
                  {t("login.remote.inspect")}
                </ActionButton>
              ) : undefined
            }
          />
        )
      }
    />
  );
}
