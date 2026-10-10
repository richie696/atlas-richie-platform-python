/** Cross-runtime blank characters used by bounded Console identifiers. */
export const NON_BLANK_WIRE_CONTENT =
  /[^\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]/u;
const WIRE_BLANK_CHARACTER_CLASS =
  "\\u0009-\\u000d\\u001c-\\u0020\\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000\\ufeff";
/** Reject wire text whose first or last character is in the shared blank-character set. */
export const NO_WIRE_BOUNDARY_BLANK = new RegExp(
  `^(?![${WIRE_BLANK_CHARACTER_CLASS}])[\\s\\S]*[^${WIRE_BLANK_CHARACTER_CLASS}]$`,
);

/** Return whether a JavaScript string contains only Unicode scalar values. */
export function hasOnlyUnicodeScalarValues(value: string): boolean {
  return !/[\uD800-\uDFFF]/u.test(value);
}

/** Match the Console wire definition of a string containing non-blank content. */
export function hasNonBlankWireContent(value: string): boolean {
  return NON_BLANK_WIRE_CONTENT.test(value);
}

/** Validate one bounded opaque identifier without depending on a schema library. */
export function isBoundedWireIdentifier(value: string, maximum: number): boolean {
  return (
    Number.isSafeInteger(maximum) &&
    maximum >= 0 &&
    value.length <= maximum &&
    hasOnlyUnicodeScalarValues(value) &&
    hasNonBlankWireContent(value)
  );
}
