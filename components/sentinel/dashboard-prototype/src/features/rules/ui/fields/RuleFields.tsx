/**
 * 规则表单的三个基础字段包装。
 *
 * 中文
 * ----
 * 旧实现在 `RuleEditor.tsx` 内部定义了同名的三个局部组件：520 行的文件里混着
 * 字段包装、五类分支表单和集群流控子表单。这里把它们拆到独立文件，让每个文件的
 * 变化原因单一：字段包装只关心「用什么控件承载一个值」。
 *
 * 三个组件都**不引入新 DOM**：渲染的控件与类名与原实现逐字一致，视觉基线不变。
 */
import { CheckboxField } from "../../../../shared/ui/CheckboxField";
import { NumberField } from "../../../../shared/ui/NumberField";
import { Select } from "../../../../shared/ui/Select";
import { TextField } from "../../../../shared/ui/TextField";
import type { RuleOption } from "../../model/ruleOptions";

/** 文本 / 数字输入的统一包装。`numeric` 决定底层控件。 */
export interface RuleInputProps {
  readonly label: string;
  readonly hint?: string;
  readonly value: string | number | undefined;
  readonly onChange: (value: string) => void;
  readonly disabled?: boolean;
  readonly numeric?: boolean;
}

export function RuleInput({
  label,
  hint,
  value,
  onChange,
  disabled,
  numeric = false,
}: RuleInputProps) {
  return numeric ? (
    <NumberField label={label} hint={hint} value={value} onChange={onChange} disabled={disabled} />
  ) : (
    <TextField
      label={label}
      hint={hint}
      value={String(value ?? "")}
      onChange={onChange}
      disabled={disabled}
    />
  );
}

/** 枚举下拉。协议值是 number，控件值域是 string，此处一次性收窄。 */
export interface RuleSelectProps {
  readonly label: string;
  readonly hint?: string;
  readonly value: number;
  readonly options: readonly RuleOption[];
  readonly onChange: (value: number) => void;
  readonly disabled?: boolean;
}

export function RuleSelect({ label, hint, value, options, onChange, disabled }: RuleSelectProps) {
  return (
    <Select
      label={label}
      hint={hint}
      value={String(value)}
      onChange={(next) => onChange(Number(next))}
      options={options.map((option) => ({ value: option.value, label: option.label }))}
      disabled={disabled}
    />
  );
}

/** 布尔开关。集群流控与本地兜底共用。 */
export interface RuleToggleProps {
  readonly label: string;
  readonly hint?: string;
  readonly checked: boolean;
  readonly onChange: (checked: boolean) => void;
  readonly disabled?: boolean;
}

export function RuleToggle({ label, hint, checked, onChange, disabled }: RuleToggleProps) {
  return (
    <CheckboxField
      label={label}
      hint={hint}
      checked={checked}
      onChange={onChange}
      disabled={disabled}
      className="rule-toggle"
    />
  );
}
