/**
 * 实例健康矩阵面板。
 *
 * 中文
 * ----
 * 纯展示 + 用户命令：接收已分组的行、当前选中项和筛选开关，把点击映射为
 * `onSelectInstance`。筛选与选中状态归属 `useInstanceMatrix`，本面板不持有业务状态。
 *
 * 局部组件 `Usage`（使用率条）与 `HostRows`（一个宿主机分组的表头行 + 实例行）留在本
 * 文件：它们只在矩阵内部使用、没有任何第二个消费者，且与矩阵共享同一套列定义。旧实现
 * 把它们定义在页面容器文件里，于是「矩阵长什么样」的知识散落在页面层。
 */
import { useState } from "react";
import { CaretDownIcon as CaretDown } from "@phosphor-icons/react";

import { ActionButton } from "../../../shared/ui/ActionButton";
import { CheckboxField } from "../../../shared/ui/CheckboxField";
import { DataTable as Table } from "../../../shared/ui/DataTable";
import { Panel } from "../../../shared/ui/Panel";
import { Status } from "../../../shared/ui/Status";
import { formatInstanceNumber } from "../model/instanceFormat";
import { isBlockingRateAlert, isUnderResourcePressure } from "../model/instancePolicy";
import type { HostGroup, InstanceRecord } from "../model/instance";

/** 列顺序即渲染顺序，也决定宿主机表头行的 `colSpan`。 */
const INSTANCE_MATRIX_HEADS = [
  "实例 / 宿主机",
  "状态",
  "容器 CPU",
  "容器内存",
  "HTTP QPS",
  "RT p95",
  "请求拦截率",
  "规则版本",
] as const;

export interface InstanceMatrixPanelProps {
  /** 已按宿主机分组的当前可见行。 */
  readonly hosts: readonly HostGroup[];
  /** 实例目录总数（不随「仅看异常」变化）。 */
  readonly instanceCount: number;
  readonly anomaliesOnly: boolean;
  readonly selectedId: string;
  onAnomaliesOnlyChange: (value: boolean) => void;
  onSelectInstance: (id: string) => void;
}

/** 资源使用率条。`tone` 决定颜色语义，宽度由调用方给的百分数决定。 */
function Usage({ value, tone = "blue" }: { value: number; tone?: string }) {
  return <span className="usage"><i className={`usage-${tone}`} style={{ width: `${value}%` }} /></span>;
}

/**
 * 一个宿主机分组：一条可折叠的宿主机表头行 + 该宿主机下的实例行。
 *
 * 展开/折叠是纯局部交互状态，留在最近的组件里——它不属于实例矩阵的业务状态，也不该
 * 提升到页面或 Hook。默认值全开，与旧实现一致。
 */
function HostRows({
  host,
  rows,
  selectedId,
  setSelectedId,
}: {
  host: string;
  rows: readonly InstanceRecord[];
  selectedId: string;
  setSelectedId: (id: string) => void;
}) {
  const [open, setOpen] = useState(true);
  return <>
    <tr className="host-row"><td colSpan={INSTANCE_MATRIX_HEADS.length}><ActionButton type="button" onClick={() => setOpen(!open)}><CaretDown size={14} className={open ? "" : "rotated"} /> {host} <span>({rows.length} 个实例)</span></ActionButton></td></tr>
    {open && rows.map((row) => <tr key={row.id} className={`instance-row ${selectedId === row.id ? "selected" : ""} ${row.status !== "healthy" ? row.status : ""}`} onClick={() => setSelectedId(row.id)}>
      <td><ActionButton type="button" onClick={() => setSelectedId(row.id)}>{row.id}</ActionButton></td>
      <td><Status tone={row.status}>{row.statusLabel}</Status></td>
      <td>{row.cpu}% <Usage value={row.cpu} tone={isUnderResourcePressure(row.cpu) ? "red" : "blue"} /></td>
      <td>{row.memory}% <Usage value={row.memory} tone={isUnderResourcePressure(row.memory) ? "amber" : "blue"} /></td>
      <td>{formatInstanceNumber(row.qps)}</td><td>{row.rt} ms</td>
      <td className={isBlockingRateAlert(row.blocked) ? "red" : ""}>{row.blocked.toFixed(2)}%</td><td>{row.version}</td>
    </tr>)}
  </>;
}

export function InstanceMatrixPanel({
  hosts,
  instanceCount,
  anomaliesOnly,
  selectedId,
  onAnomaliesOnlyChange,
  onSelectInstance,
}: InstanceMatrixPanelProps) {
  return (
    <Panel
      title="实例健康矩阵"
      subtitle={`共 ${instanceCount} 个示例实例，按宿主机分组 · ${anomaliesOnly ? "仅看异常" : "全部"}`}
      action={
        <CheckboxField label="仅看异常" checked={anomaliesOnly} onChange={onAnomaliesOnlyChange} className="checkbox" />
      }
      className="instance-panel"
    >
      <Table
        heads={[...INSTANCE_MATRIX_HEADS]}
        rows={hosts.map((group) => (
          <HostRows
            key={group.host}
            host={group.host}
            rows={group.instances}
            selectedId={selectedId}
            setSelectedId={onSelectInstance}
          />
        ))}
        className="instances-table"
      />
    </Panel>
  );
}
