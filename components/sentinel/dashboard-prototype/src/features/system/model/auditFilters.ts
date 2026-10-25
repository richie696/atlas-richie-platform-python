import { AUDIT_ACTION, AUDIT_RESULT, validAuditQuery, type AuditQuery } from "./systemObservation";
export interface AuditFilterDraft {
  readonly startUtc: string;
  readonly endUtc: string;
  readonly actorId: string;
  readonly action: string;
  readonly result: string;
}
/** UTC input does not use the browser's timezone or metric observation window. */
export function auditFilterDraft(query: AuditQuery): AuditFilterDraft {
  return {
    startUtc: formatUtcInput(query.startMs),
    endUtc: formatUtcInput(query.endMs),
    actorId: query.actorId,
    action: query.action ?? "",
    result: query.result ?? "",
  };
}
function formatUtcInput(value: number): string {
  return new Date(value).toISOString().slice(0, 19);
}
function utcInput(value: string): number | null {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/.test(value)) return null;
  const canonical = `${value}.000`;
  const time = Date.parse(`${canonical}Z`);
  return Number.isFinite(time) && new Date(time).toISOString().slice(0, -1) === canonical
    ? time
    : null;
}
/** Explicit apply rejects incomplete dates, invalid enum values and unbounded ranges; it never silently falls back. */
export function applyAuditFilters(draft: AuditFilterDraft, query: AuditQuery): AuditQuery | null {
  const startMs = utcInput(draft.startUtc),
    endMs = utcInput(draft.endUtc);
  const action =
      draft.action === ""
        ? null
        : Object.values(AUDIT_ACTION).find((value) => value === draft.action),
    result =
      draft.result === ""
        ? null
        : Object.values(AUDIT_RESULT).find((value) => value === draft.result);
  if (startMs === null || endMs === null || action === undefined || result === undefined)
    return null;
  const next = { ...query, startMs, endMs, actorId: draft.actorId.trim(), action, result, page: 1 };
  return validAuditQuery(next) ? next : null;
}
