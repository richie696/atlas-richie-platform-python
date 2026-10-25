import { useExternalSnapshot } from "@richie696/react-framework-react";
import { StateStore, AppError, AppErrorKind } from "@richie696/react-framework";
import { AstryxProvider } from "../../../src/app/providers/AstryxProvider";
import {
  createRuleOperation,
  createRuleDraftWorkflow,
  RuleSetWorkbenchPage,
} from "../../../src/features/rules/workspace";
import type {
  RuleMutation,
  RuleMutationResult,
  RuleOperationObservation,
  StoredRuleDraft,
  RuleValidationReport,
} from "../../../src/features/rules/model/ruleSetOperations";
import type { RuleSetCandidate } from "../../../src/features/rules/model/ruleSet";
import type { QueryAccess } from "../../../src/shared/state/ownedQueryResource";
import { ruleSet } from "../../fixtures/ruleSets";
const MODES = [
  "success",
  "conflict",
  "unknown",
  "held-validation",
  "unsupported",
  "offline",
] as const;
const LOOKUPS = ["completed", "pending", "not-found"] as const;
/** Synthetic Port topology only, not a mock HTTP gateway or a Python publication proof. */
export function createRuleWorkspaceTopology() {
  const read = new StateStore<QueryAccess>({ ownerKey: "rule-workspace-session", allowed: true }),
    write = new StateStore<QueryAccess>({ ownerKey: "rule-workspace-session", allowed: true });
  const counts = new StateStore({
    writes: 0,
    lookups: 0,
    sourceReads: 0,
    validates: 0,
    aborts: 0,
    lastCandidate: null as RuleSetCandidate | null,
  });
  let mode: (typeof MODES)[number] = "success",
    lookup: (typeof LOOKUPS)[number] = "completed",
    changedSource = false,
    key = 0,
    localKey = 0,
    latest: RuleMutation | null = null,
    latestResult: RuleMutationResult | null = null,
    stored: StoredRuleDraft | null = null,
    release: (() => void) | null = null;
  const readAccess = { read: read.getSnapshot, subscribe: read.subscribe },
    writeAccess = { read: write.getSnapshot, subscribe: write.subscribe };
  function complete(mutation: RuleMutation): RuleOperationObservation {
    if (mutation.kind === "save_draft") {
      stored = {
        id: mutation.draftId ?? "persisted-draft",
        bindingId: mutation.bindingId,
        revision: "revision-" + counts.getSnapshot().writes,
        kind: mutation.candidate.kind,
        profile: mutation.candidate.profile,
        baseVersionId: mutation.candidate.baseVersionId,
        baseChecksum: mutation.candidate.baseChecksum,
        sourceRevision: mutation.candidate.sourceRevision,
        updatedAtMs: ruleSet.asOfMs,
        records: mutation.candidate.rules.map((record, index) => ({
          id: record.recordId ?? "assigned-rule-" + index,
          rule: record.rule,
        })),
      };
      latestResult = { kind: "save_draft", draft: stored };
    } else if (mutation.kind === "delete_draft") {
      stored = null;
      latestResult = { kind: "delete_draft", draftId: mutation.draftId };
    } else if (mutation.kind === "freeze_version" && stored)
      latestResult = {
        kind: "freeze_version",
        draftId: stored.id,
        draftRevision: stored.revision,
        version: {
          id: "version-frozen",
          bindingId: mutation.bindingId,
          kind: stored.kind,
          profile: stored.profile,
          baseVersionId: stored.baseVersionId,
          checksum: mutation.candidateChecksum,
          name: mutation.name,
          note: mutation.note,
          createdAtMs: ruleSet.asOfMs,
          createdById: "test-actor",
          records: stored.records,
        },
      };
    if (!latestResult)
      throw new AppError(AppErrorKind.PROTOCOL, "Unsupported test action", { status: 422 });
    return {
      status: "completed",
      bindingId: mutation.bindingId,
      requestKey: mutation.requestKey,
      result: latestResult,
    };
  }
  const operation = createRuleOperation(
    ruleSet.binding.id,
    {
      async mutateRuleSet(mutation) {
        latest = mutation;
        counts.set({
          ...counts.getSnapshot(),
          writes: counts.getSnapshot().writes + 1,
          lastCandidate:
            mutation.kind === "save_draft"
              ? mutation.candidate
              : counts.getSnapshot().lastCandidate,
        });
        if (mode === "conflict")
          return {
            status: "rejected",
            reason: "conflict",
            bindingId: mutation.bindingId,
            requestKey: mutation.requestKey,
          };
        const value = complete(mutation);
        if (mode === "unknown") throw new AppError(AppErrorKind.NETWORK, "PRIVATE-RULE-WRITE");
        return value;
      },
      async readRuleOperation(bindingId, requestKey) {
        counts.set({ ...counts.getSnapshot(), lookups: counts.getSnapshot().lookups + 1 });
        if (lookup !== "completed" || !latestResult)
          return { bindingId, requestKey, status: lookup === "completed" ? "pending" : lookup };
        return { bindingId, requestKey, status: "completed", result: latestResult };
      },
    },
    writeAccess,
    () => "operation-" + ++key,
  );
  const workflow = createRuleDraftWorkflow(
    ruleSet.binding,
    {
      async readSnapshot() {
        counts.set({ ...counts.getSnapshot(), sourceReads: counts.getSnapshot().sourceReads + 1 });
        if (mode === "offline") throw new AppError(AppErrorKind.NETWORK, "PRIVATE-SOURCE-READ");
        return changedSource
          ? {
              ...ruleSet,
              versionId: "external-version",
              checksum: "external-checksum",
              sourceRevision: "external-revision",
              records: ruleSet.records.map((record) => ({
                ...record,
                rule:
                  record.rule.kind === "flow"
                    ? { ...record.rule, value: { ...record.rule.value, count: 999 } }
                    : record.rule,
              })),
            }
          : structuredClone(ruleSet);
      },
      async readDraft(bindingId, id) {
        if (!stored || stored.id !== id)
          throw new AppError(AppErrorKind.PROTOCOL, "Missing draft", { status: 404 });
        return stored;
      },
      async validateCandidate(candidate, signal) {
        counts.set({ ...counts.getSnapshot(), validates: counts.getSnapshot().validates + 1 });
        const value: RuleValidationReport = {
          bindingId: candidate.bindingId,
          profile: candidate.profile,
          baseChecksum: candidate.baseChecksum,
          candidateChecksum: "test-candidate-checksum",
          validationId: "test-validation-ticket",
          isPublishable: mode !== "unsupported",
          issues:
            mode === "unsupported"
              ? [{ code: "unsupported_capability", recordIndex: null, path: "clusterMode" }]
              : [],
        };
        if (mode === "held-validation")
          return new Promise<RuleValidationReport>((resolve) => {
            signal.addEventListener(
              "abort",
              () =>
                counts.set({ ...counts.getSnapshot(), aborts: counts.getSnapshot().aborts + 1 }),
              { once: true },
            );
            release = () => resolve(value);
          });
        return value;
      },
      async compareCandidate(candidate) {
        return {
          bindingId: candidate.bindingId,
          baseChecksum: candidate.baseChecksum,
          candidateChecksum: "test-candidate-checksum",
          changes: [],
        };
      },
    },
    readAccess,
    writeAccess,
    operation,
  );
  return {
    read,
    write,
    counts,
    workflow,
    operation,
    newFormKey: () => "local-form-" + ++localKey,
    setMode(value: typeof mode) {
      mode = value;
    },
    setLookup(value: typeof lookup) {
      lookup = value;
    },
    changeSource() {
      changedSource = true;
    },
    release: () => release?.(),
    last: () => latest,
    readDrafts: async () => ({
      bindingId: ruleSet.binding.id,
      asOfMs: ruleSet.asOfMs,
      items: stored ? [stored] : [],
    }),
    dispose() {
      workflow.dispose();
      operation.dispose();
      read.complete();
      write.complete();
      counts.complete();
    },
  };
}
/** Actual formal controls under StrictMode; diagnostic controls never enter production source. */
export function RuleSetWorkspaceProbe({
  topology,
}: {
  readonly topology: ReturnType<typeof createRuleWorkspaceTopology>;
}) {
  const state = useExternalSnapshot(topology.workflow),
    counts = useExternalSnapshot(topology.counts);
  return (
    <AstryxProvider>
      <div data-test-effects>
        {MODES.map((mode) => (
          <button key={mode} data-rule-mode={mode} onClick={() => topology.setMode(mode)}>
            {mode}
          </button>
        ))}
        {LOOKUPS.map((value) => (
          <button key={value} data-rule-lookup={value} onClick={() => topology.setLookup(value)}>
            {value}
          </button>
        ))}
        <button data-rule-source-change onClick={topology.changeSource}>
          Change source
        </button>
        <button data-rule-validation-release onClick={topology.release}>
          Release validation
        </button>
        <button
          data-rule-revoke
          onClick={() => topology.write.set({ ownerKey: "rule-workspace-session", allowed: false })}
        >
          Revoke edit
        </button>
        <button
          data-rule-grant
          onClick={() => topology.write.set({ ownerKey: "rule-workspace-session", allowed: true })}
        >
          Grant edit
        </button>
      </div>
      <RuleSetWorkbenchPage
        workflow={topology.workflow}
        binding={ruleSet.binding}
        newFormKey={topology.newFormKey}
      />
      <output
        data-rule-summary
        style={{ display: "block", whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
      >
        {JSON.stringify({
          source: state.source.status,
          sourceVersion: "data" in state.source ? state.source.data.versionId : null,
          validation: state.validation.status,
          operation: state.operation.command.status,
          inspecting: state.operation.inspecting,
          dirty: state.dirty,
          locked: state.locked,
          selectedKey: state.selectedKey,
          savedIdentity: state.savedIdentity,
          editingVersion: state.editing?.baseline.versionId,
          ruleCount: state.editing?.records.length,
          ruleValue: state.editing?.records[0]?.rule.draft,
          authorized: state.authorized,
          ...counts,
        })}
      </output>
    </AstryxProvider>
  );
}
