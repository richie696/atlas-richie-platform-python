import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import { useTranslation } from "react-i18next";
import type { BootstrapAuthorizationWorkflow } from "../application/bootstrapAuthorizationWorkflow";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { FeedbackPanel } from "../../../shared/ui/FeedbackPanel";
import { TextField } from "../../../shared/ui/TextField";

/**
 * Deployment authorization is a distinct one-time gate, not an admin login shortcut.
 * `workflow` must be the route owner's stable instance; this gate restores/reads its state and
 * cancels pending work on unmount. `children` render only after the server confirms authorization.
 * Raw failures and the submitted code are never rendered from the workflow snapshot.
 */
export function BootstrapAuthorizationGate({
  workflow,
  children,
}: {
  readonly workflow: BootstrapAuthorizationWorkflow;
  readonly children: ReactNode;
}) {
  const { t } = useTranslation();
  const snapshot = useExternalSnapshot(workflow);
  const [code, setCode] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const gate = snapshot.gate;
  useEffect(() => {
    // A different operator can authorize or close setup while this gate stays mounted.
    const unsubscribe = workflow.subscribe(() => {
      const current = workflow.getSnapshot().gate;
      if (
        current.status === "ready" &&
        (current.data.kind === "closed" ||
          (current.data.kind === "open" && current.data.authorized))
      )
        setCode("");
    });
    void workflow.restore().catch(() => {});
    return () => {
      unsubscribe();
      workflow.cancel();
    };
  }, [workflow]);

  const inspect = async () => {
    setSubmitting(true);
    try {
      const gate = await workflow.inspect();
      if (gate.kind === "open" && gate.authorized) setCode("");
    } catch {
      // The safe query state owns recoverable feedback; raw exceptions stay hidden.
    } finally {
      setSubmitting(false);
    }
  };
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!code.trim() || submitting) return;
    setSubmitting(true);
    void workflow
      .authorize(code)
      .then(() => setCode(""))
      .catch(() => {})
      .finally(() => setSubmitting(false));
  };

  if (gate.status === "ready" && gate.data.kind === "closed")
    return (
      <FeedbackPanel
        tone="warning"
        copy={{ title: t("setup.operator.closedTitle"), description: t("setup.operator.closed") }}
      />
    );
  if (gate.status === "ready" && gate.data.kind === "open" && gate.data.authorized) return children;

  if (gate.status === "idle" || gate.status === "loading" || gate.status === "refreshing")
    return (
      <FeedbackPanel
        isBusy
        copy={{ title: t("setup.operator.checking"), description: t("setup.operator.description") }}
      />
    );

  const unknown = snapshot.command.status === "result-unknown";
  const failed = ["error", "stale", "denied", "partial"].includes(gate.status);
  return (
    <section data-bootstrap-authorization>
      {failed ? (
        <FeedbackPanel
          tone="error"
          copy={{
            title: t("setup.operator.unavailableTitle"),
            description: t("setup.operator.unavailable"),
          }}
          actions={
            <ActionButton onClick={() => void inspect()} disabled={submitting}>
              {t("shell.feedback.retryRead")}
            </ActionButton>
          }
        />
      ) : (
        <FeedbackPanel
          tone={unknown ? "warning" : "info"}
          copy={{
            title: t(unknown ? "setup.operator.unknownTitle" : "setup.operator.title"),
            description: t(unknown ? "setup.operator.unknown" : "setup.operator.description"),
          }}
          actions={
            unknown ? (
              <ActionButton onClick={() => void inspect()} disabled={submitting}>
                {t("shell.feedback.inspectOutcome")}
              </ActionButton>
            ) : undefined
          }
        />
      )}
      {!failed && !unknown && gate.status === "ready" && gate.data.kind === "open" && (
        <form onSubmit={submit}>
          <TextField
            label={t("setup.operator.code")}
            type="password"
            value={code}
            onChange={setCode}
            autoComplete="off"
            disabled={submitting}
          />
          <ActionButton type="submit" disabled={!code.trim() || submitting}>
            {t("setup.operator.submit")}
          </ActionButton>
        </form>
      )}
    </section>
  );
}
