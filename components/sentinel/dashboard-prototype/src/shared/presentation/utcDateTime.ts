/** Wire values are UTC instants; rendering follows the configured system IANA zone. */
import { getSystemTimeZone } from "./systemTimeZone";
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
    timeZone: getSystemTimeZone(),
  }).format(value);
}

/** Format a UTC epoch value with locale conventions while keeping the timezone explicit. */
export function formatUtcDateTime(
  value: number,
  locale: string,
  style: UtcDateTimeStyle = DEFAULT_UTC_DATE_TIME_STYLE,
): string {
  const zone = getSystemTimeZone();
  const offset = new Intl.DateTimeFormat(locale, {
    timeZone: zone,
    timeZoneName: "shortOffset",
  })
    .formatToParts(value)
    .find((part) => part.type === "timeZoneName")?.value;
  return `${formatUtcInstant(value, locale, style)} ${offset ?? zone}`;
}
