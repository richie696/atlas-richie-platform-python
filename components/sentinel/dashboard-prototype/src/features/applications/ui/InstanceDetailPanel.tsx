/**
 * 选中实例的详情面板：采集层级切换 + 双轴指标图 + 当前流控规则入口。
 *
 * 中文
 * ----
 * 纯展示 + 用户命令：接收选中实例、层级状态和已算好的序列。层级是否已接入由
 * `isScopeSupported` 决定，宿主机层与进程层显示「未接入」，不复用容器曲线。
 *
 * 旧实现把这段和矩阵、筛选、hero 写在同一个组件里，于是「容器是唯一有数据的层级」这条
 * 产品硬要求（`DASHBOARD_CONTROL_PLANE.md` §4）只能以 `scope === "容器"` 的形式散落在
 * 两处 JSX 里。
 */
import { InfoIcon as Info } from "@phosphor-icons/react";

import { ActionButton } from "../../../shared/ui/ActionButton";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { Panel } from "../../../shared/ui/Panel";
import { Status } from "../../../shared/ui/Status";
import { TrendChart as Trend } from "../../../shared/ui/charts/TrendChart";
import type { MetricPoint } from "../../../shared/types/dashboard";
import { INSTANCE_SCOPES, type InstanceRecord, type InstanceScope } from "../model/instance";
import { useTranslator } from "../../../core/i18n/useTranslator";
import type { Translate } from "../../../core/i18n/types";
import { isScopeSupported } from "../model/instancePolicy";

/**
 * 采集层级的展示标签。
 *
 * 文案属于 UI 层，不进协议常量。阶段 1.3 建立统一语言资源后，这里由 `t()` 取代；
 * 层级本身已经是协议值，换语言不会再影响状态判断。
 */
const SCOPE_LABEL_KEY: Readonly<Record<InstanceScope, string>> = Object.freeze({
  host: "applications.scope.host",
  container: "applications.scope.container",
  process: "applications.scope.process",
});

/**
 * 状态行文案：已接入的层级标明数据性质，未接入的层级说明缺什么。
 *
 * 层级名先翻译再拼句子，而不是把整句当一个键——「{scope}指标 · 演示数据」这类
 * 模板里嵌语言片段，按整句建键会让每种语言都要复制一遍层级名的翻译。
 */
function scopeStatusText(scope: InstanceScope, t: Translate): string {
  return isScopeSupported(scope)
    ? t("applications.metrics.demo", { scope: t(SCOPE_LABEL_KEY[scope]) })
    : t("applications.metrics.empty", { scope: t(SCOPE_LABEL_KEY[scope]) });
}

export interface InstanceDetailPanelProps {
  /** 选中的实例；`null` 表示实例目录为空。 */
  readonly instance: InstanceRecord | null;
  readonly scope: InstanceScope;
  /** 选中实例在当前时间窗口的序列。层级未接入时不渲染图表，因此不会用到。 */
  readonly series: readonly MetricPoint[];
  onScopeChange: (scope: InstanceScope) => void;
  onViewRules: () => void;
}

export function InstanceDetailPanel({
  instance,
  scope,
  series,
  onScopeChange,
  onViewRules,
}: InstanceDetailPanelProps) {
  const t = useTranslator();
  if (!instance) {
    return (
      <Panel title={t("applications.detail.title")} subtitle={t("applications.detail.emptySubtitle")}>
        <div className="empty">{t("applications.detail.emptyBody")}</div>
      </Panel>
    );
  }

  return (
    <Panel
      title={instance.id}
      subtitle={t("applications.detail.subtitle", { host: instance.host, id: instance.id })}
      action={
        <div className="segments">
          {INSTANCE_SCOPES.map((name) => (
            <ActionButton
              type="button"
              key={name}
              className={scope === name ? "active" : ""}
              onClick={() => onScopeChange(name)}
            >
              {t(SCOPE_LABEL_KEY[name])}
            </ActionButton>
          ))}
        </div>
      }
      className="detail-panel"
    >
      <div className="detail-status">
        <Status tone={instance.status}>{instance.statusLabel}</Status>
        <span>{scopeStatusText(scope, t)}</span>
      </div>
      {isScopeSupported(scope) ? (
        <>
          <h3>
            {t("applications.detail.usage")} {" "}
            <small>
              <i className="dot-blue" /> CPU　
              <i className="dot-amber" /> {t("applications.detail.memory")}
            </small>
          </h3>
          <Trend
            data={series}
            metric="cpu"
            second="memory"
            unit="%"
            domain={[0, 100]}
            height={212}
          />
          <h3>
            {t("applications.detail.http")}
            <small>
              <i className="dot-blue" /> QPS　
              <i className="dot-red" /> {t("applications.detail.blockedRate")}
            </small>
          </h3>
          <Trend
            data={series}
            metric="qps"
            second="blocked"
            secondColor="danger"
            secondAxis
            secondUnit="%"
            height={182}
          />
        </>
      ) : (
        <div className="scope-empty">
          <Info size={20} />{" "}
          {t("applications.detail.scopeNote")}
        </div>
      )}
      <div className="detail-rule">
        <b>{t("applications.detail.currentRule")}</b>
        <span>{t("applications.detail.ruleThreshold")}</span>
        <LinkButton onClick={onViewRules}>{t("applications.action.viewRules")}</LinkButton>
      </div>
    </Panel>
  );
}
