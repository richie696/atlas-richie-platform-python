import { useTranslation } from "react-i18next";
import type { createSourceRegistrationWorkflow } from "../application/sourceRegistrationWorkflow";
import { CommandFeedback } from "../../../shared/ui/CommandFeedback";
import { FeedbackPanel } from "../../../shared/ui/FeedbackPanel";
/** Uncertain writes expose only original-operation inspection, never automatic resend. */
export function SourceOperationFeedback({
  state,
  onInspect,
  onReadLatest,
  failed,
}: {
  readonly state: ReturnType<ReturnType<typeof createSourceRegistrationWorkflow>["getSnapshot"]>;
  readonly onInspect: () => void;
  readonly onReadLatest: () => void;
  readonly failed: boolean;
}) {
  const { t } = useTranslation(),
    title = t("system.source.operation");
  return (
    <>
      <CommandFeedback
        snapshot={state.command}
        copy={{
          pending: { title, description: t("system.source.pending") },
          success: { title, description: t("system.source.saved") },
          conflict: { title, description: t("system.source.conflict") },
          error: { title, description: t("system.source.failed") },
          "result-unknown": { title, description: t("system.source.unknown") },
        }}
        onInspectOutcome={state.inspecting ? undefined : onInspect}
        onReadLatest={onReadLatest}
      />
      {failed && (
        <FeedbackPanel
          tone="warning"
          copy={{ title, description: t("system.source.inspectFailed") }}
        />
      )}
    </>
  );
}
