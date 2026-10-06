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
import type { DashboardPageProps } from "../../../shared/types/dashboard";
import { AccountMaintenancePage, RoleBindingPage } from "../../identity";
import { ROUTE } from "../../../app/router/route.constants";
import {
  SYSTEM_TABS,
  SYSTEM_TAB,
  SYSTEM_TAB_LABEL_KEY,
  resolveSystemTab,
  type SystemTab,
} from "../model/systemStatus";
import { useTranslator } from "../../../core/i18n/useTranslator";
import { CONNECTIONS, CONNECTION_SUMMARY_CARDS } from "../fixtures/systemFixtures";
import { ConnectionPanel } from "./ConnectionPanel";
import { PermissionsPanel } from "./PermissionsPanel";
import { ProtocolPanel } from "./ProtocolPanel";

export interface SystemPageProps {
  readonly navigate: DashboardPageProps["navigate"];
  readonly locale: string;
  /** URL `view` 参数；非法或缺失时由 `resolveSystemTab` 回落默认 tab。 */
  readonly view: string;
}

/** Connection, protocol, permission and identity administration workspace. */
export function SystemPage({ navigate, view }: SystemPageProps) {
  const t = useTranslator();
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
      <div className="tabs" role="group" aria-label={t("system.intro.tabGroupLabel")}>
        {SYSTEM_TABS.map((id) => (
          <ActionButton
            type="button"
            aria-pressed={tab === id}
            className={tab === id ? "active" : ""}
            key={id}
            onClick={() => selectTab(id)}
          >
            {t(SYSTEM_TAB_LABEL_KEY[id])}
          </ActionButton>
        ))}
      </div>
      {tab === SYSTEM_TAB.Connections && (
        <ConnectionPanel
          cards={CONNECTION_SUMMARY_CARDS}
          connections={CONNECTIONS}
          navigate={navigate}
        />
      )}
      {tab === SYSTEM_TAB.Permissions && <PermissionsPanel />}
      {tab === SYSTEM_TAB.Protocol && <ProtocolPanel />}
      {tab === SYSTEM_TAB.Accounts && <AccountMaintenancePage navigate={navigate} />}
      {tab === SYSTEM_TAB.Roles && <RoleBindingPage navigate={navigate} />}
    </>
  );
}
