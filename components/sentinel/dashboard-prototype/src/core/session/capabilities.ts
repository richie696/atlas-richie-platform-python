/**
 * 控制台的能力（权限）模型。
 *
 * 中文
 * ----
 * `DASHBOARD_CONTROL_PLANE.md` §2 规定服务端只判断两个能力，两项可独立授予：
 *
 * | 能力 | 允许的页面和动作 |
 * | --- | --- |
 * | `metrics:view` | 总览中的流量/资源指标、趋势图、实例指标详情和指标查询 API。 |
 * | `rules:write` | 新建、修改、停用、发布、回滚规则。 |
 *
 * ## 为什么能力值归 `core` 而不是某个 feature
 *
 * 它此前在两处**各定义了一份**：`features/identity/model/account.ts` 的
 * `IDENTITY_CAPABILITY` 与 `features/system/model/systemStatus.ts` 的 `CAPABILITY`。
 * 两份值相同，但改名只改一处——而角色授权（identity）与权限声明（system）
 * 正是要互相印证的同一个概念，一份漂移之后没人能看出「权限声明与实际角色对不上」。
 *
 * 能力是**跨 feature 的协议值**，因此归 `core`：它既不属于身份，也不属于系统。
 * 两个 feature 引用这里，不再各自持有字面量。
 *
 * ## 客户端持有的只是一份快照
 *
 * 原文写得很清楚：服务端在**每次请求**上重新判定，客户端的能力快照只用于
 * 导航与展示。因此这里不做任何「因为有权限所以可以写」的业务判断，只提供
 * 「能不能显示这个入口」。
 *
 * 界面隐藏**不是安全边界**。缺 `rules:write` 时深链与 API 仍由服务端拒绝写操作。
 */

/** 能力标识符。与服务端约定的协议值，改动即破坏兼容。 */
export const SESSION_CAPABILITY = Object.freeze({
  /** 看运行数据：指标、趋势图、实例指标详情。 */
  MetricsView: "metrics:view",
  /** 写规则：新建、修改、停用、发布、回滚。 */
  RulesWrite: "rules:write",
} as const);

/** 能力值联合。 */
export type SessionCapability = (typeof SESSION_CAPABILITY)[keyof typeof SESSION_CAPABILITY];

/** 全部能力。用于演示管理员与测试夹具。 */
export const ALL_CAPABILITIES: readonly SessionCapability[] = Object.freeze([
  SESSION_CAPABILITY.MetricsView,
  SESSION_CAPABILITY.RulesWrite,
]);

/** 当前会话是否持有某项能力。 */
export function hasCapability(
  granted: readonly SessionCapability[],
  required: SessionCapability,
): boolean {
  return granted.includes(required);
}
