/**
 * 网关装配：页面从这里取实现，而不是直接 import 单例。
 *
 * 中文
 * ----
 * 页面 import 单例网关意味着**测试无法替换实现**——想验证「无权时显示什么」
 * 就得改源码。因此实现放在 Context 里，默认值是 `fixtureGateway`。
 *
 * 装配处换成 `HttpConsoleGateway` 时，11 个页面一行都不用改：
 *
 * ```tsx
 * <ConsoleGatewayProvider gateway={new HttpConsoleGateway({ baseUrl })}>
 * ```
 *
 * ## 现在提供不了什么
 *
 * 只有**同步快照**接上了 Context。异步方法与错误分支仍是零覆盖的死代码：
 * 页面还没经历「数据未到」与「无权」两种状态。在控制面服务到位、页面真正开始
 * await 之前，不假装它们已经工作。
 */
import { createContext, useContext, type ReactNode } from "react";

import type { FixtureGateway } from "./fixtureGateway";

type AnyGateway = FixtureGateway;

const GatewayContext = createContext<AnyGateway | null>(null);

export interface ConsoleGatewayProviderProps {
  readonly gateway: AnyGateway;
  readonly children: ReactNode;
}

/** 装配网关。控制面就绪时把 `gateway` 换成 `HttpConsoleGateway`。 */
export function ConsoleGatewayProvider({
  gateway,
  children,
}: ConsoleGatewayProviderProps) {
  return <GatewayContext.Provider value={gateway}>{children}</GatewayContext.Provider>;
}

/**
 * 当前网关。
 *
 * Provider 缺失时抛错而非回落到单例：静默回落会让「测试里注入的假网关没生效」
 * 表现为「页面行为和 fixture 一样」，很难察觉。
 */
export function useConsoleGateway(): AnyGateway {
  const gateway = useContext(GatewayContext);
  if (!gateway) {
    throw new Error("useConsoleGateway 必须在 <ConsoleGatewayProvider> 内使用");
  }
  return gateway;
}