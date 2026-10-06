import { Selector } from "@astryxdesign/core/Selector";

export type SelectOption = string | { value: string | number; label: string };

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
  readonly options: ReadonlyArray<SelectOption>;
  readonly hint?: string;
  readonly disabled?: boolean;
  readonly className?: string;
  readonly isLabelHidden?: boolean;
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
}: SelectProps<V>) {
  const selectorOptions = options.map((item) =>
    typeof item === "string" ? item : { value: String(item.value), label: item.label },
  );
  // Astryx Selector 的值域是 string。协议值类型（如 TimeRangeId）在这里一次性收窄，
  // 上层 onChange 仍拿到 V，避免每个调用点各写一次转型。
  return (
    <Selector
      className={className ?? "select-control"}
      label={label}
      isLabelHidden={isLabelHidden}
      description={hint}
      value={value}
      options={selectorOptions}
      onChange={onChange as (value: string) => void}
      isDisabled={disabled}
      variant="input"
      renderValue={(option) => option.label ?? option.value}
    />
  );
}
