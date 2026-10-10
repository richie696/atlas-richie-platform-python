/** Format a display-only number with locale conventions without mutating its source value. */
export function formatLocaleNumber(
  value: number,
  locale: string,
  options?: Intl.NumberFormatOptions,
): string {
  return new Intl.NumberFormat(locale, options).format(value);
}
