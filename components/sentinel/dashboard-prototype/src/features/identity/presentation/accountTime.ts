import { formatUtcDateTime } from "../../../shared/presentation/utcDateTime";

/** Format a backend UTC instant for the account directory in the configured system timezone. */
export function formatAccountLastLogin(value: string, locale: string): string {
  return formatUtcDateTime(new Date(value).getTime(), locale, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}
