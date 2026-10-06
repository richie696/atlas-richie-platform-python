/**
 * 应用作用域目录（装配层）。
 *
 * 中文
 * ----
 * 应用 id 是**整个控制台共用的导航状态**：它出现在 URL 里，跨六个页面保持，
 * 并决定后端查询的作用域。因此「有哪些应用」属于装配层的关注点，而不是任何单个
 * feature 的私有数据——放在某个 feature 里会让其他 feature 反向依赖它。
 *
 * 用途只有一处：`resolveAppIdForRoute` 需要在进入 `single` 粒度路由
 * （应用与实例、规则）时，把「全部应用」收敛成一个真实应用。筛选下拉的候选项
 * 仍由各 feature 按自己的读模型提供（见 `Filters` 的 `applications` prop），
 * 两者不必是同一份列表。
 *
 * 接入 Console API 后本模块整体删除，改由 applications feature 的 gateway 提供
 * `ApplicationSummary[]`，装配层改为订阅。
 */

/** 应用作用域中的一条记录。 */
export interface ApplicationScope {
  readonly id: string;
  readonly label: string;
}

/**
 * 演示用应用目录。
 *
 * 这是**示例数据**，与各 feature fixture 中的演示数据同源但用途不同：这里只回答
 * 「路由作用域能否收敛到一个真实应用」。
 */
export const APPLICATION_SCOPES: readonly ApplicationScope[] = Object.freeze([
  Object.freeze({ id: "order-service", label: "order-service" }),
  Object.freeze({ id: "payment-service", label: "payment-service" }),
  Object.freeze({ id: "user-service", label: "user-service" }),
]);

/** 目录中的全部应用 id，供 `resolveAppIdForRoute` 做回退选择。 */
export const APPLICATION_SCOPE_IDS: readonly string[] = Object.freeze(
  APPLICATION_SCOPES.map((item) => item.id),
);
