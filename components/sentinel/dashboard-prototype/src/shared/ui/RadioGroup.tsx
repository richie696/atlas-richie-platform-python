import { RadioList, RadioListItem } from "@astryxdesign/core/RadioList";
import type { ReactNode } from "react";

/** Option contract for a single-value Astryx radio group. */
export type RadioGroupOption = { value: string; label: ReactNode; description?: ReactNode };

/** Shared radio group adapter used by setup and identity workflows. */
export function RadioGroup({ label, value, onChange, options, className, orientation = "vertical" }: { label: string; value: string; onChange: (value: string) => void; options: ReadonlyArray<RadioGroupOption>; className?: string; orientation?: "vertical" | "horizontal" }) {
  return <RadioList label={label} isLabelHidden className={className} value={value} onChange={onChange} orientation={orientation}>{options.map((option) => <RadioListItem key={option.value} value={option.value} label={option.label} description={option.description} />)}</RadioList>;
}
