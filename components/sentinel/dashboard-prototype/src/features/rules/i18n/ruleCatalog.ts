/**
 * 规则目录的表头文案键。
 *
 * 中文
 * ----
 * 表头是**文案键**而不是已翻译文本：列的语义属于目录面板，翻译发生在渲染时。
 * 协议列（例如配置来源）与展示列共用同一个键空间，不在这里区分。
 */

/** 目录列顺序即渲染顺序。 */
export const RULE_CATALOG_HEADERS = [
  "rules.resourceAndType",
  "rules.policy",
  "rules.threshold",
  "rules.source",
  "rules.status",
] as const;

/** 单个目录列的文案键。 */
export type RuleCatalogHeader = (typeof RULE_CATALOG_HEADERS)[number];
