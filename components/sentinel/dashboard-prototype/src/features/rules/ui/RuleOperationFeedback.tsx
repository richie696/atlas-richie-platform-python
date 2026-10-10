import { useTranslation } from "react-i18next";
import type { RuleOperationSnapshot } from "../application/ruleOperation";
import { CommandFeedback } from "../../../shared/ui/CommandFeedback";
/** A durable command result is not a source publication or an applied-instance claim. */
export function RuleOperationFeedback({
  snapshot,
  onInspect,
  onReadLatest,
}: {
  readonly snapshot: RuleOperationSnapshot;
  readonly onInspect: () => void;
  readonly onReadLatest: () => void;
}) {
  const { t } = useTranslation();
  const title = t("rules.workspace.commandTitle");
  return (
    <CommandFeedback
      snapshot={snapshot.command}
      onInspectOutcome={snapshot.inspecting ? undefined : onInspect}
      onReadLatest={onReadLatest}
      copy={{
        pending: { title, description: t("rules.workspace.commandPending") },
        success: { title, description: t("rules.workspace.commandSuccess") },
        error: { title, description: t("rules.workspace.commandFailed") },
        conflict: { title, description: t("rules.workspace.commandConflict") },
        "result-unknown": { title, description: t("rules.workspace.commandUnknown") },
      }}
    />
  );
}
