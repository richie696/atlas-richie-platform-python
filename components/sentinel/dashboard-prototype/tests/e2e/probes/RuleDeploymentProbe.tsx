import { StateStore, AppError, AppErrorKind } from "@richie696/react-framework";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import { AstryxProvider } from "../../../src/app/providers/AstryxProvider";
import {
  createRuleOperation,
  createRuleDeploymentWorkflow,
  RuleDeploymentPanel,
} from "../../../src/features/rules/workspace";
import type {
  RuleSetVersion,
  RulePublication,
  PublicationReceiptPage,
} from "../../../src/features/rules/model/ruleDeployment";
import type {
  ActivationSchedule,
  RuleActivationPlan,
} from "../../../src/features/rules/model/ruleActivation";
import type {
  RuleMutation,
  RuleMutationResult,
  RuleOperationObservation,
} from "../../../src/features/rules/model/ruleSetOperations";
import type { QueryAccess } from "../../../src/shared/state/ownedQueryResource";
import type { QuerySnapshot } from "../../../src/shared/state/queryResource";
import type { RuleSetSnapshot } from "../../../src/features/rules/model/ruleSet";
import { ruleSet } from "../../fixtures/ruleSets";
const session = "deployment-probe-session";
const daily: RuleSetVersion = {
  id: "version-one",
  bindingId: ruleSet.binding.id,
  kind: ruleSet.binding.kind,
  profile: ruleSet.binding.profile,
  baseVersionId: null,
  checksum: ruleSet.checksum,
  name: "Daily",
  note: "",
  createdAtMs: ruleSet.asOfMs,
  createdById: "test-actor",
  records: ruleSet.records,
};
const event: RuleSetVersion = {
  ...daily,
  id: "event-version",
  checksum: "event-checksum",
  name: "Event",
  baseVersionId: daily.id,
  records: [ruleSet.records[0]],
};
const phases = { state: "succeeded" as const, observedAtMs: ruleSet.asOfMs, reason: null };
const waiting = { state: "awaiting" as const, observedAtMs: null, reason: null };
/** Synthetic typed Port only. Browser interactions exercise production components, not HTTP/backend persistence. */
export function createRuleDeploymentTopology() {
  const read = new StateStore<QueryAccess>({ ownerKey: session, allowed: true }),
    write = new StateStore<QueryAccess>({ ownerKey: session, allowed: true });
  const source = new StateStore<QuerySnapshot<RuleSetSnapshot>>({
    status: "ready",
    key: "source",
    receivedAt: ruleSet.asOfMs,
    data: ruleSet,
  });
  const counts = new StateStore({
    writes: 0,
    lookups: 0,
    lastKind: "",
    lastTarget: "",
    lastRestore: "",
    lastReason: "",
    lastPlan: null as ActivationSchedule | null,
  });
  const readAccess = { read: read.getSnapshot, subscribe: read.subscribe },
    writeAccess = { read: write.getSnapshot, subscribe: write.subscribe };
  let key = 0,
    unknown = false,
    inventoryUnknown = false,
    lookup: "pending" | "not-found" | "completed" = "completed",
    latest: RuleMutation | null = null,
    result: RuleMutationResult | null = null;
  let publications: RulePublication[] = [],
    plans: RuleActivationPlan[] = [];
  const collection = <Value,>(items: readonly Value[]) => ({
    bindingId: ruleSet.binding.id,
    asOfMs: ruleSet.asOfMs,
    items,
  });
  function complete(mutation: RuleMutation): RuleOperationObservation {
    if (mutation.kind === "publish") {
      const publication: RulePublication = {
        id: "publication-" + counts.getSnapshot().writes,
        bindingId: mutation.bindingId,
        targetVersionId: mutation.versionId,
        targetChecksum: mutation.versionChecksum,
        baseVersionId: mutation.expectedVersionId,
        createdAtMs: ruleSet.asOfMs,
        validation: phases,
        configurationWrite: waiting,
        readBack: waiting,
      };
      publications.push(publication);
      result = { kind: "publish", publication };
    } else if (mutation.kind === "create_plan") {
      const plan: RuleActivationPlan = {
        ...mutation.schedule,
        id: "plan-one",
        revision: "plan-r1",
        state: "pending",
        activationPublicationId: null,
        restorePublicationId: null,
      };
      plans = [plan];
      result = { kind: "create_plan", plan };
    } else if (mutation.kind === "cancel_plan") {
      const plan: RuleActivationPlan = { ...plans[0], revision: "plan-r2", state: "cancelled" };
      plans = [plan];
      result = { kind: "cancel_plan", plan };
    } else throw new Error("Unexpected probe command");
    return {
      status: "completed",
      bindingId: mutation.bindingId,
      requestKey: mutation.requestKey,
      result,
    };
  }
  const operation = createRuleOperation(
    ruleSet.binding.id,
    {
      async mutateRuleSet(mutation) {
        counts.set({
          ...counts.getSnapshot(),
          writes: counts.getSnapshot().writes + 1,
          lastKind: mutation.kind,
          lastTarget:
            mutation.kind === "publish"
              ? mutation.versionId
              : mutation.kind === "create_plan"
                ? mutation.schedule.versionId
                : "",
          lastRestore: mutation.kind === "create_plan" ? mutation.schedule.restoreVersionId : "",
          lastReason:
            mutation.kind === "publish" || mutation.kind === "cancel_plan" ? mutation.reason : "",
          lastPlan: mutation.kind === "create_plan" ? mutation.schedule : null,
        });
        latest = mutation;
        const value = complete(mutation);
        if (unknown) throw new AppError(AppErrorKind.NETWORK, "PRIVATE-DEPLOYMENT-ERROR");
        return value;
      },
      async readRuleOperation(bindingId, requestKey) {
        counts.set({ ...counts.getSnapshot(), lookups: counts.getSnapshot().lookups + 1 });
        if (!latest || !result) throw new Error("No original operation");
        return lookup === "completed"
          ? { status: "completed", bindingId, requestKey, result }
          : { status: lookup, bindingId, requestKey };
      },
    },
    writeAccess,
    () => "deployment-probe-" + ++key,
  );
  const workflow = createRuleDeploymentWorkflow(
    ruleSet.binding,
    {
      async readVersions() {
        return collection([daily, event]);
      },
      async readVersion(binding, id) {
        const version = [daily, event].find((item) => item.id === id);
        if (!version) throw new AppError(AppErrorKind.PROTOCOL, "Missing", { status: 404 });
        return version;
      },
      async readPublications() {
        return collection(publications);
      },
      async readPublicationTarget(bindingId) {
        return { bindingId, target: null };
      },
      async readPublication(binding, id) {
        const value = publications.find((item) => item.id === id);
        if (!value) throw new AppError(AppErrorKind.PROTOCOL, "Missing", { status: 404 });
        return value;
      },
      async readReceipts(query): Promise<PublicationReceiptPage> {
        const publication = publications.find((item) => item.id === query.publicationId);
        if (!publication) throw new AppError(AppErrorKind.PROTOCOL, "Missing", { status: 404 });
        return {
          publicationId: query.publicationId,
          bindingId: ruleSet.binding.id,
          page: query.page,
          pageSize: query.pageSize,
          asOfMs: ruleSet.asOfMs,
          expected: inventoryUnknown ? null : 2,
          total: 2,
          inventorySource: inventoryUnknown ? null : "test-inventory",
          applied: 1,
          pending: 0,
          failed: 0,
          unknown: inventoryUnknown ? 1 : 0,
          restartRequired: inventoryUnknown ? 0 : 1,
          items: ["applied", inventoryUnknown ? "unknown" : "restart_required"].map(
            (state, index) => ({
              instanceId: "instance-" + index,
              processEpoch: state === "unknown" ? null : "current-" + index,
              loadedProcessEpoch: state === "unknown" ? null : "current-" + index,
              targetVersionId: publication.targetVersionId,
              loadedVersionId: state === "unknown" ? null : publication.targetVersionId,
              loadedChecksum: state === "unknown" ? null : publication.targetChecksum,
              appliedAtMs: state === "unknown" ? null : ruleSet.asOfMs,
              lastReportAtMs: state === "unknown" ? null : ruleSet.asOfMs,
              state: state as "applied" | "restart_required" | "unknown",
            }),
          ),
        };
      },
      async readPlans() {
        return collection(plans);
      },
    },
    readAccess,
    writeAccess,
    operation,
    source,
    () => ruleSet.asOfMs,
  );
  return {
    workflow,
    source,
    counts,
    read,
    write,
    setUnknown() {
      unknown = true;
    },
    setInventoryUnknown() {
      inventoryUnknown = true;
    },
    setLookup(value: typeof lookup) {
      lookup = value;
    },
    changeSource() {
      source.set({
        status: "ready",
        key: "source",
        receivedAt: ruleSet.asOfMs,
        data: {
          ...ruleSet,
          versionId: "external-version",
          checksum: "external-checksum",
          sourceRevision: "external-revision",
        },
      });
    },
    dispose() {
      workflow.dispose();
      operation.dispose();
      source.complete();
      read.complete();
      write.complete();
      counts.complete();
    },
  };
}
/** StrictMode production surface with explicit diagnostic controls outside the product UI. */
export function RuleDeploymentProbe({
  topology,
}: {
  readonly topology: ReturnType<typeof createRuleDeploymentTopology>;
}) {
  const state = useExternalSnapshot(topology.workflow),
    counts = useExternalSnapshot(topology.counts);
  return (
    <AstryxProvider>
      <div data-test-effects>
        <button data-deploy-inventory-unknown onClick={topology.setInventoryUnknown}>
          Unknown inventory
        </button>
        <button data-deploy-unknown onClick={topology.setUnknown}>
          Unknown transport outcome
        </button>
        {(["pending", "not-found", "completed"] as const).map((value) => (
          <button key={value} data-deploy-lookup={value} onClick={() => topology.setLookup(value)}>
            {value}
          </button>
        ))}
        <button data-deploy-source-change onClick={topology.changeSource}>
          External source update
        </button>
        <button
          data-deploy-revoke
          onClick={() => topology.write.set({ ownerKey: session, allowed: false })}
        >
          Revoke edit
        </button>
        <button
          data-deploy-grant
          onClick={() => topology.write.set({ ownerKey: session, allowed: true })}
        >
          Grant edit
        </button>
        <button
          data-deploy-owner-change
          onClick={() => topology.read.set({ ownerKey: "other-session", allowed: true })}
        >
          Change owner
        </button>
      </div>
      <RuleDeploymentPanel
        bindingId={ruleSet.binding.id}
        workflow={topology.workflow}
        view="publications"
      />
      <output data-deploy-summary style={{ display: "block", overflowWrap: "anywhere" }}>
        {JSON.stringify({
          ...counts,
          operation: state.operation.command.status,
          inspecting: state.operation.inspecting,
          readable: state.readable,
          writable: state.writable,
          locked: state.locked,
          versions: state.versions.status,
          version: state.version.status,
          sourceVersion: "data" in state.source ? state.source.data.versionId : null,
          publicationId: state.publicationId,
          publication: state.publication.status,
          receipts: state.receipts.status,
          plans: state.plans.status,
        })}
      </output>
    </AstryxProvider>
  );
}
