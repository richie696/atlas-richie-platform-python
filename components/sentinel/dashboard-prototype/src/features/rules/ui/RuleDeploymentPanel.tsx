import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import type {
  createRuleDeploymentWorkflow,
  RulePublicationIntent,
} from "../application/ruleDeploymentWorkflow";
import type { RuleActivationPlan } from "../model/ruleActivation";
import { RULE_MUTATION } from "../model/ruleSetOperations";
import { FeedbackPanel } from "../../../shared/ui/FeedbackPanel";
import { RuleOperationFeedback } from "./RuleOperationFeedback";
import { RuleVersionsPanel } from "./RuleVersionsPanel";
import { RulePublicationPanel } from "./RulePublicationPanel";
import { RulePlansPanel } from "./RulePlansPanel";
import { RulePublishDialog } from "./RulePublishDialog";
import { RulePlanDialog } from "./RulePlanDialog";
import { RuleCancelPlanDialog } from "./RuleCancelPlanDialog";
import { RulePublicationTargetPanel } from "./RulePublicationTargetPanel";
import styles from "./RuleSetWorkspace.module.scss";
import { useBeforeUnloadGuard } from "../../../shared/state/useBeforeUnloadGuard";
interface Props {
  readonly bindingId: string;
  readonly workflow: ReturnType<typeof createRuleDeploymentWorkflow>;
  readonly view: "publications" | "recovery";
  readonly initialPublicationId?: string;
  readonly initialVersionId?: string;
}
/** Compose independent reads and explicit confirmations. Read/write revocation unmounts transient dialog drafts. */
export function RuleDeploymentPanel({
  bindingId,
  workflow,
  view,
  initialPublicationId,
  initialVersionId,
}: Props) {
  const state = useExternalSnapshot(workflow),
    { t } = useTranslation();
  useBeforeUnloadGuard(
    state.operation.inspecting ||
      ["pending", "result-unknown"].includes(state.operation.command.status),
    state.operation.inspecting ||
      ["pending", "result-unknown"].includes(state.operation.command.status),
  );
  useEffect(() => {
    if (state.readable)
      void Promise.resolve()
        .then(workflow.refreshCatalog)
        .catch(() => {});
    return () => workflow.cancel();
  }, [workflow, state.readable]);
  useEffect(() => {
    if (state.readable && initialPublicationId && state.publicationId !== initialPublicationId)
      void workflow.selectPublication(initialPublicationId).catch(() => {});
  }, [initialPublicationId, state.publicationId, state.readable, workflow]);
  useEffect(() => {
    if (state.readable && initialVersionId && state.versionId !== initialVersionId)
      void workflow.selectVersion(initialVersionId).catch(() => {});
  }, [initialVersionId, state.readable, state.versionId, workflow]);
  return state.readable ? (
    <DeploymentSurface
      key={state.writable ? "write" : "read"}
      bindingId={bindingId}
      workflow={workflow}
      view={view}
    />
  ) : (
    <FeedbackPanel
      tone="warning"
      copy={{
        title: t("rules.deployment.versionsTitle"),
        description: t("rules.workspace.denied"),
      }}
    />
  );
}
/** Dialog intentions retain their workflow identity, so replacing the injected owner cannot inherit a confirmation. */
function DeploymentSurface({ bindingId, workflow, view }: Props) {
  const state = useExternalSnapshot(workflow),
    { t } = useTranslation();
  const [publication, setPublication] = useState<{
      readonly owner: typeof workflow;
      readonly intent: RulePublicationIntent;
    } | null>(null),
    [planOwner, setPlanOwner] = useState<typeof workflow | null>(null),
    [cancel, setCancel] = useState<{
      readonly owner: typeof workflow;
      readonly plan: RuleActivationPlan;
    } | null>(null),
    [failed, setFailed] = useState(false);
  async function act(effect: () => unknown | Promise<unknown>) {
    setFailed(false);
    try {
      await effect();
      return true;
    } catch {
      setFailed(true);
      return false;
    }
  }
  const close = () => {
    setPublication(null);
    setPlanOwner(null);
    setCancel(null);
  };
  const inspect = () =>
    void act(async () => {
      const value = await workflow.inspect();
      if (value.status === "completed") close();
    });
  const refreshPublication = () =>
    void act(async () => {
      await workflow.refreshCatalog();
      if (workflow.getSnapshot().publicationId) await workflow.refreshPublication();
    });
  const operationKind = state.operation.operation?.kind;
  const showOperation =
    (view === "publications" && operationKind === RULE_MUTATION.Publish) ||
    (view === "recovery" &&
      (operationKind === RULE_MUTATION.CreatePlan || operationKind === RULE_MUTATION.CancelPlan));
  const freshSource = state.source.status === "ready" || state.source.status === "empty";
  const freshVersions = state.versions.status === "ready";
  const freshPlans = state.plans.status === "ready" || state.plans.status === "empty";
  return (
    <section className={styles.workspace} data-rule-deployment>
      {showOperation && (
        <RuleOperationFeedback
          snapshot={state.operation}
          onInspect={inspect}
          onReadLatest={() => void act(workflow.refreshCatalog)}
        />
      )}
      {view === "publications" && <RulePublicationTargetPanel workflow={workflow} />}
      {failed && (
        <FeedbackPanel
          tone="warning"
          copy={{
            title: t("rules.workspace.actionBlocked"),
            description: t("rules.deployment.actionHint"),
          }}
        />
      )}
      {view === "publications" ? (
        <>
          <RuleVersionsPanel
            versions={state.versions}
            version={state.version}
            selectedId={state.versionId}
            canPublish={
              state.writable && !state.locked && freshSource && state.version.status === "ready"
            }
            onSelect={(id) => void act(() => workflow.selectVersion(id))}
            onRead={() => void act(workflow.refreshVersions)}
            onPublish={() =>
              void act(() =>
                setPublication({ owner: workflow, intent: workflow.preparePublication() }),
              )
            }
          />
          <RulePublicationPanel
            publications={state.publications}
            publication={state.publication}
            receipts={state.receipts}
            selectedId={state.publicationId}
            onSelect={(id) => void act(() => workflow.selectPublication(id))}
            onRead={refreshPublication}
            onReadReceipts={(page) => void act(() => workflow.loadReceipts(page))}
          />
        </>
      ) : (
        <RulePlansPanel
          plans={state.plans}
          canCreate={state.writable && !state.locked && freshVersions && freshPlans}
          canCancel={state.writable && !state.locked && freshPlans}
          onRead={() => void act(workflow.refreshPlans)}
          onCreate={() => setPlanOwner(workflow)}
          onCancel={(plan) => setCancel({ owner: workflow, plan })}
        />
      )}
      {state.writable && publication?.owner === workflow && (
        <RulePublishDialog
          workflow={workflow}
          intent={publication.intent}
          onClose={close}
          onInspect={inspect}
        />
      )}
      {state.writable && planOwner === workflow && (
        <RulePlanDialog
          bindingId={bindingId}
          workflow={workflow}
          onClose={close}
          onInspect={inspect}
        />
      )}
      {state.writable && cancel?.owner === workflow && (
        <RuleCancelPlanDialog
          workflow={workflow}
          plan={cancel.plan}
          onClose={close}
          onInspect={inspect}
        />
      )}
    </section>
  );
}
