import { NumberInput } from "@astryxdesign/core/NumberInput";

/** Product-neutral numeric field adapter with explicit empty-value semantics. */
export function NumberField({
  label,
  value,
  onChange,
  hint,
  disabled = false,
  min,
  max,
  step = 1,
  className,
  error,
  allowEmpty = false,
}: {
  label: string;
  value: number | string | undefined;
  onChange: (value: string) => void;
  hint?: string;
  disabled?: boolean;
  min?: number;
  max?: number;
  step?: number | null;
  className?: string;
  error?: string;
  allowEmpty?: boolean;
}) {
  const numericValue = value === "" || value === undefined ? null : Number(value);
  return (
    <NumberInput
      width="100%"
      label={label}
      description={hint}
      value={numericValue}
      hasClear={allowEmpty}
      onChange={(next: number | null) => onChange(next === null ? "" : String(next))}
      isDisabled={disabled}
      min={min}
      max={max}
      step={step}
      className={className}
      status={error ? { type: "error", message: error } : undefined}
      statusVariant="detached"
    />
  );
}
