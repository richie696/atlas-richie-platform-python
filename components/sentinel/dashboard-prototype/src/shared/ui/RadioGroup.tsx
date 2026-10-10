import { RadioList, RadioListItem } from "@astryxdesign/core/RadioList";
import type { ReactNode } from "react";
import styles from "./RadioGroup.module.scss";
import { resolveChoiceValue } from "./valueSelection";

/** Option contract for a single-value Astryx radio group. */
export type RadioGroupOption<Value extends string = string> = {
  readonly value: Value;
  readonly label: ReactNode;
  readonly description?: ReactNode;
};

/** Shared radio group adapter used by setup and identity workflows. */
export function RadioGroup<Value extends string = string>({
  label,
  value,
  onChange,
  options,
  className,
  orientation = "vertical",
  variant = "plain",
}: {
  label: string;
  value: Value;
  onChange: (value: Value) => void;
  options: readonly RadioGroupOption<NoInfer<Value>>[];
  className?: string;
  orientation?: "vertical" | "horizontal";
  /** Uses public RadioListItem slots, not native label/input overrides. */
  variant?: "plain" | "cards";
}) {
  return (
    <RadioList
      label={label}
      isLabelHidden
      className={[className, variant === "cards" ? styles.cards : undefined]
        .filter(Boolean)
        .join(" ")}
      value={value}
      onChange={(candidate) => {
        const next = resolveChoiceValue(options, candidate);
        if (next !== undefined) onChange(next);
      }}
      orientation={orientation}
    >
      {options.map((option) => (
        <RadioListItem
          key={option.value}
          value={option.value}
          label={option.label}
          description={option.description}
          className={
            variant === "cards"
              ? [styles.card, option.value === value ? styles.selected : undefined]
                  .filter(Boolean)
                  .join(" ")
              : undefined
          }
        />
      ))}
    </RadioList>
  );
}
