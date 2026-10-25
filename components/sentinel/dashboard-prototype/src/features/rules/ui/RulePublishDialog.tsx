import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import type {
  createRuleDeploymentWorkflow,
  RulePublicationIntent,
} from "../application/ruleDeploymentWorkflow";
import { DialogFrame } from "../../../shared/ui/DialogFrame";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { TextField } from "../../../shared/ui/TextField";
import { FeedbackPanel } from "../../../shared/ui/FeedbackPanel";
import { RuleOperationFeedback } from "./RuleOperationFeedback";
import styles from "./RuleSetWorkspace.module.scss";
import { useBeforeUnloadGuard } from "../../../shared/state/useBeforeUnloadGuard";
/** Display the captured target/base. A late source refresh requires a new confirmation rather than approving unseen content. */
export function RulePublishDialog({
  workflow,
  intent,
  onClose,
  onInspect,
}: {
  readonly workflow: ReturnType<typeof createRuleDeploymentWorkflow>;
  readonly intent: RulePublicationIntent;
  readonly onClose: () => void;
  readonly onInspect: () => void;
}) {
  const { t } = useTranslation(),
    state = useExternalSnapshot(workflow),
    [reason, setReason] = useState(""),
    [failed, setFailed] = useState(false);
  useBeforeUnloadGuard(!!reason || state.locked, state.locked, () => {
    setReason("");
    onClose();
  });
  async function submit() {
    setFailed(false);
    try {
      await workflow.publishVersion(reason, intent);
      onClose();
    } catch {
      setFailed(true);
    }
  }
  return (
    <DialogFrame
      isOpen
      title={t("rules.deployment.publishTarget")}
      subtitle={t("rules.deployment.phaseHint")}
      isBusy={state.locked}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      actions={
        <>
          <ActionButton disabled={state.locked} onClick={onClose}>
            {t("rules.workspace.keepEditing")}
          </ActionButton>
          <ActionButton
            data-deployment-submit-publish
            disabled={state.locked || !reason.trim() || !state.writable}
            onClick={() => void submit()}
          >
            {t("rules.deployment.confirmPublish")}
          </ActionButton>
        </>
      }
    >
      <RuleOperationFeedback
        snapshot={state.operation}
        onInspect={onInspect}
        onReadLatest={() => void workflow.refreshCatalog().catch(() => {})}
      />
      {failed && (
        <FeedbackPanel
          tone="warning"
          copy={{
            title: t("rules.workspace.actionBlocked"),
            description: t("rules.deployment.publishInvalid"),
          }}
        />
      )}
      <dl className={styles.facts}>
        <div>
          <dt>{t("rules.deployment.targetVersion")}</dt>
          <dd>{intent.versionId}</dd>
        </div>
        <div>
          <dt>{t("rules.workspace.checksum")}</dt>
          <dd>{intent.versionChecksum}</dd>
        </div>
        <div>
          <dt>{t("rules.baseline")}</dt>
          <dd>
            {intent.expectedVersionId ?? t("rules.workspace.noVersion")} · {intent.expectedChecksum}
          </dd>
        </div>
      </dl>
      <TextField
        label={t("rules.deployment.reason")}
        hint={t("rules.deployment.reasonHint")}
        value={reason}
        disabled={state.locked}
        onChange={setReason}
      />
      <p>{t("rules.deployment.rollbackHint")}</p>
    </DialogFrame>
  );
}
