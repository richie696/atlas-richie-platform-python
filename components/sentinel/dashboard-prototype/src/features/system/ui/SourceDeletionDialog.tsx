import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import type { createSourceRegistrationWorkflow } from "../application/sourceRegistrationWorkflow";
import type { RegisteredSource } from "../model/sourceRegistration";
import { DialogFrame } from "../../../shared/ui/DialogFrame";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { FeedbackPanel } from "../../../shared/ui/FeedbackPanel";
import { SourceOperationFeedback } from "./SourceOperationFeedback";

/** Confirms deletion of one registered source; referenced sources are rejected by the server. */
export function SourceDeletionDialog({
  workflow,
  record,
  onClose,
}: {
  readonly workflow: ReturnType<typeof createSourceRegistrationWorkflow>;
  readonly record: RegisteredSource;
  readonly onClose: () => void;
}) {
  const { t } = useTranslation(),
    state = useExternalSnapshot(workflow);
  const [failed, setFailed] = useState(false);
  const busy = state.command.status === "pending" || state.inspecting,
    unknown = state.command.status === "result-unknown",
    error = state.command.status === "error" ? state.command.error : undefined;

  async function remove() {
    setFailed(false);
    try {
      await workflow.deleteSource(record);
      onClose();
    } catch {
      setFailed(true);
      if (workflow.getSnapshot().command.status === "result-unknown") return;
      if (workflow.getSnapshot().command.status === "conflict") return;
    }
  }

  async function inspect() {
    setFailed(false);
    try {
      const result = await workflow.inspect();
      if (result.status === "completed") onClose();
    } catch {
      setFailed(true);
    }
  }

  const sourceInUse = error?.code === "source_in_use";
  return (
    <DialogFrame
      isOpen
      onOpenChange={(open) => {
        if (!open && !busy) onClose();
      }}
      isBusy={busy}
      title={t("system.source.deleteTitle")}
      subtitle={t("system.source.deleteHint")}
      width={620}
      actions={
        <>
          <ActionButton disabled={busy} onClick={onClose}>
            {t("system.source.close")}
          </ActionButton>
          <ActionButton variant="primary" disabled={busy || unknown} onClick={() => void remove()}>
            {t("system.source.delete")}
          </ActionButton>
        </>
      }
    >
      <p>
        <strong>{record.name}</strong> ({record.provider})
      </p>
      {sourceInUse && (
        <FeedbackPanel
          tone="warning"
          copy={{
            title: t("system.source.inUseTitle"),
            description: t("system.source.inUseHint"),
          }}
        />
      )}
      <SourceOperationFeedback
        state={state}
        failed={failed}
        onInspect={() => void inspect()}
        onReadLatest={() => void workflow.registry.load(null).catch(() => {})}
      />
    </DialogFrame>
  );
}
