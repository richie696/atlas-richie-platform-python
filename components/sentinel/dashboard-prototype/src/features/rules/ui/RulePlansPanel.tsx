import { useTranslation } from "react-i18next";
import type { QuerySnapshot } from "../../../shared/state/queryResource";
import type { RuleSetCollection } from "../model/ruleSet";
import { canCancelRulePlan, type RuleActivationPlan } from "../model/ruleActivation";
import { ACTIVATION_STATE_LABEL } from "../presentation/deploymentLabels";
import { Panel } from "../../../shared/ui/Panel";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { DataTable } from "../../../shared/ui/DataTable";
import { RuleQueryView } from "./RuleQueryView";
import styles from "./RuleSetWorkspace.module.scss";
import { formatUtcDateTime } from "../../../shared/presentation/utcDateTime";
/** Server-owned execution/restore facts. Cancel stops a pending/blocked plan, not an implicit rollback of an active version. */
export function RulePlansPanel({
  plans,
  canCreate,
  canCancel,
  onRead,
  onCreate,
  onCancel,
}: {
  readonly plans: QuerySnapshot<RuleSetCollection<RuleActivationPlan>>;
  readonly canCreate: boolean;
  readonly canCancel: boolean;
  readonly onRead: () => void;
  readonly onCreate: () => void;
  readonly onCancel: (plan: RuleActivationPlan) => void;
}) {
  const { t, i18n } = useTranslation();
  return (
    <Panel
      title={t("rules.deployment.plansTitle")}
      subtitle={t("rules.deployment.schedulerHint")}
      action={<ActionButton onClick={onRead}>{t("rules.deployment.refreshPlans")}</ActionButton>}
    >
      <div className={styles.content}>
        <ActionButton data-deployment-create-plan disabled={!canCreate} onClick={onCreate}>
          {t("rules.deployment.createPlan")}
        </ActionButton>
        <RuleQueryView snapshot={plans} onRetry={onRead}>
          {(collection) => (
            <DataTable
              heads={[
                t("rules.deployment.planId"),
                t("rules.deployment.targetAndRestore"),
                t("rules.deployment.interval"),
                t("rules.deployment.planStatus"),
                t("rules.deployment.action"),
              ]}
              rows={collection.items.map((plan) => (
                <tr key={plan.id}>
                  <td>{plan.id}</td>
                  <td>
                    {plan.versionId} → {plan.restoreVersionId}
                  </td>
                  <td>
                    <time dateTime={new Date(plan.activateAtMs).toISOString()}>
                      {formatUtcDateTime(plan.activateAtMs, i18n.resolvedLanguage ?? i18n.language)}
                    </time>
                    <br />
                    <time dateTime={new Date(plan.deactivateAtMs).toISOString()}>
                      {formatUtcDateTime(
                        plan.deactivateAtMs,
                        i18n.resolvedLanguage ?? i18n.language,
                      )}
                    </time>
                    <br />
                    {plan.timeZone}
                  </td>
                  <td>{t(ACTIVATION_STATE_LABEL[plan.state])}</td>
                  <td>
                    <ActionButton
                      data-deployment-cancel-plan={plan.id}
                      disabled={!canCancel || !canCancelRulePlan(plan)}
                      onClick={() => onCancel(plan)}
                    >
                      {t("rules.deployment.cancelPlan")}
                    </ActionButton>
                  </td>
                </tr>
              ))}
            />
          )}
        </RuleQueryView>
      </div>
    </Panel>
  );
}
