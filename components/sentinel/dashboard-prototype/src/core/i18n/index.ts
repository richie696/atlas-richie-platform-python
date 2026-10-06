/**
 * 全局文案与语言设置的公共入口。
 *
 * 中文
 * ----
 * `core/i18n` 拥有 locale 注册、字典组装与 locale 状态。**文案本身全部在
 * `messages/<locale>/<namespace>.json`**，集中一处，按 namespace 分文件——
 * 与 i18next 的 `i18n/{{lng}}/{{ns}}.json` 同构。
 */
export { DASHBOARD_LOCALES, FALLBACK_LOCALE, resolveLocale, type DashboardLocale } from "./locales";
export { createTranslator } from "./translator";
export type { LocaleBundle, MessageBundle, MessageValues, Translate } from "./types";
