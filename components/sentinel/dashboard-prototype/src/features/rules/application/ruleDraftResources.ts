import { AppError, AppErrorKind } from "@richie696/react-framework";
import {
  createOwnedQueryResource,
  type QueryAccessObserver,
} from "../../../shared/state/ownedQueryResource";
import type { RuleSetPort } from "../api/ruleSetPort";
import {
  validRuleSetSnapshot,
  type RuleSetSnapshot,
  type RuleBinding,
  type RuleSetCandidate,
} from "../model/ruleSet";
import { validStoredDraft, validValidationReport, validRuleSetDiff } from "../model/ruleDraftState";
import type {
  StoredRuleDraft,
  RuleValidationReport,
  RuleSetDiff,
} from "../model/ruleSetOperations";

export interface CandidateRead {
  /** Local edit generation is the query identity; business rule bodies do not become URL/cache keys. */
  readonly generation: number;
  readonly candidate: RuleSetCandidate;
}
const invalid = () =>
  new AppError(AppErrorKind.PROTOCOL, "Inconsistent rule read", {
    status: 502,
    code: "rule_read_invalid",
  });
/** Reads never update the edit buffer. Source and saved-draft refreshes remain separate facts. */
export function createRuleDraftResources(
  binding: RuleBinding,
  port: Pick<RuleSetPort, "readSnapshot" | "readDraft" | "validateCandidate" | "compareCandidate">,
  readAccess: QueryAccessObserver,
  writeAccess: QueryAccessObserver,
) {
  const source = createOwnedQueryResource<string, RuleSetSnapshot>(readAccess, {
    keyOf: (id) => id,
    async read(id, signal) {
      if (id !== binding.id) throw invalid();
      const value = await port.readSnapshot(id, signal);
      if (
        !validRuleSetSnapshot(value, id) ||
        value.binding.profile !== binding.profile ||
        value.binding.kind !== binding.kind ||
        value.binding.sourceId !== binding.sourceId ||
        value.binding.appId !== binding.appId ||
        value.binding.environmentId !== binding.environmentId
      )
        throw invalid();
      return value;
    },
    classify: (value) => (value.records.length ? "ready" : "empty"),
  });
  const saved = createOwnedQueryResource<string, StoredRuleDraft>(writeAccess, {
    keyOf: (id) => JSON.stringify([binding.id, id]),
    async read(id, signal) {
      const value = await port.readDraft(binding.id, id, signal);
      if (!validStoredDraft(value, binding, id)) throw invalid();
      return value;
    },
    classify: () => "ready",
  });
  const keyOf = ({ generation, candidate }: CandidateRead) =>
    JSON.stringify([
      binding.id,
      generation,
      candidate.profile,
      candidate.baseVersionId,
      candidate.baseChecksum,
    ]);
  const validation = createOwnedQueryResource<CandidateRead, RuleValidationReport>(writeAccess, {
    keyOf,
    async read({ candidate }, signal) {
      const value = await port.validateCandidate(candidate, signal);
      if (!validValidationReport(value, candidate)) throw invalid();
      return value;
    },
    classify: (value) => (value.isPublishable ? "ready" : "partial"),
  });
  const diff = createOwnedQueryResource<CandidateRead, RuleSetDiff>(writeAccess, {
    keyOf,
    async read({ candidate }, signal) {
      const value = await port.compareCandidate(candidate, signal);
      if (!validRuleSetDiff(value, candidate)) throw invalid();
      return value;
    },
    classify: () => "ready",
  });
  return Object.freeze({
    source,
    saved,
    validation,
    diff,
    cancel() {
      source.cancel();
      saved.cancel();
      validation.cancel();
      diff.cancel();
    },
    dispose() {
      source.dispose();
      saved.dispose();
      validation.dispose();
      diff.dispose();
    },
  });
}
