import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import type { createRuleDeploymentWorkflow } from "../application/ruleDeploymentWorkflow";
import type { RuleActivationPlan } from "../model/ruleActivation";
import { DialogFrame } from "../../../shared/ui/DialogFrame";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { TextField } from "../../../shared/ui/TextField";
import { FeedbackPanel } from "../../../shared/ui/FeedbackPanel";
import { RuleOperationFeedback } from "./RuleOperationFeedback";
import { useBeforeUnloadGuard } from "../../../shared/state/useBeforeUnloadGuard";
/** A revision-bound cancel confirmation; no local optimistic plan-state rewrite or implicit content rollback. */
export function RuleCancelPlanDialog({
  workflow,
  plan,
  onClose,
  onInspect,
}: {
  readonly workflow: ReturnType<typeof createRuleDeploymentWorkflow>;
  readonly plan: RuleActivationPlan;
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
      await workflow.cancelPlan(plan.id, plan.revision, reason);
      onClose();
    } catch {
      setFailed(true);
    }
  }
  return (
    <DialogFrame
      isOpen
      title={t("rules.deployment.cancelPlan")}
      subtitle={plan.id}
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
            data-deployment-submit-cancel
            disabled={state.locked || !reason.trim() || !state.writable}
            onClick={() => void submit()}
          >
            {t("rules.deployment.confirmCancel")}
          </ActionButton>
        </>
      }
    >
      <RuleOperationFeedback
        snapshot={state.operation}
        onInspect={onInspect}
        onReadLatest={() => void workflow.refreshPlans().catch(() => {})}
      />
      {failed && (
        <FeedbackPanel
          tone="warning"
          copy={{
            title: t("rules.workspace.actionBlocked"),
            description: t("rules.deployment.planInvalid"),
          }}
        />
      )}
      <p>{t("rules.deployment.cancelHint")}</p>
      <p>
        {plan.versionId} → {plan.restoreVersionId} · {plan.revision}
      </p>
      <TextField
        label={t("rules.deployment.reason")}
        value={reason}
        disabled={state.locked}
        onChange={setReason}
      />
    </DialogFrame>
  );
}
