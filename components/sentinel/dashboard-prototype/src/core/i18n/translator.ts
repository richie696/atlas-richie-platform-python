/**
 * 翻译入口：把 `messages/` 下的 JSON 拼成底座 `Translator` 需要的字典。
 *
 * 中文
 * ----
 * 使用 `@richie696/react-framework` 的 `Translator`（字典 + 回退 locale + 命名插值）。
 * 本模块只负责**组装**。
 *
 * ## 为什么文案放 JSON 而不是 .ts
 *
 * - 翻译者改文案不用碰代码，也不用装 Node；
 * - 翻译平台（Transifex / Lokalise / Crowdin）能直接读这个目录；
 * - 「这个项目一共有哪些文案、每种语言覆盖到哪」在一个目录里看得完。
 *
 * 代价是失去**编译期**的键名检查（`t("ovrview.title")` 拼错不再报错），
 * 由 `tests/i18n/keycheck.mjs` 在 CI 里补：它扫描所有 `t("…")` 调用，
 * 验证每个键在每种语言里都存在，并校验三种语言的键集合完全一致。
 *
 * ## 目录约定
 *
 *     messages/<locale>/<namespace>.json
 *
 * 与 i18next 的 `i18n/{{lng}}/{{ns}}.json` 同构（见 i18next-scanner 的默认
 * `resource.loadPath`）。按 namespace 拆而不做成一个大文件，是为了让单个文件
 * 保持在可读规模（当前最大 155 键）；全部集中在一个 `messages/` 目录，是为了
 * 改一个 feature 的文案时能立刻看到「别处有没有用过同一个词」。
 *
 * ## 重复键仍然是错误
 *
 * 两个 namespace 抢同一个键名意味着消息归属没定清楚，组装期立刻抛错，
 * 而不是让后注册的静默覆盖先注册的。
 */
import { Translator } from "@richie696/react-framework";

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

import { FALLBACK_LOCALE, resolveLocale } from "./locales";
import type { MessageBundle, Translate } from "./types";

export type { Translate } from "./types";

/**
 * 每个 namespace 一个文件，按 namespace 顺序拼接。
 *
 * 中文
 * ----
 * 显式列出而不是用 `import.meta.glob`：文件增删会在**编译期**暴露，而 glob 要到
 * 运行时才发现漏掉。新增 namespace 时在这里加一行，`keycheck.mjs` 会跟着校验。
 */
const BUNDLES_BY_LOCALE = {
  "zh-CN": [shellZh, overviewZh, faultsZh, applicationsZh, realtimeZh, rulesZh, systemZh, identityZh],
  "en-US": [shellEn, overviewEn, faultsEn, applicationsEn, realtimeEn, rulesEn, systemEn, identityEn],
  "ja-JP": [shellJa, overviewJa, faultsJa, applicationsJa, realtimeJa, rulesJa, systemJa, identityJa],
} as const satisfies Readonly<Record<string, readonly MessageBundle[]>>;

/** 把某个 locale 的各 namespace 拼成一张扁平字典。重复键在这里抛错。 */
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

const DICTIONARY: Record<string, Record<string, string>> = Object.fromEntries(
  Object.entries(BUNDLES_BY_LOCALE).map(([locale, bundles]) => [locale, assemble(locale, bundles)]),
);

const translator = new Translator(DICTIONARY, FALLBACK_LOCALE);

/** 取得某个 locale 的翻译函数。未知 locale 回落到默认语言。 */
export function createTranslator(locale: string): Translate {
  const resolved = resolveLocale(locale);
  return (key, values) => translator.translate(key, resolved, values);
}
