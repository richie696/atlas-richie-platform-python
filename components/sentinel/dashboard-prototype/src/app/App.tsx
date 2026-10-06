import { useMemo, type ReactNode } from "react";
import { InfoIcon as Info, ChartLineUpIcon as ChartLineUp } from "@phosphor-icons/react";
import { useOnlineStatus } from "@richie696/react-framework-react";

import { ActionButton } from "../shared/ui/ActionButton";
import { Select } from "../shared/ui/Select";
import { DASHBOARD_LOCALES, createRuleTranslator } from "../ruleI18n";
import {
  AccountMaintenancePage,
  ChangePasswordPage,
  LoginPage,
  RoleBindingPage,
  SystemInitializationPage,
} from "../features/identity";
import { ApplicationsPage } from "../features/applications/ui/ApplicationsPage";
import { FaultsPage } from "../features/faults/ui/FaultsPage";
import { OverviewPage } from "../features/overview/ui/OverviewPage";
import { RealtimePage } from "../features/realtime/ui/RealtimePage";
import { RulesPage } from "../features/rules/ui/RulesPage";
import { SystemPage } from "../features/system/ui/SystemPage";
import { AppShell } from "./shell/AppShell";
import { APPLICATION_SCOPE_IDS } from "./applicationScope";
import { navigationItemsWithIcons } from "./router/navigation";
import type { Navigate } from "../shared/types/dashboard";
import { ROUTE, type RouteId, type TimeRangeId } from "./router/route.constants";
import { useHashRoute } from "./router/useHashRoute";
import { useLocale, useLocaleSetter } from "../core/i18n/useTranslator";

/**
 * 应用装配边界。
 *
 * 中文
 * ----
 * 本组件只做三件事：装配应用壳、把 hash 解析成受控路由、把路由映射到页面实现。
 * 页面内部行为留在各自 feature 边界。
 *
 * 路由契约集中在 `app/router/route.constants.ts`：路径、访问前置条件、文案键和时间
 * 窗口协议值都在那里，页面与本组件都不允许出现裸路由字符串或中文时间窗口字面量。
 * 可分享的筛选上下文（应用 / 时间范围 /账号）序列化进 URL query，因此刷新和深链
 * 都能恢复同一视图。
 *
 * ## 导航状态只有一个所有者
 *
 * 旧实现用五个 `useState` 存 `route`/`appId`/`range`/`accountId`/`view`，再靠一个
 * `hashchange` effect 从 URL 同步进来、`navigate()` 再同步出去。同一份事实因此有
 * 两份副本（URL 与组件 state），两者靠 effect 双向搬运。副本会漂移。
 *
 * 现在这五个值全部由 `useHashRoute` 从 hash 派生，本组件不再持有它们的状态；
 * `navigate` 与页面级 setter 都只写 URL。唯一剩下的本地 state 是 `locale`——
 * 它是有界的用户偏好，不进入可分享链接。
 *
 * 登录与初始化页面不套应用壳——它们没有导航、没有全局筛选，也不应该出现
 * 「示例回放」横幅。
 *
 * 会话与初始化状态目前是原型常量。接入 `core/session` 后，守卫
 * `resolveAccessibleRoute` 依据真实会话快照决定实际展示的路由。
 */

/** 无账号上下文时的默认账号。与 `useHashRoute` 的缺省值保持同一来源。 */
const DEFAULT_ACCOUNT_ID = "account-admin";

/** 页面容器共用的筛选状态；由本组件持有并通过 props 下发。 */
interface PageContext {
  readonly navigate: Navigate;
  readonly appId: string;
  readonly setAppId: (appId: string) => void;
  readonly range: TimeRangeId;
  readonly setRange: (range: TimeRangeId) => void;
  readonly accountId: string;
  readonly locale: string;
  readonly view: string;
}

/**
 * 把受控路由映射到页面实现。
 *
 * 中文
 * ----
 * 未登记的路由不会渲染任何内容：路由静态表与本函数必须同步新增，
 * 避免出现「URL 合法但没有对应页面」的空壳路由。
 */
function renderRoute(route: RouteId, context: PageContext): ReactNode {
  const { navigate, appId, setAppId, range, setRange, accountId, locale, view } = context;
  switch (route) {
    case ROUTE.Overview:
      return <OverviewPage navigate={navigate} appId={appId} setAppId={setAppId} range={range} setRange={setRange} locale={locale} view={view} />;
    case ROUTE.Applications:
      return <ApplicationsPage navigate={navigate} appId={appId} setAppId={setAppId} range={range} setRange={setRange} locale={locale} view={view} />;
    case ROUTE.Rules:
      return <RulesPage navigate={navigate} appId={appId} setAppId={setAppId} range={range} setRange={setRange} locale={locale} view={view} />;
    case ROUTE.Realtime:
      return <RealtimePage navigate={navigate} appId={appId} setAppId={setAppId} range={range} setRange={setRange} locale={locale} view={view} />;
    case ROUTE.Faults:
      return <FaultsPage navigate={navigate} appId={appId} setAppId={setAppId} range={range} setRange={setRange} locale={locale} view={view} />;
    case ROUTE.System:
      return <SystemPage navigate={navigate} locale={locale} view={view} />;
    case ROUTE.Accounts:
      return <AccountMaintenancePage navigate={navigate} />;
    case ROUTE.Roles:
      return <RoleBindingPage navigate={navigate} selectedAccountId={accountId} />;
    case ROUTE.ChangePassword:
      return <ChangePasswordPage navigate={navigate} accountId={accountId} />;
    default:
      return null;
  }
}

export function App() {
  // 可分享的导航上下文（路由 / 应用 / 时间窗口 / 账号 / 子视图）全部由 URL 拥有。
  // 这里只订阅它，不再在组件里保存第二份副本。
  const route = useHashRoute({ applicationScopeIds: APPLICATION_SCOPE_IDS, defaultAccountId: DEFAULT_ACCOUNT_ID });
  // 语言是有界的本机偏好，不进可分享链接。状态由 `LocaleProvider` 持有，
  // 本组件只消费与下发——与页面里 `useTranslator()` 读的是同一份事实。
  const locale = useLocale();
  const setLocale = useLocaleSetter();
  const online = useOnlineStatus();
  const t = useMemo(() => createRuleTranslator(locale), [locale]);

  const { route: currentRoute, navigate, appId, setAppId, range, setRange, accountId, view } = route;

  if (currentRoute === ROUTE.Setup) {
    return <SystemInitializationPage onInitialized={() => navigate(ROUTE.Login)} />;
  }
  if (currentRoute === ROUTE.Login) {
    return <LoginPage navigate={navigate} />;
  }

  const navigation = navigationItemsWithIcons();

  const header = (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark"><ChartLineUp size={23} weight="bold" /></span>
        <span>Atlas Richie <strong>Sentinel</strong></span>
      </div>
      <nav className="main-nav" aria-label={t("shell.language")}>
        {navigation.map((item) => {
          const Icon = item.icon;
          return (
            <ActionButton
              key={item.id}
              type="button"
              className={currentRoute === item.id ? "active" : ""}
              onClick={() => navigate(item.id)}
            >
              <Icon size={16} />
              <span>{t(item.i18nKey)}</span>
            </ActionButton>
          );
        })}
      </nav>
      <div className="header-info">
        <div className="locale-control">
          <span>{t("shell.language")}</span>
          <Select
            label={t("shell.language")}
            isLabelHidden
            value={locale}
            onChange={setLocale}
            options={DASHBOARD_LOCALES.map((item) => ({ value: item.code, label: item.label }))}
            className="locale-selector"
          />
        </div>
        <span className={online ? "" : "offline-state"}>
          <i className="live-dot" /> {online ? t("shell.online") : t("shell.offline")}
        </span>
        <span className="clock">2026-09-14 14:32（示例）</span>
        <ActionButton
          className="avatar"
          type="button"
          onClick={() => navigate(ROUTE.Accounts)}
          aria-label={t("shell.nav.accounts")}
        >
          LD
        </ActionButton>
      </div>
    </header>
  );

  const banner = (
    <div className="demo-banner" role="status">
      <Info size={16} weight="fill" />
      <span><b>{t("shell.demo")}</b> · {t("shell.demoNotice")}</span>
    </div>
  );

  const footer = (
    <footer className="footer">
      Atlas Richie Sentinel · Dashboard 设计原型{" "}
      <span>示例数据仅用于交互与布局评审</span>
    </footer>
  );

  return (
    <AppShell
      header={header}
      banner={banner}
      contentClassName={`page-${currentRoute}`}
      footer={footer}
    >
      {renderRoute(currentRoute, {
        navigate,
        appId,
        setAppId,
        range,
        setRange,
        accountId,
        locale,
        view,
      })}
    </AppShell>
  );
}
