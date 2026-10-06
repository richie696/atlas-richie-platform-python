/**
 * SystemRule 表单。
 *
 * 中文
 * ----
 * 该类型没有 resource：它保护的是应用整体入口。五个阈值各自独立，未启用时序列化为
 * `DISABLED_SYSTEM_THRESHOLD`（-1），这是 Sentinel 的「不生效」语义，不是「阈值 0」。
 * 因此表单把 -1 显示为空格，而不是显示 -1 或 0。
 *
 * `highestCpuUsage` 取值区间是 0..1，不是百分数；界面也不展示百分号。
 */
import { RuleInput } from "../fields/RuleFields";
import type { SystemRuleDraft } from "../../model/ruleDraft";
import { DISABLED_SYSTEM_THRESHOLD } from "../../model/ruleKinds";
import type { RuleFieldCopy, RuleTypeCopy } from "../../model/ruleMessages";

/** 五个系统阈值字段，与 `DASHBOARD_CONTROL_PLANE.md` §4.3 SystemRule 一致。 */
const SYSTEM_FIELDS = [
  { key: "highestSystemLoad", field: "systemLoad" },
  { key: "avgRt", field: "averageRt" },
  { key: "maxThread", field: "maximumThreads" },
  { key: "qps", field: "entranceQps" },
  { key: "highestCpuUsage", field: "cpuUsage" },
] as const satisfies readonly { key: keyof SystemRuleDraft; field: keyof RuleFieldCopy }[];

export interface SystemRuleFormProps {
  readonly draft: SystemRuleDraft;
  readonly disabled: boolean;
  readonly typeCopy: RuleTypeCopy;
  readonly fields: RuleFieldCopy;
  /** 「留空会序列化为 -1」的说明。 */
  readonly disabledNote: string;
  readonly onChange: (next: SystemRuleDraft) => void;
}

/** 把协议值转成表单显示值：未启用显示为空。 */
function displayValue(value: SystemRuleDraft[keyof SystemRuleDraft]): number | string {
  return Number(value) === DISABLED_SYSTEM_THRESHOLD ? "" : value;
}

export function SystemRuleForm({
  draft,
  disabled,
  typeCopy,
  fields,
  disabledNote,
  onChange,
}: SystemRuleFormProps) {
  const update = (key: keyof SystemRuleDraft, value: number | string) =>
    onChange({ ...draft, [key]: value });

  return (
    <div className="rule-form">
      <p className="form-description">
        {typeCopy.description} {disabledNote}
      </p>
      <div className="rule-form-grid">
        {SYSTEM_FIELDS.map(({ key, field }) => (
          <RuleInput
            key={key}
            label={fields[field].label}
            hint={fields[field].hint}
            value={displayValue(draft[key])}
            onChange={(value) =>
              update(key, value === "" ? DISABLED_SYSTEM_THRESHOLD : Number(value))
            }
            disabled={disabled}
            numeric
          />
        ))}
      </div>
    </div>
  );
}
