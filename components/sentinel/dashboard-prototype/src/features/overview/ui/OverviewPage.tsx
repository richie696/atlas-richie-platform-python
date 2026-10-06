/**
 * 全局运行概览页面容器。
 *
 * 中文
 * ----
 * 页面只做三件事：取 feature 状态、组合区域、把用户动作映射为命令或导航。
 * 读模型在 `model/overview.ts`，演示数据在 `fixtures/`，作用域解析在
 * `useFleetOverview`，三个区域各自独立成组件。
 *
 * 旧实现把异常摘要、基础组件卡片、双图趋势和应用表全部内联在一个组件里：
 * 组件同时负责「当前作用域」「翻译」「四块区域的 JSX」，改趋势标题必须先读懂
 * 表格的列定义。
 *
 * 基础组件卡片留在本文件：它与异常摘要共享 `overview-top` 布局行，没有独立
 * 状态也没有第二个消费者，按 `REACT_PROJECT_SKELETON` §3「页面存在一个小型
 * 内部子组件时可同文件」处理。
 *
 * 已知口径限制（不是本次重构引入）：选单个应用时，表格收敛到该应用，**两张
 * 全局曲线不变**。`DASHBOARD_CONTROL_PLANE.md` §4.1 要求「全局曲线不能假装变成
 * 应用曲线」，所以这里保留大盘曲线而不是拿它冒充应用级数据；接入 Console API
 * 后由 `scope` 参数决定图表取数。
 */
import {
  CloudCheckIcon as CloudCheck,
  ShieldCheckIcon as ShieldCheck,
} from "@phosphor-icons/react";

import { Filters } from "../../../shared/ui/Filters";
import { Intro } from "../../../shared/ui/Intro";
import type { DashboardPageProps } from "../../../shared/types/dashboard";
import { createRuleTranslator } from "../../../ruleI18n";
import {
  APPLICATION_SUMMARIES,
  FLEET_ATTENTION,
  FLEET_TREND,
  INFRA_STATUS,
  seriesForRange,
} from "../fixtures/overviewFixtures";
import type { InfraStatus } from "../model/overview";
import { useFleetOverview } from "../state/useFleetOverview";
import { ApplicationTable } from "./ApplicationTable";
import { AttentionHero } from "./AttentionHero";
import { FleetTrendPanel } from "./FleetTrendPanel";

/** Fleet-level overview with drill-down links into application diagnostics. */
export function OverviewPage({
  navigate,
  appId,
  setAppId,
  range,
  setRange,
  locale,
}: DashboardPageProps) {
  const t = createRuleTranslator(locale);
  const overview = useFleetOverview({
    appId,
    range,
    applications: APPLICATION_SUMMARIES,
    attention: FLEET_ATTENTION,
    infra: INFRA_STATUS,
    navigate,
    setAppId,
  });
  // 演示窗口切片。接入 Console API 后由服务端按 window 查询，前端不再裁剪。
  const trend = seriesForRange(FLEET_TREND, range);
  return (
    <>
      <div className="overview-context">
        <Intro
          eyebrow="OPERATIONS / FLEET"
          title="全局运行概览"
          description="从应用视角了解整体流量与防护状况，快速定位需要关注的服务。"
        />
        <Filters
          appId={appId}
          setAppId={overview.selectApp}
          range={range}
          setRange={setRange}
          all
          applications={overview.appOptions}
          locale={locale}
        />
      </div>
      <div className="overview-top">
        <AttentionHero
          attention={overview.attention}
          appId={overview.drilldownAppId}
          navigate={navigate}
        />
        <InfraStatusCard items={overview.infra} />
      </div>
      <FleetTrendPanel trend={trend} window={overview.window} t={t} />
      <ApplicationTable
        applications={overview.applicationRows}
        attention={overview.attention}
        appId={overview.drilldownAppId}
        navigate={navigate}
      />
    </>
  );
}

/**
 * 一条基础组件状态的内容。
 *
 * 中文
 * ----
 * 两条数据形态不同：配置中心有延迟观测值，规则下发只有实例覆盖数与百分比。
 * model 用判别联合表达，这里的分支让「规则下发没有延迟」成为类型层面的事实，
 * 而不是渲染时补一个 `0 ms`。
 */
function infraItemBody(item: InfraStatus) {
  if (item.component === "config-center") {
    return (
      <>
        <CloudCheck size={30} color="#56d6a1" />
        <b>{item.name}</b>
        <small>
          {item.state} · {item.latencyMs} ms
        </small>
      </>
    );
  }
  return (
    <>
      <ShieldCheck size={30} color="#5badff" />
      <b>{item.name}</b>
      <small>
        {item.appliedInstances} / {item.totalInstances} · {item.coveragePercent}%
      </small>
    </>
  );
}

/**
 * 基础组件与规则下发状态卡片（`overview-top` 行的第二格）。
 */
function InfraStatusCard({ items }: { readonly items: readonly InfraStatus[] }) {
  return (
    <div className="infra-card">
      <div className="card-heading">
        基础组件与规则状态 <small>均为演示状态</small>
      </div>
      <div className="infra-items">
        {items.map((item) => (
          <div key={item.name}>{infraItemBody(item)}</div>
        ))}
      </div>
    </div>
  );
}
