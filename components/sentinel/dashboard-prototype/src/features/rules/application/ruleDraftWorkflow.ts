import { AppError, AppErrorKind, StateStore } from "@richie696/react-framework";
import { hasNonBlankWireContent } from "../../../core/api/protocol/common";
import type { QueryAccessObserver } from "../../../shared/state/ownedQueryResource";
import type { RuleBinding } from "../model/ruleSet";
import type { RuleSetPort } from "../api/ruleSetPort";
import type { TypedRuleDraft } from "../editor/ruleDraft";
import {
  beginRuleSetEditing,
  addRuleToSet,
  updateRuleInSet,
  removeRuleFromSet,
  prepareRuleSetCandidate,
  ruleSetIsDirty,
  type RuleSetEditing,
  type RuleSetIssue,
} from "../editor/ruleSetEditing";
import { storedDraftSnapshot } from "../model/ruleDraftState";
import {
  RULE_MUTATION,
  type RuleMutationInput,
  type RuleMutationResult,
} from "../model/ruleSetOperations";
import { HIDDEN_RULE_OPERATION, type RuleOperation } from "./ruleOperation";
import { createRuleDraftResources } from "./ruleDraftResources";
const DRAFT_MUTATIONS: ReadonlySet<string> = new Set([
  RULE_MUTATION.SaveDraft,
  RULE_MUTATION.DeleteDraft,
  RULE_MUTATION.FreezeVersion,
]);

/**
 * One binding's editor. Compose independent reads and the shared binding command owner;
 * do not construct a second mutation queue for versions/publications/plans.
 * Refresh is read-only. Replacing dirty local values requires an explicit discard intent.
 */
export function createRuleDraftWorkflow(
  binding: RuleBinding,
  port: Pick<RuleSetPort, "readSnapshot" | "readDraft" | "validateCandidate" | "compareCandidate">,
  readAccess: QueryAccessObserver,
  writeAccess: QueryAccessObserver,
  operation: RuleOperation,
) {
  const ownerKey = writeAccess.read().ownerKey;
  const resources = createRuleDraftResources(binding, port, readAccess, writeAccess);
  let disposed = false,
    performing = false,
    generation = 0,
    opening = 0;
  let editing: RuleSetEditing | null = null,
    savedIdentity: { readonly id: string; readonly revision: string } | null = null,
    selectedKey: string | null = null;
  let issues: readonly RuleSetIssue[] = [];
  const readable = () =>
    !disposed && readAccess.read().ownerKey === ownerKey && readAccess.read().allowed;
  const hidden = Object.freeze({ status: "idle" as const });
  const allowed = () =>
    !disposed &&
    writeAccess.read().ownerKey === ownerKey &&
    writeAccess.read().allowed &&
    readAccess.read().ownerKey === ownerKey &&
    readAccess.read().allowed;
  const locked = () =>
    performing ||
    opening !== 0 ||
    operation.getSnapshot().inspecting ||
    ["pending", "result-unknown"].includes(operation.getSnapshot().command.status);
  function assertEditable() {
    if (!allowed())
      throw new AppError(AppErrorKind.FORBIDDEN, "Rule editing unavailable", { status: 403 });
    if (locked()) throw new AppError(AppErrorKind.DUPLICATE, "Unresolved rule action");
  }
  const snapshot = () => ({
    authorized: allowed(),
    source: readable() ? resources.source.getSnapshot() : hidden,
    saved: allowed() ? resources.saved.getSnapshot() : hidden,
    validation: allowed() ? resources.validation.getSnapshot() : hidden,
    diff: allowed() ? resources.diff.getSnapshot() : hidden,
    operation: allowed() ? operation.getSnapshot() : HIDDEN_RULE_OPERATION,
    editing: allowed() ? editing : null,
    savedIdentity: allowed() ? savedIdentity : null,
    selectedKey: allowed() ? selectedKey : null,
    issues: allowed() ? issues : [],
    dirty: allowed() && editing !== null && ruleSetIsDirty(editing),
    locked: allowed() && locked(),
  });
  const state = new StateStore(snapshot());
  const publish = () => state.set(snapshot());
  const subscriptions = [
    resources.source,
    resources.saved,
    resources.validation,
    resources.diff,
    operation,
  ].map((resource) => resource.subscribe(publish));
  function invalidateReports() {
    generation++;
    resources.validation.reset();
    resources.diff.reset();
    issues = [];
  }
  function install(next: RuleSetEditing, identity: typeof savedIdentity) {
    editing = next;
    savedIdentity = identity;
    selectedKey = next.records[0]?.formKey ?? null;
    invalidateReports();
    publish();
  }
  function guardDiscard(discard: boolean) {
    assertEditable();
    if (!discard && editing && ruleSetIsDirty(editing))
      throw new AppError(AppErrorKind.DUPLICATE, "Unsaved rule changes", { code: "rule_unsaved" });
  }
  const revoke = () => {
    if (!allowed()) {
      opening = 0;
      editing = null;
      savedIdentity = null;
      selectedKey = null;
      invalidateReports();
    }
    publish();
  };
  subscriptions.push(readAccess.subscribe(revoke), writeAccess.subscribe(revoke));
  function candidate() {
    if (!editing) throw new AppError(AppErrorKind.PROTOCOL, "No editing session", { status: 422 });
    const result = prepareRuleSetCandidate(editing);
    if (!result.valid) {
      issues = result.issues;
      publish();
      throw new AppError(AppErrorKind.PROTOCOL, "Invalid rule candidate", { status: 422 });
    }
    return result.candidate;
  }
  function accept(result: RuleMutationResult) {
    if (!allowed()) return;
    if (result.kind === RULE_MUTATION.SaveDraft)
      install(beginRuleSetEditing(storedDraftSnapshot(result.draft, binding)), {
        id: result.draft.id,
        revision: result.draft.revision,
      });
    else if (result.kind === RULE_MUTATION.DeleteDraft && savedIdentity?.id === result.draftId) {
      editing = null;
      savedIdentity = null;
      selectedKey = null;
      invalidateReports();
    } else if (result.kind === RULE_MUTATION.FreezeVersion) invalidateReports();
  }
  async function run(input: RuleMutationInput) {
    assertEditable();
    performing = true;
    publish();
    try {
      const result = await operation.run(input);
      accept(result);
      return result;
    } finally {
      performing = false;
      publish();
    }
  }
  return Object.freeze({
    getSnapshot: state.getSnapshot,
    subscribe: state.subscribe,
    refreshSource() {
      if (!readable())
        throw new AppError(AppErrorKind.FORBIDDEN, "Rule reading unavailable", { status: 403 });
      return resources.source.load(binding.id);
    },
    begin(discard = false) {
      guardDiscard(discard);
      const source = resources.source.getSnapshot();
      if (!("data" in source))
        throw new AppError(AppErrorKind.PROTOCOL, "No source snapshot", { status: 422 });
      install(beginRuleSetEditing(source.data), null);
    },
    async openDraft(id: string, discard = false) {
      guardDiscard(discard);
      const ticket = ++generation;
      opening = ticket;
      publish();
      try {
        const draft = await resources.saved.load(id);
        if (!allowed() || opening !== ticket)
          throw new AppError(AppErrorKind.CANCELLED, "Draft owner changed");
        install(beginRuleSetEditing(storedDraftSnapshot(draft, binding)), {
          id: draft.id,
          revision: draft.revision,
        });
        return draft;
      } finally {
        if (opening === ticket) opening = 0;
        publish();
      }
    },
    select(formKey: string | null) {
      assertEditable();
      if (formKey !== null && !editing?.records.some((record) => record.formKey === formKey))
        throw new AppError(AppErrorKind.PROTOCOL, "Missing local rule", { status: 404 });
      selectedKey = formKey;
      publish();
    },
    change(formKey: string, rule: TypedRuleDraft) {
      assertEditable();
      if (!editing) throw new AppError(AppErrorKind.PROTOCOL, "No editing session");
      editing = updateRuleInSet(editing, formKey, rule);
      invalidateReports();
      publish();
    },
    add(formKey: string, rule: TypedRuleDraft) {
      assertEditable();
      if (!editing) throw new AppError(AppErrorKind.PROTOCOL, "No editing session");
      editing = addRuleToSet(editing, formKey, rule);
      selectedKey = formKey;
      invalidateReports();
      publish();
    },
    remove(formKey: string) {
      assertEditable();
      if (!editing) throw new AppError(AppErrorKind.PROTOCOL, "No editing session");
      editing = removeRuleFromSet(editing, formKey);
      if (selectedKey === formKey) selectedKey = null;
      invalidateReports();
      publish();
    },
    discard() {
      assertEditable();
      if (editing) install(beginRuleSetEditing(editing.baseline), savedIdentity);
    },
    close(discard = false) {
      guardDiscard(discard);
      editing = null;
      savedIdentity = null;
      selectedKey = null;
      invalidateReports();
      publish();
    },
    validate() {
      assertEditable();
      return resources.validation.load({ generation, candidate: candidate() });
    },
    compare() {
      assertEditable();
      return resources.diff.load({ generation, candidate: candidate() });
    },
    save() {
      assertEditable();
      return run({
        kind: RULE_MUTATION.SaveDraft,
        draftId: savedIdentity?.id ?? null,
        expectedRevision: savedIdentity?.revision ?? null,
        candidate: candidate(),
      });
    },
    deleteDraft() {
      assertEditable();
      if (!savedIdentity)
        throw new AppError(AppErrorKind.PROTOCOL, "No persisted draft", { status: 422 });
      return run({
        kind: RULE_MUTATION.DeleteDraft,
        draftId: savedIdentity.id,
        expectedRevision: savedIdentity.revision,
      });
    },
    freeze(name: string, note: string) {
      assertEditable();
      const report = resources.validation.getSnapshot();
      const versionName = name.trim();
      if (
        !editing ||
        ruleSetIsDirty(editing) ||
        !savedIdentity ||
        report.status !== "ready" ||
        !report.data.isPublishable ||
        !hasNonBlankWireContent(versionName)
      )
        throw new AppError(AppErrorKind.PROTOCOL, "Save and validate this candidate first", {
          status: 422,
          code: "rule_freeze_not_ready",
        });
      return run({
        kind: RULE_MUTATION.FreezeVersion,
        draftId: savedIdentity.id,
        expectedRevision: savedIdentity.revision,
        validationId: report.data.validationId,
        candidateChecksum: report.data.candidateChecksum,
        name: versionName,
        note,
      });
    },
    async inspect() {
      if (!allowed())
        throw new AppError(AppErrorKind.FORBIDDEN, "Rule editing unavailable", { status: 403 });
      const original = operation.getSnapshot();
      if (
        performing ||
        opening !== 0 ||
        original.inspecting ||
        !original.operation ||
        !DRAFT_MUTATIONS.has(original.operation.kind)
      )
        throw new AppError(AppErrorKind.DUPLICATE, "Inspect the originating rule workflow");
      performing = true;
      publish();
      try {
        const value = await operation.inspect();
        if (value.status === "completed") accept(value.result);
        return value;
      } finally {
        performing = false;
        publish();
      }
    },
    cancel() {
      opening = 0;
      resources.cancel();
      operation.cancel();
      publish();
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      editing = null;
      savedIdentity = null;
      subscriptions.forEach((unsubscribe) => unsubscribe());
      resources.dispose();
      state.set(snapshot());
      state.complete();
    },
  });
}
