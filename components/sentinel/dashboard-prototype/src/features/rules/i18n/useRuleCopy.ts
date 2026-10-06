/**
 * 把扁平的 `RULES_COPY` 组装成规则工作台消费的结构。
 *
 * 中文
 * ----
 * 旧实现有两条并行的文案通道：页面自己 `t("rules.xxx")`，同时再把整个嵌套语言包
 * （`ruleMessages(locale)`）塞进编辑器。后者让「同一个 feature 的文案有两种读法」，
 * 也让表单组件为了拿字段标签而依赖一整个语言包对象。
 *
 * 现在两条通道同源：都走 `useTranslator()`。本 Hook 只做**结构还原**——把扁平键
 * 重新组装成 `types` / `fields` / `options` / `filters` / `scopes` / `versions` 这些
 * 表单组件本来就在用的结构，因此 `RuleEditor` 与五个表单一行都不用改。
 *
 * 为什么不直接把表单改成 `t("rules.fields.resourceName.label")`：那会牵动六个组件的
 * 全部 props，属于与「文案搬家 + 切换翻译来源」无关的改动。结构还原把变化原因限制
 * 在一个文件里。
 *
 * 译文全部来自 `useTranslator()`，本文件不含任何字面量。
 */
import { useMemo } from "react";

import type { Translate } from "../../../core/i18n/types";
import { useTranslator } from "../../../core/i18n/useTranslator";
import { RULE_KINDS, RULE_SCOPE, type RuleKind } from "../model/ruleKinds";
import { RULE_FIELD_KEYS } from "../model/ruleMessages";
import type {
  FieldCopy,
  RuleFieldKey,
  RuleOptionCopy,
  RuleTypeCopy,
  RuleWorkbenchMessages,
} from "../model/ruleMessages";

/**
 * 每一组下拉标签的键清单，顺序即协议值顺序。
 *
 * 旧包用数组下标配对（`localizedOptions` 会在长度不匹配时抛错）。扁平字典装不下数组，
 * 顺序因此固定在这里——**这份清单才是配对关系的唯一来源**，语言包只提供标签。
 */
const OPTION_LABEL_KEYS = {
  flowGrade: ["rules.options.flowGrade.qps", "rules.options.flowGrade.thread"],
  flowStrategy: [
    "rules.options.flowStrategy.direct",
    "rules.options.flowStrategy.chain",
    "rules.options.flowStrategy.relate",
  ],
  flowBehavior: [
    "rules.options.flowBehavior.reject",
    "rules.options.flowBehavior.warmUp",
    "rules.options.flowBehavior.queueing",
  ],
  degrade: [
    "rules.options.degrade.slowRequestRatio",
    "rules.options.degrade.errorRatio",
    "rules.options.degrade.errorCount",
  ],
  authority: ["rules.options.authority.white", "rules.options.authority.black"],
} as const satisfies Readonly<Record<keyof RuleOptionCopy, readonly string[]>>;

/** 规则工作台的全部文案。`t` 用于单条查表，`messages` 用于结构化消费。 */
export interface RuleCopy {
  /** 与 `useTranslator()` 同源的翻译函数。 */
  readonly t: Translate;
  readonly messages: RuleWorkbenchMessages;
}

/** 按给定顺序从翻译函数取一组标签。 */
function labels(t: Translate, keys: readonly string[]): readonly string[] {
  return keys.map((key) => t(key));
}

function buildMessages(t: Translate): RuleWorkbenchMessages {
  const types = {} as Record<RuleKind, RuleTypeCopy>;
  for (const kind of RULE_KINDS) {
    types[kind] = {
      label: t(`rules.types.${kind}.label`),
      description: t(`rules.types.${kind}.description`),
    };
  }

  const fields = {} as Record<RuleFieldKey, FieldCopy>;
  for (const key of RULE_FIELD_KEYS) {
    fields[key] = {
      label: t(`rules.fields.${key}.label`),
      hint: t(`rules.fields.${key}.hint`),
    };
  }

  // 五组逐一列出而不是遍历 `OPTION_LABEL_KEYS`：`RuleOptionCopy` 的属性是 readonly，
  // 遍历写入需要绕过类型系统；显式列举则由返回类型保证一个组都不漏。
  const options: RuleOptionCopy = {
    flowGrade: labels(t, OPTION_LABEL_KEYS.flowGrade),
    flowStrategy: labels(t, OPTION_LABEL_KEYS.flowStrategy),
    flowBehavior: labels(t, OPTION_LABEL_KEYS.flowBehavior),
    degrade: labels(t, OPTION_LABEL_KEYS.degrade),
    authority: labels(t, OPTION_LABEL_KEYS.authority),
  };

  return {
    types,
    fields,
    options,
    rules: {
      addException: t("rules.addException"),
      remove: t("rules.remove"),
      systemDisabled: t("rules.systemDisabled"),
      paramCompatibility: t("rules.paramCompatibility"),
      filters: {
        environment: t("rules.filters.environment"),
        production: t("rules.filters.production"),
        application: t("rules.filters.application"),
        allApplications: t("rules.filters.allApplications"),
        sample: t("rules.filters.sample"),
      },
      scopes: {
        [RULE_SCOPE.Application]: t("rules.scopes.application"),
        [RULE_SCOPE.Resource]: t("rules.scopes.resource"),
      },
      versions: {
        title: t("rules.versions.title"),
        subtitle: t("rules.versions.subtitle"),
        active: t("rules.versions.active"),
        scheduled: t("rules.versions.scheduled"),
        superseded: t("rules.versions.superseded"),
        publishedAt: t("rules.versions.publishedAt"),
        effectiveWindow: t("rules.versions.effectiveWindow"),
        returnTo: t("rules.versions.returnTo"),
        plannedWindow: t("rules.versions.plannedWindow"),
        noEnd: t("rules.versions.noEnd"),
        timeZone: t("rules.versions.timeZone"),
        createVersion: t("rules.versions.createVersion"),
        immutable: t("rules.versions.immutable"),
        previewOnly: t("rules.versions.previewOnly"),
      },
    },
  };
}

/** 规则工作台文案。结构在 locale 变化时才重建。 */
export function useRuleCopy(): RuleCopy {
  const t = useTranslator();
  const messages = useMemo(() => buildMessages(t), [t]);
  return { t, messages };
}
