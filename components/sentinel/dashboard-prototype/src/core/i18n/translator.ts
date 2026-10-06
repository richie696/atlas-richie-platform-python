/**
 * 翻译入口：合并各 feature 的文案包，交给底座 `Translator`。
 *
 * 中文
 * ----
 * 使用 `@richie696/react-framework` 的 `Translator`（字典 + 回退 locale + 命名插值）。
 * 本模块只负责**组装**：各 feature 把自己的文案包交进来，重复键在组装时立刻抛错，
 * 而不是让后注册的 feature 静默覆盖先注册的。
 *
 * ## 迁移已完成
 *
 * `src/ruleI18n.ts`（嵌套对象 + 自己的 `createRuleTranslator`）已随规则工作台的
 * 迁移整体删除。七个 feature 的文案各自归自己的 `i18n/`，共享的壳层文案归
 * `core/i18n/shell.ts`；重复键在 `buildDictionary` 组装期抛错。
 */
import { Translator } from "@richie696/react-framework";

import { SHELL_COPY } from "./shell";
import { APPLICATIONS_COPY } from "../../features/applications/i18n/locales";
import { FAULTS_COPY } from "../../features/faults/i18n/locales";
import { IDENTITY_COPY } from "../../features/identity/i18n/locales";
import { OVERVIEW_COPY } from "../../features/overview/i18n/locales";
import { REALTIME_COPY } from "../../features/realtime/i18n/locales";
import { RULES_COPY } from "../../features/rules/i18n/locales";
import { SYSTEM_COPY } from "../../features/system/i18n/locales";
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
const BUNDLES: readonly LocaleBundle[] = [
  SHELL_COPY,
  FAULTS_COPY,
  OVERVIEW_COPY,
  APPLICATIONS_COPY,
  REALTIME_COPY,
  RULES_COPY,
  SYSTEM_COPY,
  IDENTITY_COPY,
];

const translator = new Translator(buildDictionary(BUNDLES), FALLBACK_LOCALE);

/** 取得某个 locale 的翻译函数。未知 locale 回落到默认语言。 */
export function createTranslator(locale: string): Translate {
  const resolved = resolveLocale(locale);
  return (key, values) => translator.translate(key, resolved, values);
}
