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
 * - **提示位**（notice）是一个结构化槽位：校验问题由 `goNext()` 写入，页面级的提示
 *   （例如「测试连接」）通过 `reportInfo()` 写入同一条路径。两者互斥但共用一个槽位，
 *   因此「下一步成功会清掉旧提示」这条旧行为得以保留——若拆成两份 state，点过一次
 *   测试连接后推进步骤，提示会残留。
 * - `goBack()` **不**清提示：旧实现回退时保留当前提示，用户能看到上一步缺什么。
 */
import { useCallback, useState } from "react";

import {
  controlPlaneDatabaseFor,
  isControlPlaneDatabaseKind,
  isRuleSourceAuthenticationMode,
  isRuleSourceKind,
  validateSetupStep,
  INITIALIZATION_STEPS,
  INITIAL_SETUP_DRAFT,
  type RuleSourceCredentials,
  type SetupAdminDraft,
  type SetupDatabaseDraft,
  type SetupDraft,
  type SetupIssue,
  type SetupRuleSourceDraft,
  type SetupStep,
} from "../model/setup";

/**
 * 提示位的两种内容。
 *
 * `issue` 是领域校验结论，UI 层负责翻译；`info` 是页面自己给出的说明文案（由调用方
 * 传入，本 Hook 不拥有界面文案）。
 */
export type SetupNotice =
  | { readonly kind: "issue"; readonly issue: SetupIssue }
  | { readonly kind: "info"; readonly text: string };

export interface SetupFlow {
  /** 有序步骤全集。步骤导航由本 Hook 拥有，页面只按它渲染步骤条。 */
  readonly steps: readonly SetupStep[];
  readonly stepIndex: number;
  readonly step: SetupStep;
  readonly isFirstStep: boolean;
  readonly isLastStep: boolean;
  readonly draft: SetupDraft;
  /** 当前选中的数据库元数据。 */
  readonly selectedDatabase: ReturnType<typeof controlPlaneDatabaseFor>;
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
  /** 校验当前步并前进；不通过时停在原地并写入提示位。 */
  goNext: () => void;
  /** 回退一步；保留当前提示。 */
  goBack: () => void;
  /** 页面写入一条说明性提示（例如连接检查结果）。 */
  reportInfo: (text: string) => void;
}

export function useSetupFlow(): SetupFlow {
  const [stepIndex, setStepIndex] = useState(0);
  const [draft, setDraft] = useState<SetupDraft>(INITIAL_SETUP_DRAFT);
  const [notice, setNotice] = useState<SetupNotice | null>(null);

  const step = INITIALIZATION_STEPS[stepIndex];
  const isLastStep = stepIndex === INITIALIZATION_STEPS.length - 1;

  // 三个单选控件的值域都是 string。协议值由类型守卫**收窄**成联合类型：不是受支持
  // 的值就保持当前状态，而不是像旧实现那样用 `as` 断言把任意字符串写进草稿。
  const selectDatabase = useCallback((value: string) => {
    if (!isControlPlaneDatabaseKind(value)) return;
    setDraft((current) => ({
      ...current,
      databaseKind: value,
      databasePort: controlPlaneDatabaseFor(value).defaultPort,
    }));
  }, []);

  const selectRuleSource = useCallback((value: string) => {
    if (!isRuleSourceKind(value)) return;
    setDraft((current) => ({ ...current, sourceKind: value }));
  }, []);

  const selectAuthenticationMode = useCallback((value: string) => {
    if (!isRuleSourceAuthenticationMode(value)) return;
    setDraft((current) => ({ ...current, sourceAuthenticationMode: value }));
  }, []);

  const setDatabasePort = useCallback((value: string) => {
    setDraft((current) => ({ ...current, databasePort: value }));
  }, []);

  const patchDatabase = useCallback((patch: Partial<SetupDatabaseDraft>) => {
    setDraft((current) => ({ ...current, database: { ...current.database, ...patch } }));
  }, []);

  const patchRuleSource = useCallback((patch: Partial<SetupRuleSourceDraft>) => {
    setDraft((current) => ({ ...current, source: { ...current.source, ...patch } }));
  }, []);

  const patchSourceCredentials = useCallback((patch: Partial<RuleSourceCredentials>) => {
    setDraft((current) => ({
      ...current,
      sourceCredentials: { ...current.sourceCredentials, ...patch },
    }));
  }, []);

  const patchAdmin = useCallback((patch: Partial<SetupAdminDraft>) => {
    setDraft((current) => ({ ...current, admin: { ...current.admin, ...patch } }));
  }, []);

  const goNext = useCallback(() => {
    const issues = validateSetupStep(step.id, draft);
    if (issues.length > 0) {
      setNotice({ kind: "issue", issue: issues[0] });
      return;
    }
    setNotice(null);
    setStepIndex((current) => Math.min(current + 1, INITIALIZATION_STEPS.length - 1));
  }, [draft, step.id]);

  const goBack = useCallback(() => {
    setStepIndex((current) => Math.max(0, current - 1));
  }, []);

  const reportInfo = useCallback((text: string) => {
    setNotice({ kind: "info", text });
  }, []);

  return {
    steps: INITIALIZATION_STEPS,
    stepIndex,
    step,
    isFirstStep: stepIndex === 0,
    isLastStep,
    draft,
    selectedDatabase: controlPlaneDatabaseFor(draft.databaseKind),
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
  };
}
