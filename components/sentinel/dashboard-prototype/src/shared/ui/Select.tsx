import selectStyles from "./Select.module.scss";
import { scopedClasses } from "./styles/scopedClasses";
import { Selector } from "@astryxdesign/core/Selector";
import { resolveChoiceValue } from "./valueSelection";

const styleModules = [selectStyles] as const;

export type SelectOption<Value extends string = string> =
  Value | { readonly value: Value; readonly label: string };

/**
 * Astryx `Selector` 的 Dashboard 适配层。
 *
 * 中文
 * ----
 * `V` 泛型让 `onChange` 传出**协议值**类型而不是一律 `string`：时间范围下拉传
 * `TimeRangeId`，调用方收到的就是 `TimeRangeId`，不需要在 `onChange` 里再做一次
 * 断言或转型。字符串字面量选项仍按字符串处理。
 */
export type SelectProps<V extends string = string> = {
  readonly label: string;
  readonly value: V;
  readonly onChange: (value: V) => void;
  readonly options: readonly SelectOption<NoInfer<V>>[];
  readonly hint?: string;
  readonly disabled?: boolean;
  readonly className?: string;
  readonly isLabelHidden?: boolean;
  readonly error?: string;
};

export function Select<V extends string = string>({
  label,
  value,
  onChange,
  options,
  hint,
  disabled = false,
  className,
  isLabelHidden = false,
  error,
}: SelectProps<V>) {
  const selectorOptions = options.map((item) =>
    typeof item === "string" ? item : { value: item.value, label: item.label },
  );
  // Only identities from the provided catalog may cross the vendor string boundary.
  return (
    <Selector
      width="100%"
      className={scopedClasses(styleModules, className ?? "select-control")}
      label={label}
      isLabelHidden={isLabelHidden}
      description={hint}
      value={value}
      options={selectorOptions}
      onChange={(candidate) => {
        const next = resolveChoiceValue(options, candidate);
        if (next !== undefined) onChange(next);
      }}
      isDisabled={disabled}
      status={error ? { type: "error", message: error } : undefined}
      statusVariant="detached"
      variant="input"
      renderValue={(option) => option.label ?? option.value}
    />
  );
}
