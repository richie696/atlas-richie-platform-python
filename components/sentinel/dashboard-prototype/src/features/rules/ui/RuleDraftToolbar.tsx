import { useTranslation } from "react-i18next";
import type { TranslationKey } from "../../../shared/types/translation";
import { ActionButton } from "../../../shared/ui/ActionButton";
import type { createRuleDraftWorkflow } from "../application/ruleDraftWorkflow";
import { RULE_DRAFT_INTENT, type RuleDraftIntent } from "../presentation/ruleDraftIntent";
import styles from "./RuleSetWorkspace.module.scss";
/** Project explicit actions into vendor controls; confirmation and command effects remain with their owners. */
export function RuleDraftToolbar({
  workflow,
  locked,
  hasSelection,
  hasSavedDraft,
  canFreeze,
  onAdd,
  onFreeze,
  onIntent,
  act,
}: {
  readonly workflow: ReturnType<typeof createRuleDraftWorkflow>;
  readonly locked: boolean;
  readonly hasSelection: boolean;
  readonly hasSavedDraft: boolean;
  readonly canFreeze: boolean;
  readonly onAdd: () => void;
  readonly onFreeze: () => void;
  readonly onIntent: (intent: RuleDraftIntent) => void;
  readonly act: (action: () => unknown | Promise<unknown>) => Promise<boolean>;
}) {
  const { t } = useTranslation();
  const actions: readonly {
    readonly id: string;
    readonly labelKey: TranslationKey;
    readonly onClick: () => void;
    readonly disabled: boolean;
  }[] = [
    { id: "add", labelKey: "rules.workspace.add", onClick: onAdd, disabled: locked },
    {
      id: "remove",
      labelKey: "rules.workspace.remove",
      onClick: () => onIntent(RULE_DRAFT_INTENT.Remove),
      disabled: locked || !hasSelection,
    },
    {
      id: "save",
      labelKey: "rules.workspace.save",
      onClick: () => void act(workflow.save),
      disabled: locked,
    },
    {
      id: "discard",
      labelKey: "rules.workspace.discard",
      onClick: () => onIntent(RULE_DRAFT_INTENT.Discard),
      disabled: locked,
    },
    {
      id: "validate",
      labelKey: "rules.workspace.validate",
      onClick: () => void act(workflow.validate),
      disabled: locked,
    },
    {
      id: "diff",
      labelKey: "rules.workspace.diff",
      onClick: () => void act(workflow.compare),
      disabled: locked,
    },
    {
      id: "freeze",
      labelKey: "rules.workspace.freeze",
      onClick: onFreeze,
      disabled: locked || !canFreeze,
    },
    {
      id: "restart",
      labelKey: "rules.workspace.readBaseline",
      onClick: () => onIntent(RULE_DRAFT_INTENT.Restart),
      disabled: locked,
    },
    {
      id: "delete",
      labelKey: "rules.workspace.deleteDraft",
      onClick: () => onIntent(RULE_DRAFT_INTENT.Delete),
      disabled: locked || !hasSavedDraft,
    },
    {
      id: "close",
      labelKey: "rules.workspace.close",
      onClick: () => onIntent(RULE_DRAFT_INTENT.Close),
      disabled: locked,
    },
  ];
  return (
    <div className={styles.actions}>
      {actions.map((action) => (
        <ActionButton
          key={action.id}
          data-rule-action={action.id}
          disabled={action.disabled}
          onClick={action.onClick}
        >
          {t(action.labelKey)}
        </ActionButton>
      ))}
    </div>
  );
}
