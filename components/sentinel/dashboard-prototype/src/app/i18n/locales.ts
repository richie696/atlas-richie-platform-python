/**
 * 界面语言定义与本机偏好。
 *
 * 中文
 * ----
 * 语言是**本机偏好**：不进 URL，也不进配置中心。放进 URL 会让「把只读视图发给同事」
 * 变成「把只读**权限**发给同事」，而权限必须由服务端裁决。
 *
 * 持久化用 `localStorage`。i18next 自带 `@i18next/browser-languagedetector` 能做这件事，
 * 但那会多一个运行时依赖，而需求只有「存一个 locale code + 首屏读它」——自己写
 * 十五行比引入一个包更合适。
 */
import { useCallback } from "react";
import { useTranslation } from "react-i18next";

/** 支持的界面语言。 */
export const LOCALES = Object.freeze(["zh-CN", "en-US", "ja-JP"] as const);

/** 默认语言，也是翻译缺失时的回落 locale。 */
export const FALLBACK_LOCALE = "zh-CN";

/** 界面语言代码。 */
export type Locale = (typeof LOCALES)[number];

/** 语言下拉里的显示名。语言名本身**不翻译**——用户按母语认它。 */
export const LOCALE_OPTIONS = Object.freeze([
  { code: "zh-CN", label: "简体中文" },
  { code: "en-US", label: "English" },
  { code: "ja-JP", label: "日本語" },
] as const);

/** 语言偏好键。独立于其它本机状态。 */
const STORAGE_KEY = "sentinel.locale";

/** 是否是受支持的 locale。存储与 URL 都是外部输入，必须逐个校验。 */
export function isSupportedLocale(value: unknown): value is Locale {
  return typeof value === "string" && (LOCALES as readonly string[]).includes(value);
}

/** 传未知值时回落到默认语言，不把任意字符串塞进 i18next。 */
export function resolveLocale(value: unknown): Locale {
  return isSupportedLocale(value) ? value : FALLBACK_LOCALE;
}

/**
 * 首屏语言。
 *
 * 中文
 * ----
 * 在**模块加载时**读一次，作为 i18next 的初始 `lng`。放在这里而不是组件里，是为了让
 * `config.ts` 的 `init()` 能同步拿到它——首帧就渲染译文，不闪一遍键名。
 */
export function readStoredLocale(): Locale {
  try {
    return resolveLocale(window.localStorage.getItem(STORAGE_KEY));
  } catch {
    // 隐私模式下读不到，用默认语言。
    return FALLBACK_LOCALE;
  }
}

/** 写回本机偏好。写不进去只影响下次首屏语言，不阻断本次切换。 */
export function writeStoredLocale(locale: Locale): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, locale);
  } catch {
    // 同上。
  }
}

/** 当前界面语言。跟随 i18next，`changeLanguage` 后自动重渲染。 */
export function useLocale(): Locale {
  const { i18n } = useTranslation();
  return resolveLocale(i18n.resolvedLanguage ?? i18n.language);
}

/** 切换界面语言并持久化。非法值回落到默认语言。 */
export function useLocaleSetter(): (next: string) => void {
  const { i18n } = useTranslation();
  return useCallback(
    (next: string) => {
      const resolved = resolveLocale(next);
      writeStoredLocale(resolved);
      void i18n.changeLanguage(resolved);
    },
    [i18n],
  );
}
