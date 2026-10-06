/**
 * 「连接与采集」面板：顶部四个概览数字 + 连接与能力状态表。
 *
 * 中文
 * ----
 * 旧实现把这一整块连同表格数据一起写在 `SystemPage` 的 `tab === "连接与采集"`
 * 分支里，页面同时承担导航状态和业务渲染。拆出来后本面板只做一件事：把传入的
 * 读模型渲染成既有 class，DOM 结构与旧实现逐字一致。
 *
 * 底部提示里的「真正的健康检查、条件写入和回滚能力需由独立管理服务实现」是
 * 能力边界声明，不能因为示例状态是「可用」就删掉。
 */
import { InfoIcon as Info } from "@phosphor-icons/react";

import { DataTable as Table } from "../../../shared/ui/DataTable";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { NumberCard } from "../../../shared/ui/NumberCard";
import { Panel } from "../../../shared/ui/Panel";
import { Status } from "../../../shared/ui/Status";
import type { Navigate } from "../../../shared/types/dashboard";
import { ROUTE } from "../../../app/router/route.constants";
import {
  CONNECTION_HEADERS,
  CONNECTION_STATE_LABEL_KEY,
  connectionStatusTone,
  type ConnectionStatus,
  type ConnectionSummaryCard,
} from "../model/systemStatus";
import { useTranslator } from "../../../core/i18n/useTranslator";

export interface ConnectionPanelProps {
  readonly cards: readonly ConnectionSummaryCard[];
  readonly connections: readonly ConnectionStatus[];
  readonly navigate: Navigate;
}

export function ConnectionPanel({ cards, connections, navigate }: ConnectionPanelProps) {
  const t = useTranslator();
  return (
    <>
      <div className="number-grid">
        {cards.map((card) => (
          <NumberCard
            key={card.label}
            label={card.label}
            value={card.value}
            unit={card.unit}
            note={card.note}
            tone={card.tone}
          />
        ))}
      </div>
      <Panel
        title={t("system.connection.title")}
        subtitle={t("system.connection.subtitle")}
      >
        {/* 列头复制成可变数组是 `DataTable` 的 props 形状要求；model 侧保持只读。 */}
        <Table
          heads={CONNECTION_HEADERS.map((key) => t(key))}
          rows={connections.map((item) => (
            <tr key={item.name}>
              <td>
                <b>{item.name}</b>
              </td>
              <td>
                <Status tone={connectionStatusTone(item.state)}>
                  {t(CONNECTION_STATE_LABEL_KEY[item.state])}
                </Status>
              </td>
              <td>{item.latency}</td>
              <td>{item.scope}</td>
              <td>{item.purpose}</td>
              <td>{item.capability}</td>
            </tr>
          ))}
        />
      </Panel>
      <div className="bottom-note">
        <Info size={18} /> {t("system.connection.note")}
        <LinkButton onClick={() => navigate(ROUTE.Rules)}>
          {t("system.connection.action.openRules")}
        </LinkButton>
      </div>
    </>
  );
}
