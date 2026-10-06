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
  connectionStatusTone,
  type ConnectionStatus,
  type ConnectionSummaryCard,
} from "../model/systemStatus";

export interface ConnectionPanelProps {
  readonly cards: readonly ConnectionSummaryCard[];
  readonly connections: readonly ConnectionStatus[];
  readonly navigate: Navigate;
}

export function ConnectionPanel({ cards, connections, navigate }: ConnectionPanelProps) {
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
        title="连接与能力状态"
        subtitle="配置中心读写、指标与事件上报是不同链路；下列状态均为示例。"
      >
        {/* 列头复制成可变数组是 `DataTable` 的 props 形状要求；model 侧保持只读。 */}
        <Table
          heads={[...CONNECTION_HEADERS]}
          rows={connections.map((item) => (
            <tr key={item.name}>
              <td>
                <b>{item.name}</b>
              </td>
              <td>
                <Status tone={connectionStatusTone(item.state)}>{item.state}</Status>
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
        <Info size={18} /> 真正的 Nacos / Consul
        健康检查、条件写入和回滚能力需由独立管理服务实现。
        <LinkButton onClick={() => navigate(ROUTE.Rules)}>
          查看规则工作台
        </LinkButton>
      </div>
    </>
  );
}
