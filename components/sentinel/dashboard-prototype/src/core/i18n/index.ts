/**
 * 全局文案与语言设置的公共入口。
 *
 * 中文
 * ----
 * `core/i18n` 只拥有**壳层**文案与 locale 注册。页面正文归各自 feature 的
 * `i18n/`，避免出现一个混着所有页面文案的巨型包（见 `docs/PRE_CODING_REVIEW.md` 第 2 问）。
 */
export { DASHBOARD_LOCALES, FALLBACK_LOCALE, resolveLocale, type DashboardLocale } from "./locales";
export { createTranslator } from "./translator";
export { SHELL_COPY } from "./shell";
export type { LocaleBundle, MessageBundle, MessageValues, Translate } from "./types";
