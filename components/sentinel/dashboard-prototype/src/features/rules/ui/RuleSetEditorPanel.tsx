import { useState } from "react";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import type { createRuleDraftWorkflow } from "../application/ruleDraftWorkflow";
import { useRuleCopy } from "../i18n/useRuleCopy";
import { RULE_ISSUE_MESSAGES } from "../i18n/ruleIssueMessages";
import { newRuleDraft } from "../editor/newRuleDraft";
import { RULE_KIND } from "../model/ruleKinds";
import { RULE_DRAFT_INTENT, type RuleDraftIntent } from "../presentation/ruleDraftIntent";
import { RuleEditor } from "./RuleEditor";
import { RuleDraftToolbar } from "./RuleDraftToolbar";
import { RuleDraftReports } from "./RuleDraftReports";
import { FreezeVersionDialog } from "./FreezeVersionDialog";
import { RuleOperationFeedback } from "./RuleOperationFeedback";
import { Panel } from "../../../shared/ui/Panel";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { DialogFrame } from "../../../shared/ui/DialogFrame";
import { FeedbackPanel } from "../../../shared/ui/FeedbackPanel";
import styles from "./RuleSetWorkspace.module.scss";

interface EditorProps {
  readonly workflow: ReturnType<typeof createRuleDraftWorkflow>;
  readonly newFormKey: () => string;
}
/** Revocation unmounts transient dialog intents; reauthorization never reopens an old destructive intent. */
export function RuleSetEditorPanel(props: EditorProps) {
  const state = useExternalSnapshot(props.workflow),
    { t } = useRuleCopy();
  return state.authorized ? (
    <AuthorizedRuleSetEditor {...props} />
  ) : (
    <FeedbackPanel
      tone="warning"
      copy={{ title: t("rules.workspace.editorTitle"), description: t("rules.workspace.denied") }}
    />
  );
}
/** Compose the selected form, toolbar, reports and controlled confirmation. No source refresh owns local edits. */
function AuthorizedRuleSetEditor({ workflow, newFormKey }: EditorProps) {
  const state = useExternalSnapshot(workflow),
    { t, messages } = useRuleCopy();
  const [intent, setIntent] = useState<RuleDraftIntent | null>(null),
    [freezing, setFreezing] = useState(false),
    [localError, setLocalError] = useState(false);
  async function act(action: () => unknown | Promise<unknown>) {
    setLocalError(false);
    try {
      await action();
      return true;
    } catch {
      setLocalError(true);
      return false;
    }
  }
  const editing = state.editing;
  const selected = editing?.records.find((record) => record.formKey === state.selectedKey) ?? null;
  const canFreeze = !!(
    editing &&
    !state.dirty &&
    state.savedIdentity &&
    state.validation.status === "ready" &&
    state.validation.data.isPublishable
  );
  const inspect = () =>
    void act(async () => {
      const value = await workflow.inspect();
      if (value.status === "completed") {
        setIntent(null);
        setFreezing(false);
      }
    });
  function confirm() {
    void act(() => {
      switch (intent) {
        case RULE_DRAFT_INTENT.Restart:
          workflow.begin(true);
          break;
        case RULE_DRAFT_INTENT.Discard:
          workflow.discard();
          break;
        case RULE_DRAFT_INTENT.Close:
          workflow.close(true);
          break;
        case RULE_DRAFT_INTENT.Remove:
          if (state.selectedKey) workflow.remove(state.selectedKey);
          break;
        case RULE_DRAFT_INTENT.Delete:
          return workflow.deleteDraft();
      }
    }).then((ok) => {
      if (ok) setIntent(null);
    });
  }
  return (
    <Panel
      title={t("rules.workspace.editorTitle")}
      subtitle={t("rules.workspace.editorDescription")}
    >
      <div className={styles.content} data-ruleset-editor>
        <RuleOperationFeedback
          snapshot={state.operation}
          onInspect={inspect}
          onReadLatest={() => void act(workflow.refreshSource)}
        />
        {localError && (
          <FeedbackPanel
            tone="warning"
            copy={{
              title: t("rules.workspace.actionBlocked"),
              description: t("rules.workspace.actionHint"),
            }}
          />
        )}
        {!editing ? (
          <ActionButton
            data-rule-action="begin"
            disabled={state.locked || !("data" in state.source)}
            onClick={() => void act(() => workflow.begin())}
          >
            {t("rules.workspace.begin")}
          </ActionButton>
        ) : (
          <>
            <p role="status" data-rule-dirty>
              {t(state.dirty ? "rules.workspace.unsaved" : "rules.workspace.clean")}
            </p>
            <dl className={styles.facts}>
              <div>
                <dt>{t("rules.baseline")}</dt>
                <dd>{editing.baseline.versionId ?? t("rules.workspace.noVersion")}</dd>
              </div>
              <div>
                <dt>{t("rules.workspace.checksum")}</dt>
                <dd>{editing.baseline.checksum}</dd>
              </div>
              <div>
                <dt>{t("rules.workspace.draftRevision")}</dt>
                <dd>{state.savedIdentity?.revision ?? t("rules.workspace.notPersisted")}</dd>
              </div>
            </dl>
            <RuleDraftToolbar
              workflow={workflow}
              locked={state.locked}
              hasSelection={selected !== null}
              hasSavedDraft={state.savedIdentity !== null}
              canFreeze={canFreeze}
              act={act}
              onIntent={setIntent}
              onFreeze={() => setFreezing(true)}
              onAdd={() =>
                void act(() =>
                  workflow.add(newFormKey(), newRuleDraft(editing.baseline.binding.kind)),
                )
              }
            />
            <div className={styles.editorLayout}>
              <nav aria-label={t("rules.workspace.records")} className={styles.records}>
                {editing.records.map((record, index) => (
                  <ActionButton
                    key={record.formKey}
                    className={styles.record}
                    data-rule-record={record.formKey}
                    variant="secondary"
                    disabled={state.locked}
                    aria-pressed={record.formKey === state.selectedKey}
                    onClick={() => void act(() => workflow.select(record.formKey))}
                  >
                    {record.rule.kind === RULE_KIND.System
                      ? messages.types.system.label
                      : record.rule.draft.resource ||
                        t("rules.workspace.newRecord", { number: index + 1 })}
                  </ActionButton>
                ))}
                {!editing.records.length && <p>{t("rules.workspace.emptyCandidate")}</p>}
              </nav>
              {selected ? (
                <RuleEditor
                  rule={selected.rule}
                  editable={!state.locked}
                  messages={messages}
                  onChange={(rule) => void act(() => workflow.change(selected.formKey, rule))}
                  errorFor={(path) =>
                    state.issues
                      .filter(
                        (item) => item.formKey === selected.formKey && item.issue.path === path,
                      )
                      .map((item) => t(RULE_ISSUE_MESSAGES[item.issue.code]))
                      .join(" ") || undefined
                  }
                />
              ) : (
                <p>{t("rules.workspace.selectRecord")}</p>
              )}
            </div>
            <RuleDraftReports workflow={workflow} act={act} />
          </>
        )}
      </div>
      {intent && (
        <DialogFrame
          isOpen
          onOpenChange={(open) => {
            if (!open) setIntent(null);
          }}
          title={t("rules.workspace.confirmTitle")}
          isBusy={state.locked}
          actions={
            <>
              <ActionButton disabled={state.locked} onClick={() => setIntent(null)}>
                {t("rules.workspace.keepEditing")}
              </ActionButton>
              <ActionButton disabled={state.locked} onClick={confirm}>
                {t("rules.workspace.confirm")}
              </ActionButton>
            </>
          }
        >
          <RuleOperationFeedback
            snapshot={state.operation}
            onInspect={inspect}
            onReadLatest={() => void act(workflow.refreshSource)}
          />
          <p>
            {t(
              intent === RULE_DRAFT_INTENT.Delete
                ? "rules.workspace.deleteDescription"
                : intent === RULE_DRAFT_INTENT.Remove
                  ? "rules.workspace.removeDescription"
                  : "rules.workspace.discardDescription",
            )}
          </p>
        </DialogFrame>
      )}
      {freezing && (
        <FreezeVersionDialog
          workflow={workflow}
          canFreeze={canFreeze}
          onClose={() => setFreezing(false)}
          onInspect={inspect}
          act={act}
        />
      )}
    </Panel>
  );
}
