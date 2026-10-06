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
import { useTranslation } from "react-i18next";
import { useConsoleGateway } from "../../../core/api/GatewayProvider";
import type { InfraStatus } from "../model/overview";
import { INFRA_STATE_LABEL_KEY } from "../model/overview";
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
}: DashboardPageProps) {
  const { t } = useTranslation();
  // 数据从 gateway 取，不再直接 import fixtures：本页对「数据从哪来」无感知，
  // 接真实控制面时只换 `core/api` 的实现。渲染时机不变（同步快照），因此首屏
  // 与迁移前逐像素相同。
  const {applications, attention, infra, trend: trendSource, seriesForRange: sliceByRange} = useConsoleGateway().readFleetOverviewSync();
  const overview = useFleetOverview({
    appId,
    range,
    applications,
    attention,
    infra,
    navigate,
    setAppId,
  });
  // 演示窗口切片。接入 Console API 后由服务端按 window 查询，前端不再裁剪。
  const trend = sliceByRange(trendSource, range);
  return (
    <>
      <div className="overview-context">
        <Intro
          eyebrow="OPERATIONS / FLEET"
          title={t("overview.intro.title")}
          description={t("overview.intro.description")}
        />
        <Filters
          appId={appId}
          setAppId={overview.selectApp}
          range={range}
          setRange={setRange}
          all
          applications={overview.appOptions}
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
      <FleetTrendPanel trend={trend} window={overview.window} />
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
 *
 * 展示名也随分支走：`config-center` 渲染产品名（数据），`rule-delivery` 渲染语言键
 * （界面文案）。共用一条路径会让其中一个永远不跟随语言切换。
 */
function infraItemBody(item: InfraStatus) {
  const { t } = useTranslation();
  if (item.component === "config-center") {
    return (
      <>
        <CloudCheck size={30} color="#56d6a1" />
        <b>{item.name}</b>
        <small>
          {t(INFRA_STATE_LABEL_KEY[item.state])} · {item.latencyMs} ms
        </small>
      </>
    );
  }
  return (
    <>
      <ShieldCheck size={30} color="#5badff" />
      <b>{t(item.nameKey)}</b>
      <small>
        {item.appliedInstances} / {item.totalInstances} · {item.coveragePercent}%
      </small>
    </>
  );
}

/**
 * 列表 key。判别联合的两个分支没有共同的身份字段，所以按分支各取一个，
 * 并带上 component 前缀避免不同分支的取值撞车。
 */
function infraItemKey(item: InfraStatus): string {
  return item.component === "config-center" ? `cc:${item.name}` : `rd:${item.nameKey}`;
}

/**
 * 基础组件与规则下发状态卡片（`overview-top` 行的第二格）。
 */
function InfraStatusCard({ items }: { readonly items: readonly InfraStatus[] }) {
  const { t } = useTranslation();
  return (
    <div className="infra-card">
      <div className="card-heading">
        {t("overview.infra.title")} <small>{t("overview.infra.demoOnly")}</small>
      </div>
      <div className="infra-items">
        {items.map((item) => (
          <div key={infraItemKey(item)}>{infraItemBody(item)}</div>
        ))}
      </div>
    </div>
  );
}
