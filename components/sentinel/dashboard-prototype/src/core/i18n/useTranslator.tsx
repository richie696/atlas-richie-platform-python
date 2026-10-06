/**
 * 当前 locale 的翻译函数。
 *
 * 中文
 * ----
 * locale 是**应用级**状态，被所有页面共享，且变化频率极低（用户手动切换）。
 * 因此这里用一个只承载 locale 的 Context 是安全的 —— 它不会「因为每次功能交互而
 * 改变」，这正是 `modern-react-ui-design` 反对 root Context 的原因。
 *
 * feature 状态（筛选、选中项、播放游标）**不走这里**，它们留在各自的 store 或组件
 * state 里。
 */
import { createContext, useContext, useMemo, type ReactNode } from "react";

import { DASHBOARD_LOCALES, FALLBACK_LOCALE, type DashboardLocale } from "./locales";
import { createTranslator, type Translate } from "./translator";

const LocaleContext = createContext<DashboardLocale>(FALLBACK_LOCALE);

export interface LocaleProviderProps {
  readonly locale: string;
  readonly children: ReactNode;
}

/** 持有当前 locale。value 只在用户切换语言时变。 */
export function LocaleProvider({ locale, children }: LocaleProviderProps) {
  const resolved = (DASHBOARD_LOCALES as readonly { code: string }[]).some(
    (item) => item.code === locale,
  )
    ? (locale as DashboardLocale)
    : FALLBACK_LOCALE;
  return <LocaleContext.Provider value={resolved}>{children}</LocaleContext.Provider>;
}

/** 取得当前 locale 的翻译函数。函数身份随 locale 稳定，页面可安全用于 memo 依赖。 */
export function useTranslator(): Translate {
  const locale = useContext(LocaleContext);
  return useMemo(() => createTranslator(locale), [locale]);
}

/** 取得当前 locale 代码。 */
export function useLocale(): DashboardLocale {
  return useContext(LocaleContext);
}
