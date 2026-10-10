/** The protocol carries UTC instants; only their user-facing representation follows the UI locale. */
export const UTC_TIME_ZONE = "UTC";
export interface UtcDateTimeStyle {
  readonly dateStyle: NonNullable<Intl.DateTimeFormatOptions["dateStyle"]>;
  readonly timeStyle: NonNullable<Intl.DateTimeFormatOptions["timeStyle"]>;
}
const DEFAULT_UTC_DATE_TIME_STYLE: UtcDateTimeStyle = Object.freeze({
  dateStyle: "medium",
  timeStyle: "medium",
});

/** Format a UTC epoch value with explicit styles; callers decide where the zone marker belongs. */
export function formatUtcInstant(
  value: number,
  locale: string,
  style: UtcDateTimeStyle = DEFAULT_UTC_DATE_TIME_STYLE,
): string {
  return new Intl.DateTimeFormat(locale, {
    ...style,
    timeZone: UTC_TIME_ZONE,
  }).format(value);
}

/** Format a UTC epoch value with locale conventions while keeping the timezone explicit. */
export function formatUtcDateTime(
  value: number,
  locale: string,
  style: UtcDateTimeStyle = DEFAULT_UTC_DATE_TIME_STYLE,
): string {
  return `${formatUtcInstant(value, locale, style)} ${UTC_TIME_ZONE}`;
}
