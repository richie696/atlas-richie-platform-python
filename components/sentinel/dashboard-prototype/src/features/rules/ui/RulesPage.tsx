/**
 * 规则工作台页面容器。
 *
 * 中文
 * ----
 * 页面只做三件事：取 feature 状态、组合区域、把用户动作映射为命令。草稿状态机在
 * `useRuleWorkbench`，目录与检视器各自独立成面板，表单按规则类型分发。
 *
 * 目录数据当前来自 `fixtures/`。接入 Console API 后由 `rules.gateway` 提供同样形状的
 * 条目列表，本组件不需要改动。
 */
import { ShieldCheckIcon as ShieldCheck } from "@phosphor-icons/react";
import { SESSION_CAPABILITY, useCan } from "../../../core/session";

import { ActionButton } from "../../../shared/ui/ActionButton";
import { Filters } from "../../../shared/ui/Filters";
import { Intro } from "../../../shared/ui/Intro";
import { Status } from "../../../shared/ui/Status";
import { createRuleTranslator, ruleMessages } from "../../../ruleI18n";
import type { RuleWorkbenchMessages } from "../model/ruleMessages";
import { RULE_CATALOG_HEADERS } from "../model/ruleCatalog";
import { RULE_KIND_ALL, resolveRuleKindFilter } from "../model/ruleKinds";
import { ROUTE } from "../../../app/router/route.constants";
import {
  RULE_APP_FIXTURES,
  RULE_FIXTURES,
  RULE_VERSION_FIXTURES,
} from "../fixtures/ruleFixtures";
import { useRuleWorkbench } from "../state/useRuleWorkbench";
import { RuleCatalogPanel } from "./RuleCatalogPanel";
import { RuleInspectorPanel } from "./RuleInspectorPanel";
import { VersionPlan } from "./VersionPlan";
import type { DashboardPageProps } from "../../../shared/types/dashboard";

export function RulesPage({
  navigate,
  appId,
  setAppId,
  range,
  setRange,
  locale,
  view,
}: DashboardPageProps) {
  const t = createRuleTranslator(locale);
  // `rules:write` 门禁。缺能力时隐藏写入口（§2：界面隐藏不是安全边界，
  // 服务端在每次写操作上仍会独立校验）。
  const canWrite = useCan(SESSION_CAPABILITY.RulesWrite);
  const messages = ruleMessages(locale) as RuleWorkbenchMessages;
  // 规则类型筛选受控：唯一来源是 URL 的 `view` 参数，切换 = 写回 URL。
  const kindFilter = resolveRuleKindFilter(view);
  const workbench = useRuleWorkbench({
    entries: RULE_FIXTURES,
    appId,
    range,
    setAppId,
    setRange,
    kindFilter,
    onKindFilterChange: (next) => {
      // 「全部类型」是默认值，不写进 URL，避免无意义的 `view=all` 噪声。
      // 传空串而不是 `undefined`：`navigate` 用 `'view' in context` 区分
      // 「没提到」与「要求清空」，`undefined` 会被前者吞掉导致筛选清不掉。
      navigate(ROUTE.Rules, { view: next === RULE_KIND_ALL ? "" : next });
    },
  });

  return (
    <>
      <Intro
        eyebrow={t("rules.eyebrow")}
        title={t("rules.title")}
        description={t("rules.description")}
        aside={<Status tone="blue">{t("rules.sourceOfTruth")}</Status>}
      />
      <Filters
        appId={appId}
        setAppId={setAppId}
        range={range}
        setRange={setRange}
        all
        showRange={false}
        labels={messages.rules.filters}
        applications={RULE_APP_FIXTURES}
      />
      <div className="rule-headline">
        <ShieldCheck size={24} color="#56d6a1" />
        <div>
          <b>{t("rules.headline")}</b>
          <p>{t("rules.headlineDetail")}</p>
        </div>
        {canWrite && (
          <ActionButton
            type="button"
            className="secondary-button"
            onClick={workbench.beginEditing}
          >
            {t("rules.editSample")}
          </ActionButton>
        )}
      </div>
      <VersionPlan versions={RULE_VERSION_FIXTURES} copy={messages.rules.versions} />
      <div className="rules-layout">
        <RuleCatalogPanel
          entries={workbench.visible}
          selectedId={workbench.selected?.id ?? ""}
          search={workbench.search}
          kindFilter={workbench.kindFilter}
          types={messages.types}
          detailLabel="rules.catalogDetail"
          searchLabel={t("rules.search")}
          allTypesLabel={t("rules.allTypes")}
          columnHeaders={RULE_CATALOG_HEADERS.map((key) => t(key))}
          activeLabel={t("rules.active")}
          emptyLabel={t("rules.noMatchingRule")}
          t={t}
          onSearch={workbench.setSearch}
          onKindFilter={workbench.setKindFilter}
          onSelect={workbench.select}
        />
        <RuleInspectorPanel
          entry={workbench.selected}
          draft={workbench.draft}
          editing={workbench.editing}
          validation={workbench.validation}
          messages={messages}
          scopes={messages.rules.scopes}
          t={t}
          onDraftChange={workbench.patchDraft}
          onBeginEditing={workbench.beginEditing}
          onValidate={workbench.runValidation}
        />
      </div>
    </>
  );
}
