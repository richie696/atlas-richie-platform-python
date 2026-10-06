/**
 * 语言资源的类型契约。
 *
 * 中文
 * ----
 * 一个 feature 拥有一份**扁平的**消息表：键是本 feature 的消息名，值是译文。
 * 扁平而不是嵌套，是为了让底座 `Translator` 的点号路径能直接命中，也让
 * 「这个 feature 有哪些文案」可以靠类型枚举出来，而不是运行时遍历对象。
 *
 * 归属规则（见 `docs/PRE_CODING_REVIEW.md` 第 2 问）：
 * 改某页的一个词，只能动那个 feature 的语言文件。全局壳层（导航、时间范围、
 * 语言名）归 `core/i18n`；六页正文一律归各自 feature，不留在共享包里。
 */
import type { DashboardLocale } from "./locales";

/** 单个 locale 下的扁平消息表。 */
export type MessageBundle = Readonly<Record<string, string>>;

/** 一个 feature 的三语文案。键与 `DASHBOARD_LOCALES` 一一对应。 */
export type LocaleBundle = Readonly<Record<DashboardLocale, MessageBundle>>;

/** 翻译函数的插值参数。 */
export type MessageValues = Readonly<Record<string, string | number>>;

/** 页面内使用的翻译函数。 */
export type Translate = (key: string, values?: MessageValues) => string;

/**
 * 合并各 feature 的文案表成底座 `Translator` 需要的字典。
 *
 * 重复键是**错误**而不是「后者覆盖前者」：两个 feature 抢同一个键名意味着
 * 消息归属没定清楚，必须在编译期或启动时暴露。
 */
export function buildDictionary(bundles: readonly LocaleBundle[]): Record<string, Record<string, string>> {
  const merged: Record<string, Record<string, string>> = {};
  for (const bundle of bundles) {
    for (const [locale, messages] of Object.entries(bundle)) {
      const target = (merged[locale] ??= {});
      for (const [key, value] of Object.entries(messages)) {
        if (key in target) {
          throw new Error(`语言键重复: "${key}" 同时出现在多个 feature 的 ${locale} 文案中`);
        }
        target[key] = value;
      }
    }
  }
  return merged;
}
