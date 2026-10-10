import { TextInput } from "@astryxdesign/core/TextInput";

/** Product-neutral text field adapter for the Astryx input contract. */
export function TextField({
  label,
  value,
  onChange,
  hint,
  disabled = false,
  type = "text",
  placeholder,
  className,
  autoComplete,
  isLabelHidden = false,
  error,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: string;
  disabled?: boolean;
  type?: "text" | "password" | "email";
  placeholder?: string;
  className?: string;
  autoComplete?: string;
  isLabelHidden?: boolean;
  error?: string;
}) {
  const fieldClassName = className ? `astryx-text-field ${className}` : "astryx-text-field";
  return (
    <TextInput
      width="100%"
      label={label}
      isLabelHidden={isLabelHidden}
      description={hint}
      value={value}
      onChange={onChange}
      isDisabled={disabled}
      type={type}
      placeholder={placeholder}
      className={fieldClassName}
      autoComplete={autoComplete}
      status={error ? { type: "error", message: error } : undefined}
      statusVariant="detached"
    />
  );
}
