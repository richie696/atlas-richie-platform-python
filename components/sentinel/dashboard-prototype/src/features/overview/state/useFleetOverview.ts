/**
 * 总览页的作用域解析与下钻命令。
 *
 * 中文
 * ----
 * 旧实现在 `OverviewPage` 组件体内写了三段彼此相关的派生逻辑：
 *
 * 1. `appId === ALL_APPLICATIONS ? APPLICATIONS : filter(...)` —— 哪些行该出现；
 * 2. 筛选下拉的候选集等于应用目录；
 * 3. 「选全部应用就改本机状态，选具体应用就跳到应用页」——因为应用页是
 *    `single` 粒度路由，不接受 `ALL_APPLICATIONS`。
 *
 * 三者是同一个决定的三个面：总览处于哪个**应用作用域**。拆成组件里的散表达式后，
 * 「跳转」这条路由约束没有名字，也不该由展示组件来守。现在它们收在一个 Hook 里：
 *
 * - Hook 不发请求、不做网络订阅，只做纯派生与命令映射（`REACT_CODING_STANDARD` §2）。
 * - 派生值在 render 期直接算，不进 `useState`，因此不存在「筛选变了但派生值还是旧的」
 *   这类不同步。
 * - 接入 Console API 后，应用目录与趋势序列改由 `overview.gateway` 提供，
 *   本 Hook 的返回形状与命令签名保持不变，页面不需要跟着改。
 */
import { useCallback, useMemo } from "react";

import { ALL_APPLICATIONS, ROUTE, type TimeRangeId } from "../../../app/router/route.constants";
import type { Navigate } from "../../../shared/types/dashboard";
import {
  attentionDrilldownAppId,
  selectApplicationScope,
  type ApplicationSummary,
  type FleetAttention,
  type InfraStatus,
} from "../model/overview";

export interface UseFleetOverviewOptions {
  /** 当前应用作用域。`ALL_APPLICATIONS` 表示大盘。 */
  readonly appId: string;
  /** 当前时间窗口。总览只按窗口取图，不按窗口改表格。 */
  readonly range: TimeRangeId;
  readonly applications: readonly ApplicationSummary[];
  readonly attention: FleetAttention;
  readonly infra: readonly InfraStatus[];
  readonly navigate: Navigate;
  readonly setAppId: (appId: string) => void;
}

export interface FleetOverview {
  readonly attention: FleetAttention;
  readonly infra: readonly InfraStatus[];
  /** 当前作用域下要显示的应用行。 */
  readonly applicationRows: readonly ApplicationSummary[];
  /** 筛选下拉的候选集。 */
  readonly appOptions: readonly { readonly id: string; readonly label: string }[];
  /** 当前时间窗口。趋势面板据此决定「示例窗口」还是发布前后对比。 */
  readonly window: TimeRangeId;
  /** 异常摘要与表格区共用的下钻目标应用 id。 */
  readonly drilldownAppId: string;
  /** 应用作用域选择命令：留在总览或跳转到应用页。 */
  selectApp: (id: string) => void;
}

export function useFleetOverview(options: UseFleetOverviewOptions): FleetOverview {
  const { appId, range, applications, attention, infra, navigate, setAppId } = options;

  const applicationRows = useMemo(
    () => selectApplicationScope(applications, appId, ALL_APPLICATIONS),
    [appId, applications],
  );

  const appOptions = useMemo(
    () => applications.map((application) => ({ id: application.id, label: application.name })),
    [applications],
  );

  const selectApp = useCallback(
    (id: string) => {
      // 应用页是 `single` 粒度路由：选定具体应用就是一次下钻，而不是本页筛选。
      if (id === ALL_APPLICATIONS) {
        setAppId(id);
        return;
      }
      navigate(ROUTE.Applications, { appId: id });
    },
    [navigate, setAppId],
  );

  return {
    attention,
    infra,
    applicationRows,
    appOptions,
    window: range,
    drilldownAppId: attentionDrilldownAppId(attention),
    selectApp,
  };
}
