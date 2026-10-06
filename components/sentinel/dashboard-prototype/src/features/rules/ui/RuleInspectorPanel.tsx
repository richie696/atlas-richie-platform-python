/**
 * 规则检视器：展示选中规则的元信息、兼容 JSON 预览与校验反馈。
 *
 * 中文
 * ----
 * 四态发布进度（已验证 / 配置中心写入成功 / 回读一致 / 实例已生效）**不在这里合并**。
 * 本面板只呈现「本地草稿已校验」这一种状态，且校验结论来自 `useRuleWorkbench` 的
 * 结构化结果，不是页面临时拼接的字符串。
 */
import { FloppyDiskIcon as FloppyDisk } from "@phosphor-icons/react";

import { ActionButton } from "../../../shared/ui/ActionButton";
import { Panel } from "../../../shared/ui/Panel";
import { RULE_TYPE_META, type RuleKind } from "../model/ruleKinds";
import type { RuleDraft } from "../model/ruleDraft";
import type { RuleWorkbenchMessages } from "../model/ruleMessages";
import type { RuleValidationState, RuleWorkbenchEntry } from "../state/useRuleWorkbench";
import { RuleEditor } from "./RuleEditor";

export interface RuleInspectorPanelProps {
  readonly entry: RuleWorkbenchEntry | null;
  readonly draft: RuleDraft;
  readonly editing: boolean;
  readonly validation: RuleValidationState;
  readonly messages: RuleWorkbenchMessages;
  readonly scopes: Readonly<Record<string, string>>;
  readonly t: (path: string, values?: Record<string, string | number>) => string;
  readonly onDraftChange: (draft: RuleDraft) => void;
  readonly onBeginEditing: () => void;
  readonly onValidate: () => void;
}

/** 把结构化校验结果转成面板展示的一行反馈。 */
function feedbackText(
  validation: RuleValidationState,
  t: (path: string, values?: Record<string, string | number>) => string,
): { readonly text: string; readonly tone: "passed" | "failed" } | null {
  if (validation.status === "passed") return { text: t("rules.validationPassed"), tone: "passed" };
  if (validation.status === "failed") {
    return {
      text: validation.issues
        .map((issue) => t(issue.key, issue.params as Record<string, string | number> | undefined))
        .join(" "),
      tone: "failed",
    };
  }
  return null;
}

export function RuleInspectorPanel({
  entry,
  draft,
  editing,
  validation,
  messages,
  scopes,
  t,
  onDraftChange,
  onBeginEditing,
  onValidate,
}: RuleInspectorPanelProps) {
  const feedback = feedbackText(validation, t);
  const typeCopy = entry ? messages.types[entry.ruleType as RuleKind] : null;

  if (!entry || !typeCopy) {
    // 空态说明「当前筛选下没有规则」，不是「搜索框里没有输入」。
    // 旧实现复用了 `t("rules.search")`（搜索框 placeholder）再拼一个「：0」，
    // 渲染出来是「搜索资源或策略：0」，语义完全对不上。
    return (
      <Panel title={t("rules.details")} subtitle={t("rules.detailDescription")}>
        <div className="empty">{t("rules.noMatchingRule")}</div>
      </Panel>
    );
  }

  return (
    <Panel
      title={editing ? t("rules.draft") : t("rules.details")}
      subtitle={editing ? t("rules.draftDescription") : t("rules.detailDescription")}
      className="rule-inspector"
    >
      <div className="key-value">
        <span>{t("rules.resource")}</span>
        <b>{entry.resource}</b>
      </div>
      <div className="key-value">
        <span>{t("rules.provider")}</span>
        <b>{entry.provider}</b>
      </div>
      <div className="key-value">
        <span>{t("rules.baseline")}</span>
        <b>{entry.version}</b>
      </div>
      <div className="key-value">
        <span>{t("rules.scope")}</span>
        <b>{t("rules.scopeExample", { scope: scopes[entry.scope] })}</b>
      </div>
      <div className="key-value">
        <span>{t("rules.compatibilityType")}</span>
        <b>{RULE_TYPE_META[entry.ruleType].className}</b>
      </div>
      <div className="divider" />
      <div className="rule-format-header">
        <div className="rule-format-copy">
          <b>{t("rules.configuration", { type: typeCopy.label })}</b>
          <span>{typeCopy.description}</span>
        </div>
        {!editing && (
          <ActionButton
            type="button"
            className="rule-edit-button"
            variant="secondary"
            size="sm"
            onClick={onBeginEditing}
          >
            {t("rules.editDraft")}
          </ActionButton>
        )}
      </div>
      <RuleEditor
        kind={entry.ruleType}
        draft={draft}
        editable={editing}
        messages={messages}
        onChange={onDraftChange}
      />
      <div className="compatibility-json">
        <div>
          <b>{t("rules.configPreview")}</b>
          <span>{t("rules.jsonArray", { name: RULE_TYPE_META[entry.ruleType].configName })}</span>
        </div>
        <pre>{JSON.stringify([draft], null, 2)}</pre>
      </div>
      {feedback && (
        <div className={`inline-note ${feedback.tone === "passed" ? "" : "invalid"}`}>
          {feedback.text}
        </div>
      )}
      <ActionButton type="button" className="primary-button full" onClick={onValidate}>
        <FloppyDisk size={16} /> {t("rules.validate")}
      </ActionButton>
      <p className="nonproduction">{t("rules.notProduction")}</p>
    </Panel>
  );
}
