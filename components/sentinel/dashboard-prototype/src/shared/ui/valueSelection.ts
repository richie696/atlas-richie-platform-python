/** Choice identity accepted by a controlled UI adapter; labels never become identifiers. */
export type ValueChoice<Value extends string> = Value | { readonly value: Value };

/** Resolve against the caller's actual choices, not an unchecked cast of a vendor callback string. */
export function resolveChoiceValue<Value extends string>(
  choices: readonly ValueChoice<Value>[],
  candidate: string,
): Value | undefined {
  for (const choice of choices) {
    const value = typeof choice === "string" ? choice : choice.value;
    if (value === candidate) return value;
  }
  return undefined;
}
