/**
 * Console API 的类型契约。
 *
 * 中文
 * ----
 * 与 `docs/CONSOLE_API_CONTRACT.md` 逐条对应。页面**只依赖这里的类型**，
 * 不依赖数据来源——接真实控制面时只需换一个 gateway 实现，页面不动。
 *
 * ## 为什么先冻结类型而不是先接服务端
 *
 * `DASHBOARD_CONTROL_PLANE.md` §6.1「契约先行」。控制面服务还不存在，
 * 如果等它写好再定形状，页面会先长出一套临时抽象、之后再推翻——那时
 * 7 个页面都得改。现在定死形状，服务端按它实现即可。
 *
 * ## 当前实现是 fixture-backed
 *
 * `fixtureGateway` 从各 feature 的 `fixtures/` 目录读数据并模拟异步，**不是**网络调用。
 * 它存在的意义是让页面的取数路径先跑通一遍真实形态（Promise、loading、错误），
 * 而不是继续让页面 `import { X_FIXTURES }` ——后者在接后端时必然全改。
 */
import type { ApplicationRecord } from "../../features/applications/model/instance";
import type { ApplicationSummary } from "../../features/overview/model/overview";
import type { FleetAttention } from "../../features/overview/model/overview";
import type { InfraStatus } from "../../features/overview/model/overview";
import type { MetricPoint } from "../../shared/types/dashboard";

/** 接口错误。`code` 决定客户端怎么渲染，`403` 与「没有数据」必须可区分。 */
export type ApiErrorCode =
  | "validation_failed"
  | "unauthenticated"
  | "capability_denied"
  | "version_conflict"
  | "readback_mismatch"
  | "config_center_unavailable";

export class ApiError extends Error {
  constructor(
    readonly code: ApiErrorCode,
    message: string,
    /** `capability_denied` 时给出缺哪项能力。 */
    readonly capability?: string,
    /** `validation_failed` 时的字段级问题。 */
    readonly issues?: readonly { field: string; message: string }[],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** 一次查询的观察范围。指标口径见契约 §4。 */
export interface MetricQuery {
  readonly appId?: string;
  readonly resource?: string;
  readonly range: string;
}

/** 带口径信息的读数。任何展示出来的数字都必须带这些字段。 */
export interface ScopedMetric {
  readonly points: readonly MetricPoint[];
  readonly unit: string;
  /** `host` / `container` / `process` / `instance` / `application`。 */
  readonly scope: string;
  /** 采集来源标识；未接入时为空串而不是「0」。 */
  readonly source: string;
  /** 采样新鲜度（ISO 时间）。 */
  readonly sampledAt: string;
}

/**
 * 控制台读模型网关。
 *
 * 页面通过它取数，不直接 `import` fixtures。方法与契约 §6 的端点一一对应。
 */
export interface ConsoleGateway {
  /** 契约 §6 `/rules/snapshot`：权威完整快照。 */
  getRuleSnapshot(): Promise<unknown>;
  /** 契约 §6 `/system/connections`：连通性与能力边界。 */
  getConnections(): Promise<readonly InfraStatus[]>;
  /** 契约 §6 `/metrics/query`：按 scope / window 查询。 */
  queryMetrics(query: MetricQuery): Promise<ScopedMetric>;
  /** 契约 §6 `/system/permissions`：角色与能力声明。 */
  getPermissions(): Promise<readonly { roleId: string; capabilities: readonly string[] }[]>;
}

/**
 * 应用与实例页需要的读模型。
 *
 * 用 `ApplicationRecord` 而不是总览页的 `ApplicationSummary`：两者字段不同
 * （前者带 host / container / 进程级指标，后者带大盘聚合值），**强行统一会
 * 造出一个两边都不需要的类型**。契约层不做这种合并——同一份后端数据在两个页面
 * 的投影本来就不同。
 */

/** 总览页需要的读模型。 */
export interface FleetOverviewSnapshot {
  readonly applications: readonly ApplicationSummary[];
  readonly attention: FleetAttention;
  readonly infra: readonly InfraStatus[];
}
