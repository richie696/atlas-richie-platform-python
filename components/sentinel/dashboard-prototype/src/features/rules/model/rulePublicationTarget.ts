/** Exact provider destination configured for one binding; credential material is never included. */
export type RulePublicationTarget =
  | {
      readonly provider: "nacos";
      readonly sourceId: string;
      readonly namespace: string;
      readonly group: string;
      readonly dataId: string;
    }
  | {
      readonly provider: "consul";
      readonly sourceId: string;
      readonly key: string;
      readonly datacenter: string | null;
    };

/** Revisions let the backend reject stale source or concurrent target edits. */
export interface VersionedRulePublicationTarget {
  readonly bindingId: string;
  readonly targetRevision: string;
  readonly sourceRevision: string;
  readonly target: RulePublicationTarget;
}

/** Target reads distinguish an unconfigured binding from unavailable authority. */
export type RulePublicationTargetSnapshot =
  | { readonly bindingId: string; readonly target: null }
  | {
      readonly bindingId: string;
      readonly targetRevision: string;
      readonly sourceRevision: string;
      readonly target: RulePublicationTarget;
    };

export function validRulePublicationTargetSnapshot(
  value: RulePublicationTargetSnapshot,
  bindingId: string,
): boolean {
  if (value.bindingId !== bindingId) return false;
  if (value.target === null) return true;
  const target = value.target;
  const identities =
    target.provider === "nacos"
      ? [target.sourceId, target.namespace, target.group, target.dataId]
      : [target.sourceId, target.key];
  return (
    !!value.targetRevision.trim() &&
    !!value.sourceRevision.trim() &&
    identities.every((item) => typeof item === "string" && !!item.trim())
  );
}
