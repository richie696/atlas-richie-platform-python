import { useTranslation } from "react-i18next";
import { ActionButton } from "../../../../shared/ui/ActionButton";
import { FeedbackPanel } from "../../../../shared/ui/FeedbackPanel";
import type {
  InitializationSnapshot,
  InitializationState,
} from "../../application/initializationWorkflow";
import type { ConnectionCheck } from "../../api/initializationPort";
import type { QuerySnapshot } from "../../../../shared/state/queryResource";
import type { TranslationKey } from "../../../../shared/types/translation";
import { initializationFeedbackKey } from "../../presentation/setupFeedback";

const CONNECTION_FAILURE_COPY = Object.freeze({
  authentication: "setup.check.authenticationFailed",
  connection: "setup.check.connectionFailed",
  unsupported: "setup.check.unsupported",
} satisfies Record<
  Extract<ConnectionCheck, { readonly status: "unreachable" }>["reason"],
  TranslationKey
>);

function ConnectionFeedback({
  snapshot,
  title,
}: {
  readonly snapshot: QuerySnapshot<ConnectionCheck>;
  readonly title: string;
}) {
  const { t } = useTranslation();
  if (snapshot.status === "idle") return null;
  const pending = snapshot.status === "loading" || snapshot.status === "refreshing";
  const reachable = snapshot.status === "ready" && snapshot.data.status === "reachable";
  const description = pending
    ? "setup.check.pending"
    : reachable
      ? "setup.check.reachable"
      : snapshot.status === "ready" && snapshot.data.status === "unreachable"
        ? CONNECTION_FAILURE_COPY[snapshot.data.reason]
        : "setup.check.failed";
  return (
    <FeedbackPanel
      copy={{ title, description: t(description) }}
      tone={pending ? "info" : reachable ? "success" : "warning"}
      isBusy={pending}
    />
  );
}

/** Safe setup outcomes and read-only investigation actions; never render error.message or a credential. */
export function InitializationFeedback({
  snapshot,
  onInspect,
  onRestore,
}: {
  readonly snapshot: InitializationSnapshot;
  readonly onInspect: () => void;
  readonly onRestore: () => void;
}) {
  const { t } = useTranslation();
  const status = snapshot.initialization.status;
  const uncertain = status === "result-unknown" || status === "pending";
  const busy = status === "submitting" || status === "checking";
  const bootstrapFailed = ["error", "stale", "denied"].includes(snapshot.bootstrap.status);
  const setupWasClosed =
    status === "closed" ||
    (status === "rejected" && snapshot.initialization.reason === "setup-closed");
  const unavailableWindow =
    snapshot.bootstrap.status === "ready" &&
    (snapshot.bootstrap.data.initialized || !snapshot.bootstrap.data.setupAvailable);
  return (
    <section data-setup-state={status}>
      {status !== "idle" && (
        <FeedbackPanel
          copy={{
            title: t("setup.workflow.title"),
            description: t(initializationFeedbackKey(snapshot.initialization)),
          }}
          tone={status === "ready" ? "success" : busy ? "info" : "warning"}
          isBusy={busy}
          actions={
            uncertain ? (
              <ActionButton onClick={onInspect}>{t("shell.feedback.inspectOutcome")}</ActionButton>
            ) : setupWasClosed ? (
              <ActionButton onClick={onRestore}>{t("shell.feedback.retryRead")}</ActionButton>
            ) : undefined
          }
        />
      )}
      {status === "idle" && snapshot.bootstrap.status === "loading" && (
        <FeedbackPanel
          copy={{ title: t("setup.workflow.title"), description: t("setup.workflow.checking") }}
          isBusy
        />
      )}
      {status === "idle" && unavailableWindow && (
        <FeedbackPanel
          copy={{
            title: t("setup.workflow.title"),
            description: t(
              snapshot.bootstrap.status === "ready" && snapshot.bootstrap.data.initialized
                ? "setup.workflow.closed"
                : "setup.workflow.unavailable",
            ),
          }}
          tone="warning"
        />
      )}
      {bootstrapFailed && !uncertain && !busy && (
        <FeedbackPanel
          copy={{ title: t("setup.workflow.title"), description: t("setup.workflow.unavailable") }}
          tone="error"
          actions={<ActionButton onClick={onRestore}>{t("shell.feedback.retryRead")}</ActionButton>}
        />
      )}
      <ConnectionFeedback snapshot={snapshot.databaseCheck} title={t("setup.field.database")} />
      <ConnectionFeedback snapshot={snapshot.sourceCheck} title={t("setup.field.ruleSource")} />
    </section>
  );
}
