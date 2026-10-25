/**
 * 首次初始化向导的状态机。
 *
 * 中文
 * ----
 * 旧实现在 `SystemInitializationPage` 里摊开了 8 个 `useState`（步骤下标、数据库种类、
 * 端口、连接信息、来源种类、来源连接、认证方式、凭证、管理员表单、提示），合法迁移
 * 只存在于 `next()` 这一个事件处理函数里，而「这一步允许提交什么」又是第三段内联
 * `if`。三处事实互相复制，任何一步新增校验都要同时改三处。
 *
 * 这里收成单一所有者：
 *
 * - **草稿**是一份 `SetupDraft` 快照，字段按领域分块，页面只发命令不改结构；
 * - **步骤迁移**只有 `goNext()` / `goBack()` 两个命令，前进前先跑当前步校验；
 * - 校验只持有“哪些步骤已被用户尝试”的状态；当前错误始终由纯校验函数从最新草稿派生，
 *   不保存第二份可过期的错误副本。修正某个字段后，只清除已不成立的字段错误。
 * - 页面说明（例如「测试连接」）通过单独的 `notice` 槽位呈现；输入变化清除说明，但不
 *   擦掉其它仍然有效的字段错误。
 * - `goBack()` 不清除已尝试步骤的验证状态，用户返回时仍能看到尚未修正的问题。
 */
import { useCallback, useState } from "react";

import {
  isControlPlaneDatabaseKind,
  isRuleSourceAuthenticationMode,
  isRuleSourceKind,
  validateSetupStep,
  clearSetupSecrets,
  INITIAL_SETUP_DRAFT,
  SETUP_STEPS,
  SETUP_CONNECTION_CHECK,
  setupStepForField,
  type RuleSourceCredentials,
  type SetupAdminDraft,
  type SetupDatabaseDraft,
  type SetupDraft,
  type SetupIssue,
  type SetupRuleSourceDraft,
  type SetupStepId,
  type SetupConnectionCheckTarget,
} from "../model/setup";
import {
  changeSetupDatabase,
  changeSetupSource,
  changeSetupAuthentication,
  prepareSetupSubmission,
  type SetupSubmission,
} from "../model/setupSubmission";

/**
 * 页面级提示内容。字段问题由 {@link SetupFlow.fieldIssues} 根据当前草稿实时派生。
 */
export type SetupNotice = { readonly kind: "info"; readonly text: string };

export interface SetupFlow {
  /** 有序步骤全集。步骤导航由本 Hook 拥有，页面只按它渲染步骤条。 */
  readonly steps: readonly SetupStepId[];
  readonly stepIndex: number;
  readonly step: SetupStepId;
  readonly isFirstStep: boolean;
  readonly isLastStep: boolean;
  readonly draft: SetupDraft;
  /** Current-step issues are derived from the draft after that step has been validated. */
  readonly fieldIssues: readonly SetupIssue[];
  readonly notice: SetupNotice | null;

  /** 选择数据库种类，并同步该种类的默认端口。 */
  selectDatabase: (value: string) => void;
  setDatabasePort: (value: string) => void;
  patchDatabase: (patch: Partial<SetupDatabaseDraft>) => void;
  selectRuleSource: (value: string) => void;
  patchRuleSource: (patch: Partial<SetupRuleSourceDraft>) => void;
  selectAuthenticationMode: (value: string) => void;
  patchSourceCredentials: (patch: Partial<RuleSourceCredentials>) => void;
  patchAdmin: (patch: Partial<SetupAdminDraft>) => void;
  /** 校验当前步并前进；失败后在该步骤显示从草稿派生的字段错误。 */
  goNext: () => void;
  /** 回退一步；保留已尝试步骤的字段校验状态。 */
  goBack: () => void;
  /** 页面写入一条说明性提示（例如连接检查结果）。 */
  reportInfo: (text: string) => void;
  /** Report every local validation failure so the UI can annotate all affected fields. */
  reportIssues: (issues: readonly SetupIssue[]) => void;
  /** Check the entire form and produce the selected write-only branches. Never clears a failed form. */
  prepareSubmission: () => SetupSubmission | null;
  /** Best-effort removal from mounted form state after confirmed completion; no browser storage is used. */
  clearSensitive: () => void;
}

/** Connection edits invalidate only the corresponding optional check authority. */
export function useSetupFlow(
  onConnectionChange?: (target?: SetupConnectionCheckTarget) => void,
): SetupFlow {
  const [stepIndex, setStepIndex] = useState(0);
  const [draft, setDraft] = useState<SetupDraft>(INITIAL_SETUP_DRAFT);
  const [notice, setNotice] = useState<SetupNotice | null>(null);
  const [validatedSteps, setValidatedSteps] = useState<readonly SetupStepId[]>([]);

  const clearNotice = useCallback(() => setNotice(null), []);

  const step = SETUP_STEPS[stepIndex];
  const isLastStep = stepIndex === SETUP_STEPS.length - 1;
  const fieldIssues = validatedSteps.includes(step) ? validateSetupStep(step, draft) : [];

  const markValidated = useCallback((steps: readonly SetupStepId[]) => {
    setValidatedSteps((current) => {
      const next = new Set(current);
      steps.forEach((value) => next.add(value));
      return [...next];
    });
  }, []);

  // 三个单选控件的值域都是 string。协议值由类型守卫**收窄**成联合类型：不是受支持
  // 的值就保持当前状态，而不是像旧实现那样用 `as` 断言把任意字符串写进草稿。
  const selectDatabase = useCallback(
    (value: string) => {
      if (!isControlPlaneDatabaseKind(value)) return;
      onConnectionChange?.(SETUP_CONNECTION_CHECK.Database);
      clearNotice();
      setDraft((current) => changeSetupDatabase(current, value));
    },
    [clearNotice, onConnectionChange],
  );

  const selectRuleSource = useCallback(
    (value: string) => {
      if (!isRuleSourceKind(value)) return;
      onConnectionChange?.(SETUP_CONNECTION_CHECK.Source);
      clearNotice();
      setDraft((current) => changeSetupSource(current, value));
    },
    [clearNotice, onConnectionChange],
  );

  const selectAuthenticationMode = useCallback(
    (value: string) => {
      if (!isRuleSourceAuthenticationMode(value)) return;
      onConnectionChange?.(SETUP_CONNECTION_CHECK.Source);
      clearNotice();
      setDraft((current) => changeSetupAuthentication(current, value));
    },
    [clearNotice, onConnectionChange],
  );

  const setDatabasePort = useCallback(
    (value: string) => {
      onConnectionChange?.(SETUP_CONNECTION_CHECK.Database);
      clearNotice();
      setDraft((current) => ({ ...current, databasePort: value }));
    },
    [clearNotice, onConnectionChange],
  );

  const patchDatabase = useCallback(
    (patch: Partial<SetupDatabaseDraft>) => {
      onConnectionChange?.(SETUP_CONNECTION_CHECK.Database);
      clearNotice();
      setDraft((current) => ({ ...current, database: { ...current.database, ...patch } }));
    },
    [clearNotice, onConnectionChange],
  );

  const patchRuleSource = useCallback(
    (patch: Partial<SetupRuleSourceDraft>) => {
      onConnectionChange?.(SETUP_CONNECTION_CHECK.Source);
      clearNotice();
      setDraft((current) => ({ ...current, source: { ...current.source, ...patch } }));
    },
    [clearNotice, onConnectionChange],
  );

  const patchSourceCredentials = useCallback(
    (patch: Partial<RuleSourceCredentials>) => {
      onConnectionChange?.(SETUP_CONNECTION_CHECK.Source);
      clearNotice();
      setDraft((current) => ({
        ...current,
        sourceCredentials: { ...current.sourceCredentials, ...patch },
      }));
    },
    [clearNotice, onConnectionChange],
  );

  const patchAdmin = useCallback(
    (patch: Partial<SetupAdminDraft>) => {
      clearNotice();
      setDraft((current) => ({ ...current, admin: { ...current.admin, ...patch } }));
    },
    [clearNotice],
  );

  const goNext = useCallback(() => {
    const issues = validateSetupStep(step, draft);
    if (issues.length > 0) {
      markValidated([step]);
      return;
    }
    setNotice(null);
    setStepIndex((current) => Math.min(current + 1, SETUP_STEPS.length - 1));
  }, [draft, markValidated, step]);

  const goBack = useCallback(() => {
    setStepIndex((current) => Math.max(0, current - 1));
  }, []);

  const reportInfo = useCallback((text: string) => {
    setNotice({ kind: "info", text });
  }, []);
  const reportIssues = useCallback(
    (issues: readonly SetupIssue[]) => {
      if (issues.length === 0) return;
      const target = issues[0].field ? setupStepForField(issues[0].field) : step;
      markValidated([target]);
      setStepIndex(SETUP_STEPS.indexOf(target));
      setNotice(null);
    },
    [markValidated, step],
  );

  const prepareSubmission = useCallback(() => {
    const result = prepareSetupSubmission(draft);
    if (result.status === "invalid") {
      const firstOwnedIssue = result.issues.find((issue) => issue.field !== undefined);
      if (firstOwnedIssue?.field) {
        const targetStep = setupStepForField(firstOwnedIssue.field);
        markValidated([targetStep]);
        setStepIndex(SETUP_STEPS.indexOf(targetStep));
      } else {
        markValidated([step]);
      }
      setNotice(null);
      return null;
    }
    setNotice(null);
    setValidatedSteps([]);
    return result.submission;
  }, [draft, markValidated, step]);
  const clearSensitive = useCallback(() => {
    onConnectionChange?.();
    setDraft((current) => clearSetupSecrets(current));
    setNotice(null);
    setValidatedSteps([]);
  }, [onConnectionChange]);

  return {
    steps: SETUP_STEPS,
    stepIndex,
    step,
    isFirstStep: stepIndex === 0,
    isLastStep,
    draft,
    fieldIssues,
    notice,
    selectDatabase,
    setDatabasePort,
    patchDatabase,
    selectRuleSource,
    patchRuleSource,
    selectAuthenticationMode,
    patchSourceCredentials,
    patchAdmin,
    goNext,
    goBack,
    reportInfo,
    reportIssues,
    prepareSubmission,
    clearSensitive,
  };
}
