/** Scheduler facts belong to the backend. The browser resolves civil-time input and validates hints only. */
export const ACTIVATION_STATE = Object.freeze({
  Pending: "pending",
  Activating: "activating",
  Active: "active",
  Restoring: "restoring",
  Completed: "completed",
  Blocked: "blocked",
  Cancelled: "cancelled",
} as const);
export interface ActivationSchedule {
  readonly bindingId: string;
  readonly versionId: string;
  readonly restoreVersionId: string;
  readonly activateAtMs: number;
  readonly deactivateAtMs: number;
  readonly timeZone: string;
}
export interface RuleActivationPlan extends ActivationSchedule {
  readonly id: string;
  readonly revision: string;
  readonly state: (typeof ACTIVATION_STATE)[keyof typeof ACTIVATION_STATE];
  readonly activationPublicationId: string | null;
  readonly restorePublicationId: string | null;
}
/** Pending/blocked cancellation never implies restoring an already active version. */
export function canCancelRulePlan(plan: RuleActivationPlan): boolean {
  return plan.state === ACTIVATION_STATE.Pending || plan.state === ACTIVATION_STATE.Blocked;
}
export const SCHEDULE_ISSUE = Object.freeze({
  Identity: "identity",
  Window: "window",
  Past: "past",
  TimeZone: "time_zone",
  Overlap: "overlap",
} as const);
const ACTIVE_PLAN_STATES: ReadonlySet<RuleActivationPlan["state"]> = new Set([
  ACTIVATION_STATE.Pending,
  ACTIVATION_STATE.Activating,
  ACTIVATION_STATE.Active,
  ACTIVATION_STATE.Restoring,
]);
export function validIanaTimeZone(value: string): boolean {
  try {
    if (!value.trim()) return false;
    new Intl.DateTimeFormat("en", { timeZone: value });
    return true;
  } catch {
    return false;
  }
}
/** Exact UTC intervals are half-open. Adjacent plans do not overlap; server must recheck transactionally. */
export function activationScheduleIssues(
  schedule: ActivationSchedule,
  nowMs: number,
  existing: readonly RuleActivationPlan[],
): readonly (typeof SCHEDULE_ISSUE)[keyof typeof SCHEDULE_ISSUE][] {
  const issues: (typeof SCHEDULE_ISSUE)[keyof typeof SCHEDULE_ISSUE][] = [];
  if (
    ![schedule.bindingId, schedule.versionId, schedule.restoreVersionId].every(
      (value) => !!value.trim(),
    ) ||
    schedule.versionId === schedule.restoreVersionId
  )
    issues.push(SCHEDULE_ISSUE.Identity);
  if (
    ![schedule.activateAtMs, schedule.deactivateAtMs, nowMs].every(
      (value) => Number.isSafeInteger(value) && value >= 0,
    ) ||
    schedule.deactivateAtMs <= schedule.activateAtMs
  )
    issues.push(SCHEDULE_ISSUE.Window);
  if (schedule.activateAtMs <= nowMs) issues.push(SCHEDULE_ISSUE.Past);
  if (!validIanaTimeZone(schedule.timeZone)) issues.push(SCHEDULE_ISSUE.TimeZone);
  if (
    existing.some(
      (plan) =>
        plan.bindingId === schedule.bindingId &&
        ACTIVE_PLAN_STATES.has(plan.state) &&
        schedule.activateAtMs < plan.deactivateAtMs &&
        schedule.deactivateAtMs > plan.activateAtMs,
    )
  )
    issues.push(SCHEDULE_ISSUE.Overlap);
  return issues;
}

const HOUR_MS = 60 * 60 * 1000;
const OFFSET_PROBE_HOURS = 36;
/**
 * Return all UTC candidates for a civil minute. DST gaps return none, overlaps return two;
 * UI must ask the user to choose rather than silently normalize/guess an offset.
 * Time-zone data comes from Intl; all arithmetic is bounded, no browser timer schedules execution.
 */
export function resolveCivilMinute(local: string, timeZone: string): readonly number[] {
  if (!validIanaTimeZone(timeZone)) return [];
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(local);
  if (!match) return [];
  const [, year, month, day, hour, minute] = match.map(Number);
  if (year < 100 || year > 9999) return [];
  const nominal = Date.UTC(year, month - 1, day, hour, minute);
  const date = new Date(nominal);
  if (
    date.getUTCFullYear() !== year ||
    date.getUTCMonth() !== month - 1 ||
    date.getUTCDate() !== day ||
    date.getUTCHours() !== hour ||
    date.getUTCMinutes() !== minute
  )
    return [];
  const format = new Intl.DateTimeFormat("en-US-u-ca-gregory-nu-latn", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  });
  function civilAt(atMs: number): number {
    const parts = format.formatToParts(atMs);
    const part = (key: Intl.DateTimeFormatPartTypes) =>
      Number(parts.find((item) => item.type === key)!.value);
    return Date.UTC(
      part("year"),
      part("month") - 1,
      part("day"),
      part("hour"),
      part("minute"),
      part("second"),
    );
  }
  const offsets = new Set<number>();
  for (let hours = -OFFSET_PROBE_HOURS; hours <= OFFSET_PROBE_HOURS; hours++) {
    const probe = nominal + hours * HOUR_MS;
    offsets.add(civilAt(probe) - probe);
  }
  return [...offsets]
    .map((offset) => nominal - offset)
    .filter((candidate) => civilAt(candidate) === nominal)
    .sort((a, b) => a - b);
}
