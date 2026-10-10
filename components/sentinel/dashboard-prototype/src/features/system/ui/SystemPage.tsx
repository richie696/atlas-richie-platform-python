import systemStyles from "./System.module.scss";
import { scopedClasses } from "../../../shared/ui/styles/scopedClasses";
/**
 * 系统管理页面容器。
 *
 * 中文
 * ----
 * 页面只做三件事：持有 tab 导航状态、把读模型交给面板、把身份子页挂到对应 tab。
 *
 * - **tab 状态是纯 UI 导航状态**，不上提到 app 层 store：它不进入 feature 状态，
 *   跨页面没有第二个消费者。但它**进 URL query**（`view=<tab id>`），因此可分享、
 *   刷新后停在原处，并且能被视觉基线工具直接捕获——这一点是必要的：早先 tab 只存在
 *   于组件 state，基线只覆盖默认 tab，其余 4 个 tab 的改动没有任何自动回归保护。
 *   合法值由本 feature 的 `resolveSystemTab` 校验，路由边界不认识具体 tab。
 * - tab 用稳定 id（`permissions`）而不是中文标签；标签由 `SYSTEM_TAB_LABEL` 提供。
 *   否则改一次文案就会让已分享的链接失效。
 * - 面板按 tab 条件渲染且互斥，条件表达式的先后顺序不影响 DOM。
 * - 「账户维护」「角色绑定」两个 tab 的内容由 identity feature 拥有。本页通过
 *   identity 的**公共入口**引用它们，不再深导入 `features/identity/ui/*`：
 *   深导入让一个 feature 读另一个 feature 的私有文件，改动会互相打断
 *   （`REWRITE_PLAN.md` §9.5）。
 */
import { ActionButton } from "../../../shared/ui/ActionButton";
import { Intro } from "../../../shared/ui/Intro";
import { Status } from "../../../shared/ui/Status";
import type { ReactNode } from "react";
import type { DashboardPageProps } from "../../../shared/types/dashboard";
import type { createSystemObservationResources } from "../application/systemObservationResources";
import type { createSourceRegistrationWorkflow } from "../application/sourceRegistrationWorkflow";
import type { AuditQuery } from "../model/systemObservation";
import type { ControlPlaneAccessState } from "../../identity";
import { ROUTE } from "../../../shared/types/navigation";
import { SYSTEM_TABS, SYSTEM_TAB, resolveSystemTab, type SystemTab } from "../model/systemStatus";
import { SYSTEM_TAB_LABEL_KEY } from "../presentation/systemPresentation";
import { useTranslation } from "react-i18next";
import { ObservedPermissionsPanel } from "./ObservedPermissionsPanel";
import { ObservedConnectionsPanel } from "./ObservedConnectionsPanel";
import { ObservedProtocolsPanel } from "./ObservedProtocolsPanel";
import { ObservedAuditPanel } from "./ObservedAuditPanel";
import { SourceRegistryPanel } from "./SourceRegistryPanel";

type SystemObservationResources = ReturnType<typeof createSystemObservationResources>;

const styleModules = [systemStyles] as const;

export interface SystemPageProps {
  readonly navigate: DashboardPageProps["navigate"];
  readonly locale: string;
  /** URL `view` 参数；非法或缺失时由 `resolveSystemTab` 回落默认 tab。 */
  readonly view: string;
  /** 角色绑定的 URL 目标；系统 tab 与独立身份页使用相同目标语义。 */
  readonly accountId?: string;
  /** Identity panels are composed by the app owner to keep feature dependencies one-way. */
  readonly identityPanels: {
    readonly accounts: ReactNode;
    readonly roles: ReactNode;
  };
  readonly access: ControlPlaneAccessState;
  readonly observations: SystemObservationResources;
  readonly sourceRegistration: ReturnType<typeof createSourceRegistrationWorkflow> | null;
  readonly auditQuery: AuditQuery;
  readonly onAuditQueryChange: (query: AuditQuery) => void;
}

/** Connection, protocol, permission and identity administration workspace. */
export function SystemPage({
  navigate,
  view,
  accountId,
  identityPanels,
  access,
  observations,
  sourceRegistration,
  auditQuery,
  onAuditQueryChange,
}: SystemPageProps) {
  const { t } = useTranslation();
  // 受控：tab 不再是本组件的 state，唯一来源是 URL。切换 = 写回 URL。
  const tab: SystemTab = resolveSystemTab(view);
  const selectTab = (next: SystemTab) => {
    if (next === tab) return;
    navigate(ROUTE.System, { view: next });
  };

  return (
    <>
      <Intro
        eyebrow="ADMIN / SYSTEM"
        title={t("system.intro.title")}
        description={t("system.intro.description")}
        aside={<Status tone="blue">{t("system.intro.aside")}</Status>}
      />
      <div
        className={scopedClasses(styleModules, "tabs")}
        role="group"
        aria-label={t("system.intro.tabGroupLabel")}
      >
        {SYSTEM_TABS.map((id) => (
          <ActionButton
            type="button"
            aria-pressed={tab === id}
            className={scopedClasses(styleModules, tab === id ? "active" : "")}
            key={id}
            onClick={() => selectTab(id)}
          >
            {t(SYSTEM_TAB_LABEL_KEY[id])}
          </ActionButton>
        ))}
      </div>
      {tab === SYSTEM_TAB.Connections && (
        <>
          <ObservedConnectionsPanel resource={observations.connections} />
          {sourceRegistration && <SourceRegistryPanel workflow={sourceRegistration} />}
        </>
      )}
      {tab === SYSTEM_TAB.Permissions && <ObservedPermissionsPanel access={access} />}
      {tab === SYSTEM_TAB.Protocol && <ObservedProtocolsPanel resource={observations.protocols} />}
      {tab === SYSTEM_TAB.Audit && (
        <ObservedAuditPanel
          resource={observations.audit}
          query={auditQuery}
          onQueryChange={onAuditQueryChange}
          onPublication={(record) => {
            if (record.publicationId !== null)
              navigate(ROUTE.Rules, {
                ...(record.environmentId ? { environmentId: record.environmentId } : {}),
                ...(record.appId ? { appId: record.appId } : {}),
                ...(record.bindingId ? { bindingId: record.bindingId } : {}),
                publicationId: record.publicationId,
              });
          }}
        />
      )}
      {tab === SYSTEM_TAB.Accounts && identityPanels.accounts}
      {tab === SYSTEM_TAB.Roles && identityPanels.roles}
    </>
  );
}
