/** Presentation metadata owned by this feature; never part of a wire/domain contract. */
import {
  INCIDENT_SEVERITY,
  INCIDENT_CATEGORY,
  SEVERITY_FILTER_ALL,
  type IncidentSeverity,
  type SeverityFilter,
  type IncidentCategory,
} from "../model/incident";
import type { TranslationKey } from "../../../shared/types/translation";

/**
 * 严重级别的展示文案**键**。
 *
 * 中文
 * ----
 * 协议值与文案分开维护。原先这里存的是中文字面量（"严重" / "警告" / "信息"），
 * 而 `i18n/locales.ts` 里又有一份 `faults.severity.*` 三语键——同一个概念两份
 * 定义，改一处不会提示另一处已经对不上。收敛成键，译文只存在于语言包。
 */
export const SEVERITY_LABEL_KEY: Readonly<Record<IncidentSeverity, TranslationKey>> = Object.freeze(
  {
    [INCIDENT_SEVERITY.Critical]: "faults.severity.critical",
    [INCIDENT_SEVERITY.Warning]: "faults.severity.warning",
    [INCIDENT_SEVERITY.Info]: "faults.severity.info",
  },
);

/** 级别筛选项的展示文案键。 */
export const SEVERITY_FILTER_LABEL_KEY: Readonly<Record<SeverityFilter, TranslationKey>> =
  Object.freeze({
    [SEVERITY_FILTER_ALL]: "faults.severity.all",
    ...SEVERITY_LABEL_KEY,
  });

/** 事件类别的展示文案键。 */
export const CATEGORY_LABEL_KEY: Readonly<Record<IncidentCategory, TranslationKey>> = Object.freeze(
  {
    [INCIDENT_CATEGORY.Resource]: "faults.category.resource",
    [INCIDENT_CATEGORY.ResponseTime]: "faults.category.responseTime",
    [INCIDENT_CATEGORY.RulePublished]: "faults.category.rulePublished",
    [INCIDENT_CATEGORY.RuleEffective]: "faults.category.ruleEffective",
  },
);
