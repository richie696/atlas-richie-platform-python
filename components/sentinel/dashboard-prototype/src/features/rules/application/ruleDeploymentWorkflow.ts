import { AppError, AppErrorKind, StateStore } from "@richie696/react-framework";
import { hasNonBlankWireContent } from "../../../core/api/protocol/common";
import type { QueryAccessObserver } from "../../../shared/state/ownedQueryResource";
import type { QuerySnapshot } from "../../../shared/state/queryResource";
import type { RuleBinding, RuleSetSnapshot } from "../model/ruleSet";
import type { RuleMutationTarget } from "../model/ruleSetOperations";
import {
  canCancelRulePlan,
  activationScheduleIssues,
  type ActivationSchedule,
} from "../model/ruleActivation";
import {
  RULE_MUTATION,
  type RuleMutationInput,
  type RuleMutationResult,
} from "../model/ruleSetOperations";
import {
  createRuleDeploymentResources,
  type RuleDeploymentReadPort,
} from "./ruleDeploymentResources";
import { HIDDEN_RULE_OPERATION, type RuleOperation } from "./ruleOperation";

/** Source state has one owner; this projection does not load or copy a second authoritative snapshot. */
export interface RuleSourceObservation {
  readonly getSnapshot: () => QuerySnapshot<RuleSetSnapshot>;
  readonly subscribe: (listener: () => void) => () => void;
}
/** Facts captured when the user opens a confirmation, not silently replaced while it is open. */
export type RulePublicationIntent = Omit<
  Extract<RuleMutationInput, { readonly kind: "publish" }>,
  "kind" | "reason"
>;
export const DEFAULT_RECEIPT_PAGE_SIZE = 20;
const DEPLOYMENT_MUTATIONS: ReadonlySet<string> = new Set([
  RULE_MUTATION.Publish,
  RULE_MUTATION.CreatePlan,
  RULE_MUTATION.CancelPlan,
]);
const MAX_DEPLOYMENT_REASON_LENGTH = 1024;
const notReady = () =>
  new AppError(AppErrorKind.PROTOCOL, "Read current deployment facts first", {
    status: 422,
    code: "rule_deployment_not_ready",
  });
function fresh<Value>(value: QuerySnapshot<Value>): boolean {
  return value.status === "ready" || value.status === "empty";
}
/**
 * Version publication, rollback-as-publication and persistent schedule commands for one binding/session.
 * Reuse the binding command owner. Neither successful dispatch nor receipt reads update the live source optimistically.
 * Caller injects the source projection and clock; the browser never executes activation/restore timers.
 */
export function createRuleDeploymentWorkflow(
  binding: RuleBinding,
  port: RuleDeploymentReadPort,
  readAccess: QueryAccessObserver,
  writeAccess: QueryAccessObserver,
  operation: RuleOperation,
  source: RuleSourceObservation,
  clock: () => number,
) {
  const ownerKey = readAccess.read().ownerKey;
  const resources = createRuleDeploymentResources(binding, port, readAccess);
  let disposed = false,
    performing = false;
  let versionId: string | null = null,
    publicationId: string | null = null;
  const readable = () =>
    !disposed && readAccess.read().allowed && readAccess.read().ownerKey === ownerKey;
  const writable = () =>
    readable() && writeAccess.read().allowed && writeAccess.read().ownerKey === ownerKey;
  const locked = () =>
    performing ||
    operation.getSnapshot().inspecting ||
    ["pending", "result-unknown"].includes(operation.getSnapshot().command.status);
  const idle = Object.freeze({ status: "idle" as const });
  const snapshot = () => ({
    readable: readable(),
    writable: writable(),
    locked: writable() && locked(),
    versionId: readable() ? versionId : null,
    publicationId: readable() ? publicationId : null,
    source: readable() ? source.getSnapshot() : idle,
    versions: readable() ? resources.versions.getSnapshot() : idle,
    version: readable() ? resources.version.getSnapshot() : idle,
    publications: readable() ? resources.publications.getSnapshot() : idle,
    publication: readable() ? resources.publication.getSnapshot() : idle,
    receipts: readable() ? resources.receipts.getSnapshot() : idle,
    plans: readable() ? resources.plans.getSnapshot() : idle,
    publicationTarget: readable() ? resources.publicationTarget.getSnapshot() : idle,
    operation: writable() ? operation.getSnapshot() : HIDDEN_RULE_OPERATION,
  });
  const state = new StateStore(snapshot());
  const publish = () => state.set(snapshot());
  const owned = [
    resources.versions,
    resources.version,
    resources.publications,
    resources.publication,
    resources.receipts,
    resources.plans,
    resources.publicationTarget,
  ];
  const subscriptions = [...owned, source, operation].map((value) => value.subscribe(publish));
  const revoke = () => {
    if (!readable()) {
      versionId = null;
      publicationId = null;
      resources.reset();
    }
    publish();
  };
  subscriptions.push(readAccess.subscribe(revoke), writeAccess.subscribe(revoke));
  function assertRead() {
    if (!readable())
      throw new AppError(AppErrorKind.FORBIDDEN, "Rule deployment reading unavailable", {
        status: 403,
      });
  }
  function assertWrite() {
    if (!writable())
      throw new AppError(AppErrorKind.FORBIDDEN, "Rule deployment unavailable", { status: 403 });
    if (locked()) throw new AppError(AppErrorKind.DUPLICATE, "Unresolved rule action");
  }
  function accept(result: RuleMutationResult) {
    if (!writable()) return;
    if (result.kind === RULE_MUTATION.Publish) {
      publicationId = result.publication.id;
      resources.publication.reset();
      resources.receipts.reset();
      resources.publications.reset();
    } else if (result.kind === RULE_MUTATION.CreatePlan || result.kind === RULE_MUTATION.CancelPlan)
      resources.plans.reset();
    else if (result.kind === RULE_MUTATION.ConfigureTarget) resources.publicationTarget.reset();
    publish();
  }
  async function run(input: RuleMutationInput) {
    assertWrite();
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
  function reason(value: string) {
    const text = value.trim();
    if (!hasNonBlankWireContent(text) || text.length > MAX_DEPLOYMENT_REASON_LENGTH)
      throw notReady();
    return text;
  }
  async function loadReceipts(page = 1, pageSize = DEFAULT_RECEIPT_PAGE_SIZE) {
    assertRead();
    const selected = resources.publication.getSnapshot();
    if (!fresh(selected) || !("data" in selected) || selected.data.id !== publicationId)
      throw notReady();
    return resources.receipts.load({ publication: selected.data, page, pageSize });
  }
  function preparePublication(): RulePublicationIntent {
    assertWrite();
    const current = source.getSnapshot(),
      target = resources.version.getSnapshot();
    if (
      !fresh(current) ||
      !("data" in current) ||
      target.status !== "ready" ||
      target.data.id !== versionId ||
      current.data.binding.id !== binding.id ||
      current.data.binding.profile !== binding.profile
    )
      throw notReady();
    return Object.freeze({
      versionId: target.data.id,
      versionChecksum: target.data.checksum,
      expectedVersionId: current.data.versionId,
      expectedChecksum: current.data.checksum,
      expectedSourceRevision: current.data.sourceRevision,
    });
  }
  return Object.freeze({
    binding,
    getSnapshot: state.getSnapshot,
    subscribe: state.subscribe,
    refreshCatalog() {
      assertRead();
      return Promise.all([
        resources.versions.load(binding.id),
        resources.publications.load(binding.id),
        resources.plans.load(binding.id),
        resources.publicationTarget.load(binding.id),
      ]);
    },
    refreshVersions() {
      assertRead();
      return resources.versions.load(binding.id);
    },
    refreshPlans() {
      assertRead();
      return resources.plans.load(binding.id);
    },
    refreshPublicationTarget() {
      assertRead();
      return resources.publicationTarget.load(binding.id);
    },
    configurePublicationTarget(target: RuleMutationTarget) {
      assertWrite();
      const sourceSnapshot = source.getSnapshot();
      const current = resources.publicationTarget.getSnapshot();
      if (
        !fresh(sourceSnapshot) ||
        !("data" in sourceSnapshot) ||
        sourceSnapshot.data.binding.id !== binding.id ||
        !sourceSnapshot.data.sourceRevision ||
        target.sourceId !== binding.sourceId ||
        (current.status !== "ready" && current.status !== "empty")
      )
        throw notReady();
      const expectedTargetRevision =
        current.status === "ready" && "data" in current && current.data.target !== null
          ? current.data.targetRevision
          : null;
      return run({
        kind: RULE_MUTATION.ConfigureTarget,
        expectedSourceRevision: sourceSnapshot.data.sourceRevision,
        expectedTargetRevision,
        target,
      });
    },
    async selectVersion(id: string | null) {
      assertRead();
      versionId = id;
      resources.version.reset();
      publish();
      if (id !== null) return resources.version.load(id);
    },
    refreshVersion() {
      assertRead();
      if (!versionId) throw notReady();
      return resources.version.load(versionId);
    },
    async selectPublication(id: string | null) {
      assertRead();
      publicationId = id;
      resources.publication.reset();
      resources.receipts.reset();
      publish();
      if (id !== null) return resources.publication.load(id);
    },
    refreshPublication() {
      assertRead();
      if (!publicationId) throw notReady();
      return resources.publication.load(publicationId);
    },
    loadReceipts,
    preparePublication,
    publishVersion(reasonText: string, expected: RulePublicationIntent) {
      const current = preparePublication();
      if (
        !expected ||
        current.versionId !== expected.versionId ||
        current.versionChecksum !== expected.versionChecksum ||
        current.expectedVersionId !== expected.expectedVersionId ||
        current.expectedChecksum !== expected.expectedChecksum ||
        current.expectedSourceRevision !== expected.expectedSourceRevision
      )
        throw new AppError(AppErrorKind.PROTOCOL, "Publication confirmation changed", {
          status: 409,
          code: "conflict",
        });
      return run({ kind: RULE_MUTATION.Publish, ...expected, reason: reason(reasonText) });
    },
    createPlan(schedule: ActivationSchedule) {
      assertWrite();
      const versions = resources.versions.getSnapshot(),
        plans = resources.plans.getSnapshot();
      if (
        !fresh(versions) ||
        !("data" in versions) ||
        !fresh(plans) ||
        !("data" in plans) ||
        schedule.bindingId !== binding.id ||
        !versions.data.items.some((value) => value.id === schedule.versionId) ||
        !versions.data.items.some((value) => value.id === schedule.restoreVersionId) ||
        activationScheduleIssues(schedule, clock(), plans.data.items).length
      )
        throw notReady();
      return run({ kind: RULE_MUTATION.CreatePlan, schedule });
    },
    cancelPlan(id: string, revision: string, reasonText: string) {
      assertWrite();
      const plans = resources.plans.getSnapshot();
      if (!fresh(plans) || !("data" in plans)) throw notReady();
      const plan = plans.data.items.find((value) => value.id === id);
      if (!plan || plan.revision !== revision || !canCancelRulePlan(plan)) throw notReady();
      return run({
        kind: RULE_MUTATION.CancelPlan,
        planId: id,
        expectedRevision: revision,
        reason: reason(reasonText),
      });
    },
    async inspect() {
      if (!writable())
        throw new AppError(AppErrorKind.FORBIDDEN, "Rule deployment unavailable", { status: 403 });
      const original = operation.getSnapshot();
      if (
        performing ||
        original.inspecting ||
        !original.operation ||
        !DEPLOYMENT_MUTATIONS.has(original.operation.kind)
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
      resources.cancel();
      operation.cancel();
      publish();
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      versionId = null;
      publicationId = null;
      subscriptions.forEach((unsubscribe) => unsubscribe());
      resources.dispose();
      state.set(snapshot());
      state.complete();
    },
  });
}
