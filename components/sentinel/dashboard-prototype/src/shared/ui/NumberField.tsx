import { NumberInput } from "@astryxdesign/core/NumberInput";

/** Product-neutral numeric field adapter with explicit empty-value semantics. */
export function NumberField({ label, value, onChange, hint, disabled = false, min, max, step = 1, className }: { label: string; value: number | string | undefined; onChange: (value: string) => void; hint?: string; disabled?: boolean; min?: number; max?: number; step?: number; className?: string }) {
  const numericValue = value === "" || value === undefined ? null : Number(value);
  return <NumberInput label={label} description={hint} value={numericValue} onChange={(next) => onChange(String(next))} isDisabled={disabled} min={min} max={max} step={step} className={className} />;
}
