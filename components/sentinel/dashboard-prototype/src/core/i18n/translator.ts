/**
 * 翻译入口：合并各 feature 的文案包，交给底座 `Translator`。
 *
 * 中文
 * ----
 * 使用 `@richie696/react-framework` 的 `Translator`（字典 + 回退 locale + 命名插值）。
 * 本模块只负责**组装**：各 feature 把自己的文案包交进来，重复键在组装时立刻抛错，
 * 而不是让后注册的 feature 静默覆盖先注册的。
 *
 * ## 迁移期状态
 *
 * 规则工作台仍在用旧的 `ruleI18n.ts`（嵌套对象 + 自己的 `createRuleTranslator`），
 * 它**不**并入这里 —— 旧包是嵌套结构、键名带 `rules.` 前缀，压平后与新包并存只会
 * 引入暂时无意义的键空间迁移。做法是：每迁完一个 feature，就把该页的调用点切到
 * `createTranslator`，六页全部迁完后 `ruleI18n.ts` 整体删除。
 *
 * 这样每个 feature 的文案所有权是独立的一步，不需要一次改完。
 *
 * 已迁：shell、faults、overview。其余 feature 的 `ui/` 层仍直接写中文字面量，
 * 真实规模见 `tests/i18n/audit.mjs`。
 */
import { Translator } from "@richie696/react-framework";

import { SHELL_COPY } from "./shell";
import { FAULTS_COPY } from "../../features/faults/i18n/locales";
import { OVERVIEW_COPY } from "../../features/overview/i18n/locales";
import { FALLBACK_LOCALE, resolveLocale } from "./locales";
import {
  buildDictionary,
  type LocaleBundle,
  type Translate,
} from "./types";

export type { Translate } from "./types";

/**
 * 已注册到统一字典的文案包。
 *
 * 新增 feature 迁移时在此追加一项。顺序不影响结果——重复键会抛错，不存在覆盖。
 */
const BUNDLES: readonly LocaleBundle[] = [SHELL_COPY, FAULTS_COPY, OVERVIEW_COPY];

const translator = new Translator(buildDictionary(BUNDLES), FALLBACK_LOCALE);

/** 取得某个 locale 的翻译函数。未知 locale 回落到默认语言。 */
export function createTranslator(locale: string): Translate {
  const resolved = resolveLocale(locale);
  return (key, values) => translator.translate(key, resolved, values);
}
