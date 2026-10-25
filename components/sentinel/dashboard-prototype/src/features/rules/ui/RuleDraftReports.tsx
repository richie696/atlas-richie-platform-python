import { useTranslation } from "react-i18next";
import type { createRuleDraftWorkflow } from "../application/ruleDraftWorkflow";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import { prepareRuleSetCandidate } from "../editor/ruleSetEditing";
import { RULE_ISSUE_MESSAGES } from "../i18n/ruleIssueMessages";
import { RuleQueryView } from "./RuleQueryView";
import styles from "./RuleSetWorkspace.module.scss";
/** Full-array preview and independently obtained server reports. They confer no publication authority. */
export function RuleDraftReports({
  workflow,
  act,
}: {
  readonly workflow: ReturnType<typeof createRuleDraftWorkflow>;
  readonly act: (action: () => unknown | Promise<unknown>) => Promise<boolean>;
}) {
  const { t } = useTranslation(),
    state = useExternalSnapshot(workflow);
  if (!state.editing) return null;
  const prepared = prepareRuleSetCandidate(state.editing);
  return (
    <>
      {state.issues.length > 0 && (
        <ul role="alert">
          {state.issues.map((item, index) => (
            <li key={index}>{t(RULE_ISSUE_MESSAGES[item.issue.code])}</li>
          ))}
        </ul>
      )}
      <section>
        <h3>{t("rules.configPreview")}</h3>
        {prepared.valid ? (
          <pre className={styles.preview} data-rule-full-preview>
            {JSON.stringify(
              prepared.candidate.rules.map((record) => record.rule.value),
              null,
              2,
            )}
          </pre>
        ) : (
          <p>{t("rules.workspace.invalidPreview")}</p>
        )}
      </section>
      <RuleQueryView snapshot={state.validation} onRetry={() => void act(workflow.validate)}>
        {(report) => (
          <section data-rule-validation>
            <h3>
              {t(
                report.isPublishable
                  ? "rules.workspace.validationPassed"
                  : "rules.workspace.validationBlocked",
              )}
            </h3>
            <p>
              {report.profile} · {report.candidateChecksum}
            </p>
            {report.issues.map((issue, index) => (
              <p key={index}>
                {t("rules.workspace.validationIssue", {
                  number: issue.recordIndex === null ? "—" : issue.recordIndex + 1,
                })}
              </p>
            ))}
          </section>
        )}
      </RuleQueryView>
      <RuleQueryView snapshot={state.diff} onRetry={() => void act(workflow.compare)}>
        {(diff) => (
          <section data-rule-diff>
            <h3>{t("rules.workspace.diffTitle", { count: diff.changes.length })}</h3>
            <pre className={styles.preview}>{JSON.stringify(diff.changes, null, 2)}</pre>
          </section>
        )}
      </RuleQueryView>
    </>
  );
}
