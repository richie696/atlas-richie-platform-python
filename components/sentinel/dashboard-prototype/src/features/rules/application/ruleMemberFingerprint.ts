import { RULE_KIND, SentinelCode } from "../model/ruleKinds";
import type { RuleCatalogEntry } from "../model/ruleDirectory";
import type { RuleLoadObservationPage } from "../model/ruleObservations";

const encoder = new TextEncoder();

/**
 * Computes the shared Java/Go/Rust Flow member fingerprint only for the exact V1
 * subset. Unsupported profiles or semantics return null so the UI cannot infer
 * runtime usage from an incompatible rule representation.
 */
export async function ruleMemberFingerprint(entry: RuleCatalogEntry): Promise<string | null> {
  const { binding, record } = entry;
  if (
    !["sentinel-java-v1", "sentinel-go-v1", "sentinel-rust-v1"].includes(binding.profile) ||
    record.rule.kind !== RULE_KIND.Flow
  ) {
    return null;
  }

  const rule = record.rule.value;
  if (
    !rule.resource ||
    rule.resource.trim() !== rule.resource ||
    encoder.encode(rule.resource).byteLength > 200 ||
    rule.limitApp !== "default" ||
    rule.grade !== SentinelCode.FLOW_GRADE_QPS ||
    rule.strategy !== SentinelCode.FLOW_STRATEGY_DIRECT ||
    rule.controlBehavior !== SentinelCode.FLOW_BEHAVIOR_REJECT ||
    rule.clusterMode ||
    (rule.refResource !== undefined && rule.refResource !== "") ||
    (rule.warmUpPeriodSec !== undefined && rule.warmUpPeriodSec !== 0) ||
    (rule.maxQueueingTimeMs !== undefined && rule.maxQueueingTimeMs !== 0) ||
    rule.clusterConfig !== undefined ||
    !Number.isFinite(rule.count) ||
    rule.count <= 0
  ) {
    return null;
  }

  const threshold = rule.count.toString();
  if (
    !/^\d+(?:\.\d+)?$/.test(threshold) ||
    Number(threshold) > 1_000_000_000 ||
    (threshold.split(".")[1]?.length ?? 0) > 6
  ) {
    return null;
  }
  const normalizedThreshold = threshold.includes(".")
    ? threshold.replace(/0+$/, "").replace(/\.$/, "")
    : threshold;
  const resourceBytes = encoder.encode(rule.resource);
  const thresholdBytes = encoder.encode(normalizedThreshold);
  const prefix = encoder.encode(`sentinel-flow-member-v1\n${resourceBytes.byteLength}:`);
  const middle = encoder.encode(`\n${thresholdBytes.byteLength}:`);
  const suffix = encoder.encode("\n");
  const bytes = new Uint8Array(
    prefix.byteLength +
      resourceBytes.byteLength +
      middle.byteLength +
      thresholdBytes.byteLength +
      suffix.byteLength,
  );
  let offset = 0;
  for (const part of [prefix, resourceBytes, middle, thresholdBytes, suffix]) {
    bytes.set(part, offset);
    offset += part.byteLength;
  }

  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join(
    "",
  );
}

/**
 * Return counts only when the target inventory and this observation page are complete.
 * Stale, missing, incompatible, or failed observations remain unconfirmed; they are never
 * interpreted as a negative membership result.
 */
export function confirmedRuleInstanceUsage(
  entry: RuleCatalogEntry,
  memberFingerprint: string | null | undefined,
  page: RuleLoadObservationPage | undefined,
): {
  readonly loaded: number;
  readonly notIncluded: number;
  readonly expected: number;
  readonly unconfirmed: number;
} | null {
  if (
    !page ||
    page.query.environmentId !== entry.binding.environmentId ||
    page.query.appId !== entry.binding.appId ||
    page.query.bindingId !== entry.binding.id ||
    page.coverage !== "complete" ||
    page.targets.expected === null ||
    page.targets.observed === null ||
    page.targets.stale === null ||
    page.targets.notObserved === null ||
    page.targets.expected !== page.targets.observed + page.targets.notObserved ||
    page.total !== page.targets.expected ||
    page.hasMore ||
    page.items.length !== page.targets.expected ||
    !page.items.every(
      (observation) =>
        observation.bindingId === entry.binding.id && observation.instanceId.length > 0,
    ) ||
    page.items.filter((observation) => observation.eventKind !== null).length !==
      page.targets.observed ||
    page.items.filter((observation) => observation.freshness === "stale").length !==
      page.targets.stale
  ) {
    return null;
  }

  const hasCurrentMembership = (observation: (typeof page.items)[number]) =>
    !!memberFingerprint &&
    observation.profileId === entry.binding.profile &&
    observation.freshness === "current" &&
    observation.activeSnapshot?.membershipComplete === true &&
    (observation.loadState === "applied" ||
      observation.loadState === "failed_keeps_last_known_good");
  const matchesRule = (observation: (typeof page.items)[number]) =>
    observation.activeSnapshot?.members.some(
      (member) =>
        member.ruleKind === entry.record.rule.kind &&
        member.fingerprintSha256 === memberFingerprint,
    ) === true;
  const loaded = page.items.filter(
    (observation) => hasCurrentMembership(observation) && matchesRule(observation),
  ).length;
  const notIncluded = page.items.filter(
    (observation) => hasCurrentMembership(observation) && !matchesRule(observation),
  ).length;

  return {
    loaded,
    notIncluded,
    expected: page.targets.expected,
    unconfirmed: page.targets.expected - loaded - notIncluded,
  };
}

/**
 * Projects each authoritative observation into exact membership for one catalog rule.
 * Partial pages remain useful for inspection, but missing/incompatible member data stays unknown.
 */
export function ruleInstanceMembership(
  entry: RuleCatalogEntry,
  memberFingerprint: string | null | undefined,
  page: RuleLoadObservationPage | undefined,
):
  | readonly {
      readonly observation: RuleLoadObservationPage["items"][number];
      readonly membership: "included" | "not_included" | "unknown";
    }[]
  | null {
  if (
    !page ||
    page.query.environmentId !== entry.binding.environmentId ||
    page.query.appId !== entry.binding.appId ||
    page.query.bindingId !== entry.binding.id
  ) {
    return null;
  }

  return page.items.map((observation) => {
    const trustedMembership =
      memberFingerprint &&
      observation.bindingId === entry.binding.id &&
      observation.profileId === entry.binding.profile &&
      observation.freshness === "current" &&
      observation.activeSnapshot?.membershipComplete === true;
    const containsRule = trustedMembership
      ? observation.activeSnapshot?.members.some(
          (member) =>
            member.ruleKind === entry.record.rule.kind &&
            member.fingerprintSha256 === memberFingerprint,
        ) === true
      : false;
    return {
      observation,
      membership: !trustedMembership ? "unknown" : containsRule ? "included" : "not_included",
    } as const;
  });
}
