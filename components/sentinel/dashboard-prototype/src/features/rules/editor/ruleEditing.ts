import type { TypedRuleDraft } from "./ruleDraft";
import { draftFromEntry, type RuleWorkbenchEntry } from "./ruleEntry";
import type { RuleIssue } from "./rulePolicy";

/** A validation result belongs to one draft session, never to a previously selected rule. */
export type RuleValidationState =
  | { readonly status: "idle" }
  | { readonly status: "passed" }
  | { readonly status: "failed"; readonly issues: readonly RuleIssue[] };

/** The sole owner of draft, edit mode and validation for an exact selected baseline. */
export interface RuleDraftSession {
  readonly entryId: string;
  readonly baseline: RuleWorkbenchEntry["sentinelRule"];
  readonly rule: TypedRuleDraft;
  readonly editing: boolean;
  readonly validation: RuleValidationState;
}

export function createDraftSession(entry: RuleWorkbenchEntry): RuleDraftSession {
  return {
    entryId: entry.id,
    baseline: entry.sentinelRule,
    rule: draftFromEntry(entry),
    editing: false,
    validation: { status: "idle" },
  };
}

/** Resolve before rendering; unlike Effect synchronization this cannot expose an old draft. */
export function resolveDraftSession(
  entry: RuleWorkbenchEntry | null,
  session: RuleDraftSession | null,
): RuleDraftSession | null {
  if (!entry) return null;
  return session?.entryId === entry.id && session.baseline === entry.sentinelRule
    ? session
    : createDraftSession(entry);
}

/** Category checks protect event boundaries even when called by plain JavaScript. */
export function editDraftSession(
  session: RuleDraftSession,
  rule: TypedRuleDraft,
): RuleDraftSession {
  if (session.rule.kind !== rule.kind) throw new TypeError("Mismatched rule category");
  return { ...session, rule, editing: true, validation: { status: "idle" } };
}
