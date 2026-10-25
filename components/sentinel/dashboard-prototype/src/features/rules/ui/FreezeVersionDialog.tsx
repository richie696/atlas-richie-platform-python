import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import type { createRuleDraftWorkflow } from "../application/ruleDraftWorkflow";
import { DialogFrame } from "../../../shared/ui/DialogFrame";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { FormGrid } from "../../../shared/ui/FormGrid";
import { TextField } from "../../../shared/ui/TextField";
import { RuleOperationFeedback } from "./RuleOperationFeedback";
import { useBeforeUnloadGuard } from "../../../shared/state/useBeforeUnloadGuard";
/** Mount per freeze intent: fields disappear on cancellation, completion or permission revocation. */
export function FreezeVersionDialog({
  workflow,
  canFreeze,
  onClose,
  onInspect,
  act,
}: {
  readonly workflow: ReturnType<typeof createRuleDraftWorkflow>;
  readonly canFreeze: boolean;
  readonly onClose: () => void;
  readonly onInspect: () => void;
  readonly act: (action: () => unknown | Promise<unknown>) => Promise<boolean>;
}) {
  const { t } = useTranslation(),
    state = useExternalSnapshot(workflow);
  const [name, setName] = useState(""),
    [note, setNote] = useState("");
  useBeforeUnloadGuard(!!name || !!note || state.locked, state.locked, () => {
    setName("");
    setNote("");
    onClose();
  });
  return (
    <DialogFrame
      isOpen
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={t("rules.workspace.freeze")}
      subtitle={t("rules.workspace.freezeDescription")}
      isBusy={state.locked}
      actions={
        <>
          <ActionButton disabled={state.locked} onClick={onClose}>
            {t("rules.workspace.keepEditing")}
          </ActionButton>
          <ActionButton
            disabled={state.locked || !name.trim() || !canFreeze}
            onClick={() =>
              void act(() => workflow.freeze(name, note)).then((ok) => {
                if (ok) onClose();
              })
            }
          >
            {t("rules.workspace.freeze")}
          </ActionButton>
        </>
      }
    >
      <RuleOperationFeedback
        snapshot={state.operation}
        onInspect={onInspect}
        onReadLatest={() => void act(workflow.refreshSource)}
      />
      <FormGrid>
        <TextField
          label={t("rules.workspace.versionName")}
          value={name}
          onChange={setName}
          disabled={state.locked}
        />
        <TextField
          label={t("rules.workspace.versionNote")}
          value={note}
          onChange={setNote}
          disabled={state.locked}
        />
      </FormGrid>
    </DialogFrame>
  );
}
