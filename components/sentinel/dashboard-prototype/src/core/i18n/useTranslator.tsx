/**
 * 当前 locale 的 Context：同时提供**读取**与**设置**。
 *
 * 中文
 * ----
 * locale 是**应用级**状态：被壳层与所有页面共享，变化频率极低（用户手动切换）。
 * 用一个只承载 locale 的 Context 是安全的——它不会「因为每次功能交互而改变」，
 * 这正是 `modern-react-ui-design` 反对 root Context 的原因。
 *
 * feature 状态（筛选、选中项、播放游标）**不走这里**，它们留在各自的 store 或组件
 * state 里。
 *
 * ## 这里必须同时拥有 setter，不能只收一个 locale 字符串
 *
 * 旧实现是 `<LocaleProvider locale={initialLocale}>`，其中 `initialLocale` 在
 * `main.tsx` 模块加载时从 `localStorage` 读一次就再也不变。而 `App` 内部另有一份
 * 活的 `useState`。结果是**同一个 locale 存在两份**：
 *
 * - 壳层导航用 `App` 里的那份 → 切语言生效
 * - 用 `useTranslator()` 的页面读 Context 里那份 → **永远不响应语言选择器**
 *
 * 实测症状：故障分析页是第一个迁到 `useTranslator()` 的 feature，源码里零中文
 * 字面量、文案包三语齐全，运行时切到 English 标题仍是「故障分析」。
 *
 * 顺带修掉另一个死代码：原先的 `setLocale` 只改 `App` 的 state，从不写
 * `localStorage`，所以 `main.tsx` 里「首屏从 `sentinel.locale` 读取」永远读到空串。
 */
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

import { DASHBOARD_LOCALES, FALLBACK_LOCALE, resolveLocale, type DashboardLocale } from "./locales";
import { createTranslator, type Translate } from "./translator";

/** locale 偏好键。属于本机界面偏好，不进 URL，也不进配置中心。 */
const STORAGE_KEY = "sentinel.locale";

interface LocaleContextValue {
  readonly locale: DashboardLocale;
  readonly setLocale: (next: string) => void;
}

const LocaleContext = createContext<LocaleContextValue | null>(null);

/** 读本机偏好；隐私模式下 localStorage 可能抛异常，此时回落到默认语言即可。 */
function readStoredLocale(): string {
  try {
    return window.localStorage.getItem(STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

export interface LocaleProviderProps {
  readonly children: ReactNode;
  /**
   * 覆盖首屏语言。仅供测试与将来「由上层决定初始语言」的场景使用；
   * 正常运行不需要传，语言由本机偏好决定。
   */
  readonly initialLocale?: string;
}

/** 持有当前 locale 并提供设置命令。value 只在语言真正变化时才变。 */
export function LocaleProvider({ children, initialLocale }: LocaleProviderProps) {
  const [locale, setLocaleState] = useState<DashboardLocale>(() =>
    resolveLocale(initialLocale ?? readStoredLocale()),
  );

  const setLocale = useCallback((next: string) => {
    // 非法值回落到默认语言，不把任意字符串塞进 Context。
    const resolved = resolveLocale(next);
    setLocaleState(resolved);
    try {
      window.localStorage.setItem(STORAGE_KEY, resolved);
    } catch {
      // 写不进去（隐私模式 / 配额满）只影响下次首屏语言，不阻断本次切换。
    }
  }, []);

  const value = useMemo<LocaleContextValue>(() => ({ locale, setLocale }), [locale, setLocale]);
  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

function useLocaleContext(): LocaleContextValue {
  const value = useContext(LocaleContext);
  // Provider 缺失时给出可读的报错，而不是静默回落成「永远是中文」——
  // 后者会让「页面没跟着切语言」看起来像迁移没做完。
  if (!value) {
    throw new Error("useTranslator/useLocale 必须在 <LocaleProvider> 内使用");
  }
  return value;
}

/** 取得当前 locale。 */
export function useLocale(): DashboardLocale {
  return useLocaleContext().locale;
}

/** 取得语言切换命令。壳层的语言下拉用它。 */
export function useLocaleSetter(): (next: string) => void {
  return useLocaleContext().setLocale;
}

/** 取得当前 locale 的翻译函数。函数身份随 locale 稳定，页面可安全用于 memo 依赖。 */
export function useTranslator(): Translate {
  const locale = useLocaleContext().locale;
  return useMemo(() => createTranslator(locale), [locale]);
}
