/**
 * 规则版本与生效计划。
 *
 * 中文
 * ----
 * 草稿、版本、计划是三个**不能混为同一个可变对象**的层次（见
 * `规则控制台与运行观测设计.md` §5.1）：
 *
 * 1. 草稿可编辑，但不能直接成为计划目标；
 * 2. 校验通过的草稿固化为一个**不可变的完整快照版本**；
 * 3. 生效计划只引用版本，不复制规则内容。
 *
 * 因此版本类型只读，且 `checksum` 与 `baseVersionId` 是版本身份的一部分，不是展示字段。
 */
import type { RuleSourceKind } from "./ruleKinds";

/** 版本状态。`scheduled` 表示已有指向它的生效计划。 */
export const VERSION_STATE = Object.freeze({
  Active: "active",
  Scheduled: "scheduled",
  Superseded: "superseded",
} as const);

/** {@link VERSION_STATE} 的值联合。 */
export type VersionState = (typeof VERSION_STATE)[keyof typeof VERSION_STATE];

/**
 * 一个不可变规则集版本。
 *
 * `startsAt` / `endsAt` / `restoreVersion` 只在 `scheduled` 版本上出现；其余状态
 * 使用 `publishedAt`。用可选字段而不是联合类型，是为了让 fixture 与接口都能用同一
 * 个对象字面量描述。
 */
export interface RuleVersion {
  readonly id: string;
  readonly name: string;
  readonly state: VersionState;
  readonly source: RuleSourceKind;
  /** 已发布版本的时间点。 */
  readonly publishedAt?: string;
  /** 已计划版本的生效起点。 */
  readonly startsAt?: string;
  /** 已计划版本的生效终点。 */
  readonly endsAt?: string;
  /** 高峰期结束后要发布回的目标版本 id。 */
  readonly restoreVersion?: string;
  readonly summary: string;
  /** 内容校验和。生产实现由服务端计算，客户端不自行生成。 */
  readonly checksum: string;
}

/**
 * 生效计划。
 *
 * 中文
 * ----
 * 计划属于管理服务的调度器，不属于浏览器。类型保留在前端只为渲染「已计划」窗口与
 * 冲突状态；创建、取消与实际触发都不在这里发生。
 */
export interface ActivationPlan {
  readonly planId: string;
  readonly versionId: string;
  /** ISO 8601，必须带 IANA 时区偏移。 */
  readonly activateAt: string;
  readonly deactivateAt?: string;
  /** 必填：高峰结束时要发布回哪个版本，不能是「当时碰巧生效的版本」。 */
  readonly restoreVersionId: string;
  readonly timeZone: string;
  readonly state: "pending" | "triggered" | "completed" | "blocked_by_conflict" | "cancelled";
  readonly blockedReason?: string;
}
