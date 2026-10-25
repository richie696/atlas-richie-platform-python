import { DateTimeInput, type ISODateTimeString } from "@astryxdesign/core/DateTimeInput";

/** Astryx date/time field adapter; the caller defines how its timezone-free ISO value is interpreted. */
export function DateTimeField({
  label,
  value,
  onChange,
  hint,
  disabled = false,
}: {
  readonly label: string;
  readonly value: string;
  readonly onChange: (value: string) => void;
  readonly hint?: string;
  readonly disabled?: boolean;
}) {
  return (
    <DateTimeInput
      width="100%"
      label={label}
      description={hint}
      value={value ? (value as ISODateTimeString) : undefined}
      onChange={(next) => onChange(next ?? "")}
      isDisabled={disabled}
      hourFormat="24h"
      hasSeconds
      timeOptionInterval={15}
      nativePicker="never"
    />
  );
}
