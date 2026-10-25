import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import type { createRuleDeploymentWorkflow } from "../application/ruleDeploymentWorkflow";
import {
  INITIAL_RULE_SCHEDULE_DRAFT,
  hasRuleScheduleChanges,
  prepareRuleSchedule,
  type RuleScheduleDraft,
} from "../model/ruleScheduleDraft";
import { DialogFrame } from "../../../shared/ui/DialogFrame";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { FeedbackPanel } from "../../../shared/ui/FeedbackPanel";
import { RulePlanFields } from "./RulePlanFields";
import { RuleOperationFeedback } from "./RuleOperationFeedback";
import { useBeforeUnloadGuard } from "../../../shared/state/useBeforeUnloadGuard";
import { formatUtcDateTime } from "../../../shared/presentation/utcDateTime";
/** Only the draft is local. The workflow validates current versions/overlaps and sends one durable plan command. */
export function RulePlanDialog({
  bindingId,
  workflow,
  onClose,
  onInspect,
}: {
  readonly bindingId: string;
  readonly workflow: ReturnType<typeof createRuleDeploymentWorkflow>;
  readonly onClose: () => void;
  readonly onInspect: () => void;
}) {
  const { t, i18n } = useTranslation(),
    state = useExternalSnapshot(workflow);
  const [draft, setDraft] = useState<RuleScheduleDraft>(INITIAL_RULE_SCHEDULE_DRAFT),
    [failed, setFailed] = useState(false);
  useBeforeUnloadGuard(hasRuleScheduleChanges(draft) || state.locked, state.locked, () => {
    setDraft(INITIAL_RULE_SCHEDULE_DRAFT);
    onClose();
  });
  const prepared = prepareRuleSchedule(bindingId, draft);
  async function submit() {
    if (!prepared.valid) {
      setFailed(true);
      return;
    }
    setFailed(false);
    try {
      await workflow.createPlan(prepared.schedule);
      onClose();
    } catch {
      setFailed(true);
    }
  }
  return (
    <DialogFrame
      isOpen
      title={t("rules.deployment.createPlan")}
      subtitle={t("rules.deployment.schedulerHint")}
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
            data-deployment-submit-plan
            disabled={state.locked || !state.writable}
            onClick={() => void submit()}
          >
            {t("rules.deployment.savePlan")}
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
        <div data-plan-validation-feedback>
          <FeedbackPanel
            tone="warning"
            copy={{
              title: t("rules.workspace.actionBlocked"),
              description: t("rules.deployment.planInvalid"),
            }}
          />
        </div>
      )}
      <RulePlanFields
        draft={draft}
        versions={"data" in state.versions ? state.versions.data.items : []}
        disabled={state.locked}
        onChange={(nextDraft) => {
          setDraft(nextDraft);
          setFailed(false);
        }}
      />
      {prepared.valid ? (
        <p data-schedule-utc>
          {formatUtcDateTime(
            prepared.schedule.activateAtMs,
            i18n.resolvedLanguage ?? i18n.language,
          )}{" "}
          →{" "}
          {formatUtcDateTime(
            prepared.schedule.deactivateAtMs,
            i18n.resolvedLanguage ?? i18n.language,
          )}
        </p>
      ) : (
        <p>{t("rules.deployment.planInvalid")}</p>
      )}
    </DialogFrame>
  );
}
