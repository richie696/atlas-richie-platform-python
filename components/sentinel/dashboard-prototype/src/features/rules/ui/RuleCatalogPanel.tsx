/**
 * 规则目录面板。
 *
 * 中文
 * ----
 * 纯展示 + 用户命令：接收已筛选的目录和当前选中项，把点击映射为 `onSelect`。
 * 筛选与状态归属在 `useRuleWorkbench`，本组件不持有任何业务状态。
 */
import { ActionButton } from "../../../shared/ui/ActionButton";
import { DataTable as Table } from "../../../shared/ui/DataTable";
import { Panel } from "../../../shared/ui/Panel";
import { Select } from "../../../shared/ui/Select";
import { Status } from "../../../shared/ui/Status";
import { TextField } from "../../../shared/ui/TextField";
import { RULE_KIND_ALL, RULE_SOURCE, type RuleKind, type RuleKindFilter } from "../model/ruleKinds";
import type { RuleTypeCopyMap } from "../model/ruleMessages";
import type { RuleWorkbenchEntry } from "../state/useRuleWorkbench";

export interface RuleCatalogPanelProps {
  readonly entries: readonly RuleWorkbenchEntry[];
  readonly selectedId: string;
  readonly search: string;
  readonly kindFilter: RuleKindFilter;
  readonly types: RuleTypeCopyMap;
  /** 面板副标题模板，接收目录条数。 */
  readonly detailLabel: string;
  readonly searchLabel: string;
  readonly allTypesLabel: string;
  readonly columnHeaders: readonly string[];
  readonly activeLabel: string;
  readonly emptyLabel: string;
  readonly t: (path: string, values?: Record<string, string | number>) => string;
  onSearch: (value: string) => void;
  onKindFilter: (value: RuleKindFilter) => void;
  onSelect: (entry: RuleWorkbenchEntry) => void;
}

export function RuleCatalogPanel({
  entries,
  selectedId,
  search,
  kindFilter,
  types,
  detailLabel,
  searchLabel,
  allTypesLabel,
  columnHeaders,
  activeLabel,
  emptyLabel,
  t,
  onSearch,
  onKindFilter,
  onSelect,
}: RuleCatalogPanelProps) {
  return (
    <Panel
      title={t("rules.catalog")}
      subtitle={t(detailLabel, { count: entries.length })}
      action={
        <div className="rule-filters">
          <TextField
            label={searchLabel}
            isLabelHidden
            placeholder={searchLabel}
            value={search}
            onChange={onSearch}
            className="search"
          />
          <Select
            label={allTypesLabel}
            isLabelHidden
            value={kindFilter}
            onChange={onKindFilter}
            options={[
              { value: RULE_KIND_ALL, label: allTypesLabel },
              ...(Object.keys(types) as RuleKind[]).map((kind) => ({
                value: kind,
                label: types[kind].label,
              })),
            ]}
          />
        </div>
      }
    >
      <Table
        heads={[...columnHeaders]}
        rows={entries.map((entry) => (
          <tr
            key={entry.id}
            className={selectedId === entry.id ? "selected" : ""}
            onClick={() => onSelect(entry)}
          >
            <td>
              <ActionButton
                type="button"
                className="resource-button"
                onClick={() => onSelect(entry)}
              >
                {entry.resource}
                <small>{types[entry.ruleType].label}</small>
              </ActionButton>
            </td>
            <td>{entry.strategy}</td>
            <td>{entry.threshold}</td>
            <td>
              <Status tone={entry.provider === RULE_SOURCE.Nacos ? "blue" : "purple"}>
                {entry.provider}
              </Status>
            </td>
            <td>
              <Status>{activeLabel}</Status>
            </td>
          </tr>
        ))}
      />
      {entries.length === 0 && <div className="empty">{emptyLabel}</div>}
    </Panel>
  );
}
