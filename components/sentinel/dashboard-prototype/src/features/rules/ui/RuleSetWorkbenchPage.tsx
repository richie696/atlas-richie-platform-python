import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import type { createRuleDraftWorkflow } from "../application/ruleDraftWorkflow";
import type { RuleBinding } from "../model/ruleSet";
import { Panel } from "../../../shared/ui/Panel";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { RuleQueryView } from "./RuleQueryView";
import { RuleSetEditorPanel } from "./RuleSetEditorPanel";
import styles from "./RuleSetWorkspace.module.scss";
import { useBeforeUnloadGuard } from "../../../shared/state/useBeforeUnloadGuard";
import { formatUtcDateTime } from "../../../shared/presentation/utcDateTime";
/** Binding is explicitly selected by app/directory. No first-rule or another-application fallback. */
export function RuleSetWorkbenchPage({
  workflow,
  binding,
  newFormKey,
}: {
  readonly workflow: ReturnType<typeof createRuleDraftWorkflow>;
  readonly binding: RuleBinding;
  readonly newFormKey: () => string;
}) {
  const { t, i18n } = useTranslation(),
    state = useExternalSnapshot(workflow);
  useBeforeUnloadGuard(
    state.dirty ||
      state.operation.inspecting ||
      ["pending", "result-unknown"].includes(state.operation.command.status),
    state.operation.inspecting ||
      ["pending", "result-unknown"].includes(state.operation.command.status),
    () => workflow.close(true),
  );
  useEffect(() => {
    void Promise.resolve()
      .then(workflow.refreshSource)
      .catch(() => {});
    return () => workflow.cancel();
  }, [workflow]);
  return (
    <section className={styles.workspace} data-rule-workspace>
      <Panel
        title={t("rules.workspace.sourceTitle")}
        subtitle={binding.location}
        action={
          <ActionButton
            disabled={["loading", "refreshing"].includes(state.source.status)}
            onClick={() =>
              void Promise.resolve()
                .then(workflow.refreshSource)
                .catch(() => {})
            }
          >
            {t("rules.workspace.refresh")}
          </ActionButton>
        }
      >
        <div className={styles.content}>
          <dl className={styles.facts}>
            <div>
              <dt>{t("rules.provider")}</dt>
              <dd>{binding.sourceLabel}</dd>
            </div>
            <div>
              <dt>{t("rules.workspace.binding")}</dt>
              <dd>{binding.id}</dd>
            </div>
            <div>
              <dt>{t("rules.workspace.profile")}</dt>
              <dd>{binding.profile}</dd>
            </div>
          </dl>
          <RuleQueryView
            snapshot={state.source}
            onRetry={() =>
              void Promise.resolve()
                .then(workflow.refreshSource)
                .catch(() => {})
            }
          >
            {(source) => (
              <p data-rule-source-summary>
                {t("rules.workspace.sourceRead", { count: source.records.length })} ·{" "}
                {source.versionId ?? t("rules.workspace.noVersion")} ·{" "}
                <time dateTime={new Date(source.asOfMs).toISOString()}>
                  {formatUtcDateTime(source.asOfMs, i18n.resolvedLanguage ?? i18n.language)}
                </time>
              </p>
            )}
          </RuleQueryView>
          {state.source.status === "empty" && <p>{t("rules.workspace.emptySource")}</p>}
        </div>
      </Panel>
      <RuleSetEditorPanel workflow={workflow} newFormKey={newFormKey} />
    </section>
  );
}
