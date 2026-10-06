/**
 * 应用与实例页面容器。
 *
 * 中文
 * ----
 * 页面只做三件事：取 feature 状态、组合区域、把用户动作映射为命令。矩阵与实例详情各自
 * 独立成面板，筛选与选中状态在 `useInstanceMatrix`，纯规则在 `model/instancePolicy`。
 *
 * 数据当前来自 `fixtures/`。接入 Console API 后由 `applications.gateway` 提供同样形状的
 * 应用目录与实例目录，本组件不需要改动。
 *
 * 文案现状：正文仍是硬编码中文。本轮不为此建 feature 级 i18n 层——在统一语言资源
 * （`core/i18n`，阶段 1.3）落地前再加一层本地字典只会产生第二套翻译入口。协议值
 * （scope、route）已经与文案分离，届时只替换文案取值。
 */
import { ArrowRightIcon as ArrowRight, InfoIcon as Info, WarningIcon as Warning } from "@phosphor-icons/react";

import { ActionButton } from "../../../shared/ui/ActionButton";
import { Filters } from "../../../shared/ui/Filters";
import { Intro } from "../../../shared/ui/Intro";
import { LinkButton } from "../../../shared/ui/LinkButton";
import type { DashboardPageProps } from "../../../shared/types/dashboard";
import { useTranslation } from "react-i18next";
import { ROUTE } from "../../../app/router/route.constants";
import {
  APPLICATION_FIXTURES,
  ORDER_INSTANCE_FIXTURES,
  readInstanceSeries,
} from "../fixtures/applicationsFixtures";
import { useInstanceMatrix } from "../state/useInstanceMatrix";
import { InstanceDetailPanel } from "./InstanceDetailPanel";
import { InstanceMatrixPanel } from "./InstanceMatrixPanel";

export function ApplicationsPage({
  navigate,
  appId,
  setAppId,
  range,
  setRange,
}: DashboardPageProps) {
  const { t } = useTranslation();
  const matrix = useInstanceMatrix({
    applications: APPLICATION_FIXTURES,
    instances: ORDER_INSTANCE_FIXTURES,
    appId,
    range,
    readSeries: readInstanceSeries,
  });
  const { app, hasInstanceSamples, instanceCount, anomalyCount } = matrix;

  // 应用目录为空属于装配错误（应用层保证至少一个应用），此时不渲染只剩空壳的页面。
  if (!app) return null;

  return (
    <>
      <div className="application-context">
        <Intro
          eyebrow="APPLICATIONS / INSTANCES"
          title={t("applications.intro.title")}
          description={t("applications.intro.description")}
        />
        <Filters
          appId={appId}
          setAppId={setAppId}
          range={range}
          setRange={setRange}
        applications={APPLICATION_FIXTURES}
        />
      </div>
      <div className="app-hero">
        <div className="alert-hero">
          <span className="alert-icon">
            <Warning size={27} weight="fill" />
          </span>
          <div>
            <span className="eyebrow">SELECTED APPLICATION</span>
            <h2>
              {app.label} ·{" "}
              {hasInstanceSamples
                ? t("applications.summary.anomalyCount", { instanceCount, anomalyCount })
                : app.stateLabel}
            </h2>
            <p>
              {hasInstanceSamples
                ? t("applications.summary.advice")
                : t("applications.summary.noSamples")}
            </p>
          </div>
          <ActionButton
            className="primary-button"
            type="button"
            onClick={() => matrix.setAnomaliesOnly(true)}
          >
            {t("applications.action.viewAnomalies")} <ArrowRight size={16} />
          </ActionButton>
        </div>
        <div className="rule-card">
          <span>
            {t("applications.card.ruleVersion")} <b>{app.version}</b>
          </span>
          <span>
            {t("applications.card.configProvider")} <b>{app.provider}</b>
          </span>
          <span>
            {t("applications.card.effective")} {" "}
            <b>{t("applications.card.instances", { running: app.running, total: app.total })}</b>
          </span>
          <LinkButton onClick={() => navigate(ROUTE.Rules)}>
            {t("applications.action.viewRuleDetail")}
          </LinkButton>
        </div>
      </div>
      {!hasInstanceSamples && (
        <div className="inline-note">
          <Info size={16} /> {t("applications.note.matrixScope")}
        </div>
      )}
      <div className="instance-layout">
        <InstanceMatrixPanel
          hosts={matrix.hosts}
          instanceCount={instanceCount}
          anomaliesOnly={matrix.anomaliesOnly}
          selectedId={matrix.selectedId}
          onAnomaliesOnlyChange={matrix.setAnomaliesOnly}
          onSelectInstance={matrix.setSelectedId}
        />
        <InstanceDetailPanel
          instance={matrix.selected}
          scope={matrix.scope}
          series={matrix.series}
          onScopeChange={matrix.setScope}
          onViewRules={() => navigate(ROUTE.Rules)}
        />
      </div>
    </>
  );
}
