import type {
  PublicationPhase,
  PublicationStageState,
  ReceiptState,
  RulePublication,
} from "../model/ruleDeployment";
import type { RuleActivationPlan } from "../model/ruleActivation";
import type { TranslationKey } from "../../../shared/types/translation";
/** Closed backend facts map to translation keys; protocol enum values never become field labels. */
export const PUBLICATION_STAGE_LABEL: Readonly<Record<PublicationStageState, TranslationKey>> =
  Object.freeze({
    awaiting: "rules.deployment.stage.awaiting",
    running: "rules.deployment.stage.running",
    succeeded: "rules.deployment.stage.succeeded",
    failed: "rules.deployment.stage.failed",
    unknown: "rules.deployment.stage.unknown",
  });
export const RECEIPT_STATE_LABEL: Readonly<Record<ReceiptState, TranslationKey>> = Object.freeze({
  applied: "rules.deployment.receipt.applied",
  pending: "rules.deployment.receipt.pending",
  failed: "rules.deployment.receipt.failed",
  unknown: "rules.deployment.receipt.unknown",
  restart_required: "rules.deployment.receipt.restartRequired",
});
export const ACTIVATION_STATE_LABEL: Readonly<Record<RuleActivationPlan["state"], TranslationKey>> =
  Object.freeze({
    pending: "rules.deployment.plan.pending",
    activating: "rules.deployment.plan.activating",
    active: "rules.deployment.plan.active",
    restoring: "rules.deployment.plan.restoring",
    completed: "rules.deployment.plan.completed",
    blocked: "rules.deployment.plan.blocked",
    cancelled: "rules.deployment.plan.cancelled",
  });

/** Project publication phases to stable translated field labels without translating protocol values. */
export function publicationStages(item: RulePublication): readonly {
  readonly labelKey: TranslationKey;
  readonly phase: PublicationPhase;
}[] {
  return [
    { labelKey: "rules.deployment.validation", phase: item.validation },
    { labelKey: "rules.deployment.configurationWrite", phase: item.configurationWrite },
    { labelKey: "rules.deployment.readBack", phase: item.readBack },
  ];
}
