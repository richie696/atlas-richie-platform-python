/**
 * 规则工作台的草稿状态机。
 *
 * 中文
 * ----
 * 旧实现在 `RulesPage` 里用六个 `useState` 手写草稿流程：选择规则、复制成草稿、
 * 编辑、进入/退出编辑态、校验反馈。状态之间的合法迁移只存在于事件处理函数里，
 * 页面组件因此既管数据又管渲染。
 *
 * 这里把草稿流程收成单一所有者：
 *
 * - **选中规则**与**草稿内容**是两条独立事实。切换选中项会丢弃草稿并退出编辑态；
 *   编辑草稿不会改变选中项。
 * - **编辑态**只能由显式命令进入或退出。表单里的任何一次改动都会自动进入编辑态，
 *   因为用户在只读视图里改字段本身就是意图信号。
 * - **校验反馈**是草稿的派生结论，由命令触发而不是由字段改动触发；用户继续编辑时
 *   反馈立即失效，否则会显示针对旧内容的结论。
 *
 * 本 Hook 不发请求。真实草稿保存、冲突与导航保护需接入 feature 用例，不能把当前
 * 单条本地草稿合同称为已经完成的 Console 工作流。
 */
import { useCallback, useMemo, useState } from "react";

import { ALL_APPLICATIONS, type TimeRangeId } from "../../../shared/types/navigation";
import type { RuleKindFilter } from "../model/ruleKinds";
import type { TypedRuleDraft } from "../editor/ruleDraft";
import type { RuleWorkbenchEntry } from "../editor/ruleEntry";
import {
  createDraftSession,
  resolveDraftSession,
  editDraftSession,
  type RuleDraftSession,
  type RuleValidationState,
} from "../editor/ruleEditing";
import { filterRuleCatalog, validateRuleDraft } from "../editor/rulePolicy";

/** 校验反馈的两种状态。`idle` 表示尚未执行校验，而不是「校验通过」。 */
export type { RuleValidationState } from "../editor/ruleEditing";

export interface UseRuleWorkbenchOptions {
  /** 目录全集。生产实现来自 gateway；原型阶段由 fixture 提供。 */
  readonly entries: readonly RuleWorkbenchEntry[];
  readonly appId: string;
  readonly range: TimeRangeId;
  readonly setAppId: (appId: string) => void;
  readonly setRange: (range: TimeRangeId) => void;
  /**
   * 规则类型筛选。**受控**：唯一来源是 URL 的 `view` 参数。
   *
   * 中文
   * ----
   * 类型筛选是离散选择、切换频率低，且明确描述「正在看哪一类规则」——可分享的观察
   * 范围，因此进 URL。搜索词是高频自由文本，仍留在本地 state，理由见
   * `REWRITE_PLAN.md` §「导航状态」。
   */
  readonly kindFilter: RuleKindFilter;
  /** 切换类型筛选。页面实现：写回 URL，而不是改本地 state。 */
  readonly onKindFilterChange: (value: RuleKindFilter) => void;
}

export interface RuleWorkbench {
  /** 当前应用与时间范围筛选下的目录。 */
  readonly visible: readonly RuleWorkbenchEntry[];
  /** 当前选中的目录条目；筛选后可能为空。 */
  readonly selected: RuleWorkbenchEntry | null;
  /** 编辑器正在编辑的草稿副本。 */
  readonly draft: TypedRuleDraft | null;
  /** 是否处于编辑态。 */
  readonly editing: boolean;
  readonly validation: RuleValidationState;
  readonly search: string;
  readonly kindFilter: RuleKindFilter;

  setSearch: (value: string) => void;
  setKindFilter: (value: RuleKindFilter) => void;
  /** 切换选中项：丢弃草稿、退出编辑态、清空校验反馈。 */
  select: (entry: RuleWorkbenchEntry) => void;
  /** 字段改动：更新草稿并进入编辑态，校验反馈失效。 */
  patchDraft: (next: TypedRuleDraft) => void;
  /** 显式进入编辑态（示例草稿按钮 / 编辑草稿按钮）。 */
  beginEditing: () => void;
  /** 执行本地语义校验。 */
  runValidation: () => void;
}

export function useRuleWorkbench(options: UseRuleWorkbenchOptions): RuleWorkbench {
  const { entries, appId } = options;
  const [search, setSearch] = useState("");
  /**
   * 选中项的 id，**不是**选中项本身。
   *
   * 中文
   * ----
   * 只存 id、不存条目：条目是 `visible` 的派生结果，存下来就成了第二份真相。
   * 初值用 `null` 而不是 `entries[0].id`——旧实现在这里取目录全集的第一项，
   * 而第一项的类型与当前筛选无关。深链 `view=degrade` 时该条目必然被滤掉，
   * 于是 `selected` 恒为 `null`。现在从可见集派生目标，再解析其草稿会话。
   */
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [storedSession, setSession] = useState<RuleDraftSession | null>(null);

  const visible = useMemo(
    () =>
      filterRuleCatalog(entries, {
        appId,
        allApplications: ALL_APPLICATIONS,
        kind: options.kindFilter,
        query: search,
      }),
    [appId, entries, options.kindFilter, search],
  );

  /**
   * 当前选中项的 id：**已按可见集收敛**。
   *
   * 中文
   * ----
   * 这一条同时承担三件事，且都不需要额外状态：
   *
   * 1. 深链进入某个筛选时，自动选中该筛选下的第一条——用户看到的是相关内容，
   *    而不是「目录里有东西但右侧是空的」。
   * 2. 筛选/搜索变化后旧选中项消失时，落到新的第一条；筛选结果为空时才真的
   *    没有选中项，此时检视器展示空态。
   * 3. `draft` 与 `selected` 的对应关系由 `resolveDraftSession` 保持：`selected` 一旦改变，
   *    草稿随之换成对应内容，不存在「草稿还留着上一条规则」的窗口。
   */
  const effectiveId = visible.some((entry) => entry.id === selectedId)
    ? selectedId
    : (visible[0]?.id ?? null);

  const selected = useMemo(
    () => visible.find((entry) => entry.id === effectiveId) ?? null,
    [effectiveId, visible],
  );

  // Derive the exact target before commit: no post-render Effect and no empty object assertion.
  const session = useMemo(
    () => resolveDraftSession(selected, storedSession),
    [selected, storedSession],
  );
  // Conditional adjustment of this component's own state follows React's documented pattern.
  // Reset before children commit so discarded drafts cannot resurface. No external effect here.
  if (session !== storedSession) setSession(session);

  const select = useCallback((entry: RuleWorkbenchEntry) => {
    setSelectedId(entry.id);
    setSession(createDraftSession(entry));
  }, []);

  const patchDraft = useCallback(
    (next: TypedRuleDraft) => {
      if (session) setSession(editDraftSession(session, next));
    },
    [session],
  );

  const beginEditing = useCallback(() => {
    if (session) setSession({ ...session, editing: true, validation: { status: "idle" } });
  }, [session]);

  const runValidation = useCallback(() => {
    if (!session) return;
    const issues = validateRuleDraft(session.rule);
    setSession({
      ...session,
      validation: issues.length > 0 ? { status: "failed", issues } : { status: "passed" },
    });
  }, [session]);

  return {
    visible,
    selected,
    draft: session?.rule ?? null,
    editing: session?.editing ?? false,
    validation: session?.validation ?? { status: "idle" },
    search,
    kindFilter: options.kindFilter,
    setSearch,
    setKindFilter: options.onKindFilterChange,
    select,
    patchDraft,
    beginEditing,
    runValidation,
  };
}
