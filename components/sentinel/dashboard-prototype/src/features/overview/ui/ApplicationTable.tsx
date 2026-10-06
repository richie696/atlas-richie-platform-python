/**
 * 应用运行状态表。
 *
 * 中文
 * ----
 * 表格行是**按应用聚合**的关键指标，不是单实例数字：QPS 与 RT 是 HTTP 层口径，
 * 拦截率是 Sentinel 拒绝占比。行 key 用应用 id，不用数组下标。
 *
 * 「没有实例级数据时显示缺口，不能用另一应用的行填充」：本表只渲染
 * `useFleetOverview` 解析出的当前作用域行，选中不存在的应用时表格为空而不是
 * 悄悄回退到全集。
 */
import { DataTable as Table } from "../../../shared/ui/DataTable";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { Panel } from "../../../shared/ui/Panel";
import { Status } from "../../../shared/ui/Status";
import { ROUTE } from "../../../app/router/route.constants";
import { numberText } from "../format/numberText";
import {
  APPLICATION_HEALTH_LABEL_KEY,
  APPLICATION_TABLE_HEADERS,
  CELL_ALERT_THRESHOLDS,
  type ApplicationSummary,
  type FleetAttention,
} from "../model/overview";
import { useTranslation } from "react-i18next";
import type { Navigate } from "../../../shared/types/dashboard";

export interface ApplicationTableProps {
  readonly applications: readonly ApplicationSummary[];
  /** 表格下方的「共 N 个应用」口径来自异常摘要，与标题同源。 */
  readonly attention: FleetAttention;
  /** 表格区右上角入口的下钻目标应用 id。 */
  readonly appId: string;
  readonly navigate: Navigate;
}

export function ApplicationTable({
  applications,
  attention,
  appId,
  navigate,
}: ApplicationTableProps) {
  const { t } = useTranslation();
  return (
    <Panel
      title={t("overview.table.title")}
      subtitle={t("overview.table.subtitle")}
      action={
        <LinkButton onClick={() => navigate(ROUTE.Applications, { appId })}>
          {t("overview.table.viewAll")}
        </LinkButton>
      }
    >
      <Table
        heads={APPLICATION_TABLE_HEADERS.map((key) => t(key))}
        rows={applications.map((app) => (
          <tr key={app.id}>
            <td>
              <LinkButton onClick={() => navigate(ROUTE.Applications, { appId: app.id })}>
                {app.name}
              </LinkButton>
            </td>
            <td>
              <Status tone={app.health}>{t(APPLICATION_HEALTH_LABEL_KEY[app.health])}</Status>
            </td>
            <td>
              {app.runningInstances} / {app.totalInstances}
            </td>
            <td className={app.cpuPercent > CELL_ALERT_THRESHOLDS.cpuPercent ? "red" : ""}>
              {app.cpuPercent}%
            </td>
            <td>{app.memoryPercent}%</td>
            <td>{numberText(app.httpQps)}</td>
            <td className={app.rtP95Ms > CELL_ALERT_THRESHOLDS.rtP95Ms ? "red" : ""}>
              {app.rtP95Ms} ms
            </td>
            <td className={app.blockedRatePercent > CELL_ALERT_THRESHOLDS.blockedRatePercent ? "red" : ""}>
              {app.blockedRatePercent}%
            </td>
            <td>{app.ruleVersion}</td>
            <td>
              <LinkButton onClick={() => navigate(ROUTE.Applications, { appId: app.id })}>
                {t("overview.table.detail")}
              </LinkButton>
            </td>
          </tr>
        ))}
      />
      <p className="table-note">
        {t("overview.table.note", {
          shown: applications.length,
          total: attention.totalApps,
        })}
      </p>
    </Panel>
  );
}
