/** Presentation metadata owned by this feature; never part of a wire/domain contract. */
import type { ApplicationHealth, InfraConnectionState } from "../model/overview";
import type { TranslationKey } from "../../../shared/types/translation";

/** 应用状态表格的列头。值是语言键，译文在 `i18n/locales.ts`。 */
export const APPLICATION_TABLE_HEADERS: readonly TranslationKey[] = Object.freeze([
  "overview.table.head.name",
  "overview.table.head.status",
  "overview.table.head.instances",
  "overview.table.head.cpuAvg",
  "overview.table.head.memoryAvg",
  "overview.table.head.httpQps",
  "overview.table.head.rtP95",
  "overview.table.head.blockedRate",
  "overview.table.head.ruleVersion",
  "overview.table.head.actions",
]);

/**
 * 健康等级的展示文案键。
 *
 * 中文
 * ----
 * 曾经还有一个 `healthReason: string` 字段，由 fixture 直接给中文（"资源压力"）。
 * 它的取值与 `health` 一一对应，于是同一份事实存在两份：改枚举要记得改 fixture，
 * 改 fixture 又不影响枚举——两份都可能对不上，且中文绕过了语言包。
 *
 * 这里收敛成「枚举 -> 语言键」的单向映射，`healthReason` 从模型里删除。
 * 将来若真需要自由文本说明（例如「CPU 连续 5 分钟高于 90%」），应另加一个
 * 明确的 `healthDetail` 字段，而不是让枚举标签兼职说明文字。
 */
export const APPLICATION_HEALTH_LABEL_KEY: Readonly<Record<ApplicationHealth, TranslationKey>> =
  Object.freeze({
    critical: "overview.table.health.critical",
    warning: "overview.table.health.warning",
    healthy: "overview.table.health.healthy",
  } as const);

/** 连接状态的展示文案键。 */
export const INFRA_STATE_LABEL_KEY: Readonly<Record<InfraConnectionState, TranslationKey>> =
  Object.freeze({
    available: "overview.infra.state.available",
    unavailable: "overview.infra.state.unavailable",
    connecting: "overview.infra.state.connecting",
  } as const);
