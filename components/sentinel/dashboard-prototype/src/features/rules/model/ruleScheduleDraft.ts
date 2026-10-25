import { resolveCivilMinute, type ActivationSchedule } from "./ruleActivation";
export const DEFAULT_SCHEDULE_TIME_ZONE = "UTC";
export interface RuleScheduleDraft {
  readonly versionId: string;
  readonly restoreVersionId: string;
  readonly timeZone: string;
  readonly startsAt: string;
  readonly endsAt: string;
  /** Empty until the user chooses an explicit UTC occurrence when the civil minute is ambiguous. */
  readonly startOccurrence: string;
  readonly endOccurrence: string;
}
/** Stable pristine local schedule; a civil-time choice is never filled from a guessed default version. */
export const INITIAL_RULE_SCHEDULE_DRAFT: RuleScheduleDraft = Object.freeze({
  versionId: "",
  restoreVersionId: "",
  timeZone: DEFAULT_SCHEDULE_TIME_ZONE,
  startsAt: "",
  endsAt: "",
  startOccurrence: "",
  endOccurrence: "",
});
/** Only local user input determines dirty state, not a catalog refresh or validation response. */
export function hasRuleScheduleChanges(draft: RuleScheduleDraft): boolean {
  return (Object.keys(INITIAL_RULE_SCHEDULE_DRAFT) as (keyof RuleScheduleDraft)[]).some(
    (key) => draft[key] !== INITIAL_RULE_SCHEDULE_DRAFT[key],
  );
}
export const CIVIL_TIME_ISSUE = Object.freeze({
  Identity: "identity",
  Start: "start",
  End: "end",
  Window: "window",
} as const);
/** Resolve displayed civil-time input without a default DST offset or implicit restore version. */
export function prepareRuleSchedule(
  bindingId: string,
  draft: RuleScheduleDraft,
):
  | { readonly valid: true; readonly schedule: ActivationSchedule }
  | {
      readonly valid: false;
      readonly issues: readonly (typeof CIVIL_TIME_ISSUE)[keyof typeof CIVIL_TIME_ISSUE][];
    } {
  const choose = (local: string, occurrence: string) => {
    const values = resolveCivilMinute(local, draft.timeZone);
    if (values.length === 1)
      return occurrence === "" || occurrence === String(values[0]) ? values[0] : null;
    return occurrence !== "" && values.includes(Number(occurrence)) ? Number(occurrence) : null;
  };
  const start = choose(draft.startsAt, draft.startOccurrence),
    end = choose(draft.endsAt, draft.endOccurrence);
  const issues: (typeof CIVIL_TIME_ISSUE)[keyof typeof CIVIL_TIME_ISSUE][] = [];
  if (
    ![bindingId, draft.versionId, draft.restoreVersionId].every((value) => !!value.trim()) ||
    draft.versionId === draft.restoreVersionId
  )
    issues.push(CIVIL_TIME_ISSUE.Identity);
  if (start === null) issues.push(CIVIL_TIME_ISSUE.Start);
  if (end === null) issues.push(CIVIL_TIME_ISSUE.End);
  if (start !== null && end !== null && end <= start) issues.push(CIVIL_TIME_ISSUE.Window);
  if (issues.length || start === null || end === null) return { valid: false, issues };
  return {
    valid: true,
    schedule: {
      bindingId,
      versionId: draft.versionId,
      restoreVersionId: draft.restoreVersionId,
      timeZone: draft.timeZone,
      activateAtMs: start,
      deactivateAtMs: end,
    },
  };
}
