import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";

/** Product-neutral boolean field adapter for Astryx checkbox semantics. */
export function CheckboxField({ label, checked, onChange, hint, disabled = false, className }: { label: string; checked: boolean; onChange: (checked: boolean) => void; hint?: string; disabled?: boolean; className?: string }) {
  return <CheckboxInput label={label} description={hint} value={checked} onChange={onChange} isDisabled={disabled} className={className} />;
}
