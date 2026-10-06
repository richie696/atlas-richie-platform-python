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

/**
 * 规则类型与表单字段的文案键映射。
 *
 * 为什么显式列出而不是 `` t(`rules.types.${kind}.label`) ``：模板拼出的键
 * 静态扫描器无法枚举——`i18n:check` 看不到它们，语言包里少一个字段标签时
 * 不会有任何报错，只会在那个字段的表单上显示原始键名。改成显式映射后，
 * 全部 155 个键都变成字面量，可被校验；`satisfies` 还保证枚举加了一个值
 * 就必须在这里补一行。
 */
const TYPE_COPY_KEYS = {
  authority: { label: "rules.types.authority.label", description: "rules.types.authority.description" },
  degrade: { label: "rules.types.degrade.label", description: "rules.types.degrade.description" },
  flow: { label: "rules.types.flow.label", description: "rules.types.flow.description" },
  param: { label: "rules.types.param.label", description: "rules.types.param.description" },
  system: { label: "rules.types.system.label", description: "rules.types.system.description" },
} as const satisfies Readonly<Record<RuleKind, { label: string; description: string }>>;

const FIELD_COPY_KEYS = {
  authorityMode: { label: "rules.fields.authorityMode.label", hint: "rules.fields.authorityMode.hint" },
  averageRt: { label: "rules.fields.averageRt.label", hint: "rules.fields.averageRt.hint" },
  breakDuration: { label: "rules.fields.breakDuration.label", hint: "rules.fields.breakDuration.hint" },
  callerOrigin: { label: "rules.fields.callerOrigin.label", hint: "rules.fields.callerOrigin.hint" },
  circuitStrategy: { label: "rules.fields.circuitStrategy.label", hint: "rules.fields.circuitStrategy.hint" },
  circuitThreshold: { label: "rules.fields.circuitThreshold.label", hint: "rules.fields.circuitThreshold.hint" },
  clusterMode: { label: "rules.fields.clusterMode.label", hint: "rules.fields.clusterMode.hint" },
  clusterThresholdType: { label: "rules.fields.clusterThresholdType.label", hint: "rules.fields.clusterThresholdType.hint" },
  controlBehavior: { label: "rules.fields.controlBehavior.label", hint: "rules.fields.controlBehavior.hint" },
  controlStrategy: { label: "rules.fields.controlStrategy.label", hint: "rules.fields.controlStrategy.hint" },
  cpuUsage: { label: "rules.fields.cpuUsage.label", hint: "rules.fields.cpuUsage.hint" },
  entranceQps: { label: "rules.fields.entranceQps.label", hint: "rules.fields.entranceQps.hint" },
  exceptionThreshold: { label: "rules.fields.exceptionThreshold.label", hint: "rules.fields.exceptionThreshold.hint" },
  localFallback: { label: "rules.fields.localFallback.label", hint: "rules.fields.localFallback.hint" },
  maxQueueingTime: { label: "rules.fields.maxQueueingTime.label", hint: "rules.fields.maxQueueingTime.hint" },
  maximumThreads: { label: "rules.fields.maximumThreads.label", hint: "rules.fields.maximumThreads.hint" },
  minimumRequests: { label: "rules.fields.minimumRequests.label", hint: "rules.fields.minimumRequests.hint" },
  originList: { label: "rules.fields.originList.label", hint: "rules.fields.originList.hint" },
  parameterExceptions: { label: "rules.fields.parameterExceptions.label", hint: "rules.fields.parameterExceptions.hint" },
  parameterIndex: { label: "rules.fields.parameterIndex.label", hint: "rules.fields.parameterIndex.hint" },
  parameterType: { label: "rules.fields.parameterType.label", hint: "rules.fields.parameterType.hint" },
  parameterValue: { label: "rules.fields.parameterValue.label", hint: "rules.fields.parameterValue.hint" },
  relatedResource: { label: "rules.fields.relatedResource.label", hint: "rules.fields.relatedResource.hint" },
  resourceName: { label: "rules.fields.resourceName.label", hint: "rules.fields.resourceName.hint" },
  sampleCount: { label: "rules.fields.sampleCount.label", hint: "rules.fields.sampleCount.hint" },
  singleNodeThreshold: { label: "rules.fields.singleNodeThreshold.label", hint: "rules.fields.singleNodeThreshold.hint" },
  slowCallRatio: { label: "rules.fields.slowCallRatio.label", hint: "rules.fields.slowCallRatio.hint" },
  statisticPeriod: { label: "rules.fields.statisticPeriod.label", hint: "rules.fields.statisticPeriod.hint" },
  statisticWindow: { label: "rules.fields.statisticWindow.label", hint: "rules.fields.statisticWindow.hint" },
  systemLoad: { label: "rules.fields.systemLoad.label", hint: "rules.fields.systemLoad.hint" },
  thresholdType: { label: "rules.fields.thresholdType.label", hint: "rules.fields.thresholdType.hint" },
  warmUpPeriod: { label: "rules.fields.warmUpPeriod.label", hint: "rules.fields.warmUpPeriod.hint" },
} as const satisfies Readonly<Record<RuleFieldKey, { label: string; hint: string }>>;

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
  // 顺序由 `RULE_KINDS` / `RULE_FIELD_KEYS` 决定，**不能改成遍历映射表**。
  // 映射表是对象字面量，属性顺序是字母序（authority, degrade, flow, …），
  // 而这里是声明序（flow, degrade, system, authority, param）——下拉选项按
  // `Object.values(types)` 渲染，顺序一变界面就变了，字节数却完全相同。
  // 这条是视觉基线抓出来的：`rules-filter-system` 的 DOM 不等价而大小一字不差。
  //
  // 映射表只负责「枚举值 → 语言键」的查法：键是字面量可被 `i18n:check` 校验，
  // 而模板拼键 `` t(`rules.types.${kind}.label`) `` 扫不出来。
  const types = {} as Record<RuleKind, RuleTypeCopy>;
  for (const kind of RULE_KINDS) {
    const copy = TYPE_COPY_KEYS[kind];
    types[kind] = { label: t(copy.label), description: t(copy.description) };
  }

  const fields = {} as Record<RuleFieldKey, FieldCopy>;
  for (const key of RULE_FIELD_KEYS) {
    const copy = FIELD_COPY_KEYS[key];
    fields[key] = { label: t(copy.label), hint: t(copy.hint) };
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
