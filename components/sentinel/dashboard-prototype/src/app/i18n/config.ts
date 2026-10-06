/**
 * i18next 初始化。
 *
 * 中文
 * ----
 * 翻译机制完全交给社区库：[i18next](https://www.i18next.com/) 负责资源、回退与插值，
 * [react-i18next](https://react.i18next.com/) 提供 React 绑定。本文件是**唯一的配置
 * 点**——组件里不再有任何自建的翻译包装。
 *
 * ## 资源形状：一个 locale 一张扁平表
 *
 * i18next 原生支持 namespace（`t('ns:key')`，`nsSeparator: ':'`）。本项目**关闭**
 * namespace 分隔符，把 8 个 namespace 的 JSON 合并成该 locale 的单张扁平表：
 *
 * - 键本来就是 `feature.area.field` 形式，feature 名本身就是命名空间，不需要第二层；
 * - 关闭 `nsSeparator` 后，键里出现 `:` 也会被当普通字符；
 * - 合并时重复键直接抛错——两个 namespace 抢同一个键名意味着消息归属没定清楚。
 *
 * ## 首帧必须是译文
 *
 * 没有 backend 需要加载、`resources` 又是同步对象时 i18next 会同步完成初始化，首帧
 * 即可取到译文。曾想显式写 `initImmediate: false` 强制它，但 v26 的 `InitOptions`
 * 里已无此选项（写上去 typecheck 会报错）——靠 `tests/visual` 的 DOM 等价验证首帧。
 *
 * ## 不要开 `nonExplicitSupportedLngs`
 *
 * 它曾被我「顺手」加在配置里，结果**整个应用渲染出原始键名**：i18next 认为
 * `isSupportedCode('zh-CN') === false`，`toResolveHierarchy('zh-CN')[0]` 是
 * undefined，于是每个 `t()` 都回退成键本身。资源其实完好——519 个键都在 store 里，
 * `getResourceBundle('zh-CN','translation')` 也取得到值。
 *
 * 该选项的语义是「supportedLngs 里列的是**完整**代码，同时接受更短的**隐式**形式」，
 * 开启后 i18next 期待的反而是不完整代码（`zh`），完整的 `zh-CN` 被判为不支持。
 * 我们三个 locale 都是完整代码，不需要隐式匹配。
 *
 * ## 键的完整性由 CI 保证
 *
 * `Translate` 的 key 是 `string`，`t("ovrview.title")` 拼错在编译期无声无息。
 * `npm run i18n:check` 扫源码里字面量写出的键并校验它们都存在，同时校验三语键集合
 * 完全一致。这是换 JSON 换来的代价，有意识地用 CI 补，而不是靠人记。
 */
import i18next from "i18next";
import { initReactI18next } from "react-i18next";

import shellZh from "./messages/zh-CN/shell.json";
import overviewZh from "./messages/zh-CN/overview.json";
import faultsZh from "./messages/zh-CN/faults.json";
import applicationsZh from "./messages/zh-CN/applications.json";
import realtimeZh from "./messages/zh-CN/realtime.json";
import rulesZh from "./messages/zh-CN/rules.json";
import systemZh from "./messages/zh-CN/system.json";
import identityZh from "./messages/zh-CN/identity.json";

import shellEn from "./messages/en-US/shell.json";
import overviewEn from "./messages/en-US/overview.json";
import faultsEn from "./messages/en-US/faults.json";
import applicationsEn from "./messages/en-US/applications.json";
import realtimeEn from "./messages/en-US/realtime.json";
import rulesEn from "./messages/en-US/rules.json";
import systemEn from "./messages/en-US/system.json";
import identityEn from "./messages/en-US/identity.json";

import shellJa from "./messages/ja-JP/shell.json";
import overviewJa from "./messages/ja-JP/overview.json";
import faultsJa from "./messages/ja-JP/faults.json";
import applicationsJa from "./messages/ja-JP/applications.json";
import realtimeJa from "./messages/ja-JP/realtime.json";
import rulesJa from "./messages/ja-JP/rules.json";
import systemJa from "./messages/ja-JP/system.json";
import identityJa from "./messages/ja-JP/identity.json";

import { FALLBACK_LOCALE, LOCALES, readStoredLocale, type Locale } from "./locales";
import type { MessageBundle } from "./types";

/**
 * 每个 namespace 一个文件，按 namespace 顺序拼接。
 *
 * 显式列出而不是 `import.meta.glob`：文件增删会在**编译期**暴露，glob 要到运行时
 * 才发现漏掉。新增 namespace 时在这里加一行，`npm run i18n:check` 会跟着校验。
 */
const BUNDLES_BY_LOCALE = {
  "zh-CN": [shellZh, overviewZh, faultsZh, applicationsZh, realtimeZh, rulesZh, systemZh, identityZh],
  "en-US": [shellEn, overviewEn, faultsEn, applicationsEn, realtimeEn, rulesEn, systemEn, identityEn],
  "ja-JP": [shellJa, overviewJa, faultsJa, applicationsJa, realtimeJa, rulesJa, systemJa, identityJa],
} as const;

/** 把某个 locale 的各 namespace 拼成一张扁平表。重复键在这里抛错。 */
function assemble(locale: string, bundles: readonly MessageBundle[]): Record<string, string> {
  const merged: Record<string, string> = {};
  for (const bundle of bundles) {
    for (const [key, value] of Object.entries(bundle)) {
      if (key in merged) {
        throw new Error(`语言键重复: "${key}" 在 ${locale} 的多个 namespace 中同时出现`);
      }
      merged[key] = value;
    }
  }
  return merged;
}

export const resources = Object.fromEntries(
  Object.entries(BUNDLES_BY_LOCALE).map(([locale, bundles]) => [
    locale,
    { translation: assemble(locale, bundles) },
  ]),
);

if (!i18next.isInitialized) {
  void i18next.use(initReactI18next).init({
    resources,
    lng: readStoredLocale(),
    fallbackLng: FALLBACK_LOCALE,
    supportedLngs: LOCALES,
    // 键是**扁平**的（`"overview.intro.title": "…"`），因此关掉 namespace 分隔符：
    // 本项目不用 `ns:key` 形式，键里出现 `:` 也应当被当普通字符。
    //
    // `keySeparator` 保持默认（`.`）：i18next 会**先按字面键取、取不到才拆分**，
    // 所以扁平键与嵌套键都能用，不必关掉——两种风格兼容比收紧更省心。
    nsSeparator: false,
    // 缺键时 i18next 返回键本身；不要把「键」再当 HTML 解释一遍。
    interpolation: { escapeValue: false },
    react: { useSuspense: false },
  });
}

/** i18next 实例。组件一般用 `useTranslation()`，只有需要 `changeLanguage` 时才直接拿它。 */
export default i18next;
export type { Locale };
