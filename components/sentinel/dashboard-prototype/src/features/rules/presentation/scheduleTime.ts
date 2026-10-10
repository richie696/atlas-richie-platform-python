import { formatUtcDateTime } from "../../../shared/presentation/utcDateTime";

/** A translated option label paired with the stable value submitted by the rule workflow. */
export interface ScheduleOccurrenceOption {
  readonly value: string;
  readonly label: string;
}

/**
 * Present civil-time occurrences as explicit UTC instants.
 *
 * Locale affects labels only. The option values remain epoch-millisecond strings so changing
 * the UI language cannot change a selected DST occurrence or the activation protocol payload.
 */
export function scheduleOccurrenceOptions(
  values: readonly number[],
  locale: string,
  chooseLabel: string,
): readonly ScheduleOccurrenceOption[] {
  return Object.freeze([
    Object.freeze({ value: "", label: chooseLabel }),
    ...values.map((value) => {
      if (!Number.isSafeInteger(value) || value < 0) {
        throw new RangeError("schedule occurrence must be a non-negative epoch millisecond");
      }
      return Object.freeze({
        value: String(value),
        label: formatUtcDateTime(value, locale),
      });
    }),
  ]);
}
