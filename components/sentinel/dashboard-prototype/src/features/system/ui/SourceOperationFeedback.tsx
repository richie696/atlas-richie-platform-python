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
  inspectDisabled = false,
  inspectCoolingDown = false,
}: {
  readonly state: ReturnType<ReturnType<typeof createSourceRegistrationWorkflow>["getSnapshot"]>;
  readonly onInspect: () => void;
  readonly onReadLatest: () => void;
  readonly failed: boolean;
  readonly inspectDisabled?: boolean;
  readonly inspectCoolingDown?: boolean;
}) {
  const { t } = useTranslation(),
    title = t("system.source.operation"),
    deleted = state.operation?.kind === "delete";
  return (
    <>
      <CommandFeedback
        snapshot={state.command}
        copy={{
          pending: { title, description: t("system.source.pending") },
          success: {
            title,
            description: t(deleted ? "system.source.deleted" : "system.source.saved"),
          },
          conflict: { title, description: t("system.source.conflict") },
          error: { title, description: t("system.source.failed") },
          "result-unknown": { title, description: t("system.source.unknown") },
        }}
        onInspectOutcome={state.inspecting ? undefined : onInspect}
        inspectDisabled={inspectDisabled}
        onReadLatest={onReadLatest}
      />
      {failed && (
        <FeedbackPanel
          tone="warning"
          copy={{
            title,
            description: t(
              inspectCoolingDown
                ? "system.source.inspectRateLimited"
                : "system.source.inspectFailed",
            ),
          }}
        />
      )}
    </>
  );
}
