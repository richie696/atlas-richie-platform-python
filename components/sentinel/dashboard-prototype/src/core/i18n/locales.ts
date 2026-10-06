/**
 * 支持的界面语言。
 *
 * 中文
 * ----
 * 语言只影响**展示**：规则 JSON、配置中心 key、资源名、版本与审计事实保持原值
 * （`DASHBOARD_CONTROL_PLANE.md` §4.3.1）。语言选择属于本机界面偏好，不进 URL、
 * 规则草稿或审计事件。
 */
export const DASHBOARD_LOCALES = Object.freeze([
  { code: "zh-CN", label: "简体中文" },
  { code: "en-US", label: "English" },
  { code: "ja-JP", label: "日本語" },
] as const);

/** 默认语言，也是翻译缺失时的回落 locale。 */
export const FALLBACK_LOCALE = "zh-CN";

/** 界面语言代码。 */
export type DashboardLocale = (typeof DASHBOARD_LOCALES)[number]["code"];

/** 传入未知 locale 时回落到默认语言。 */
export function resolveLocale(value: string): DashboardLocale {
  const candidate = value as DashboardLocale;
  return (DASHBOARD_LOCALES as readonly { code: string }[]).some(
    (item) => item.code === candidate,
  )
    ? candidate
    : FALLBACK_LOCALE;
}
