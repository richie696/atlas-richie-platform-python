import { http, HttpResponse } from "msw";
import { CONSOLE_HEADER } from "../../../core/api/protocol/common";
import { readMockPrincipal } from "../../../core/api/mock/mockRole";
import {
  ActivationPlanSchema,
  RuleBindingPageSchema,
  RuleBindingRegistrationRequestSchema,
  RuleBindingSchema,
  RuleCommandRequestSchema,
  RuleOperationObservationSchema,
  RuleSetCandidateSchema,
  RuleSetCollectionSchema,
  RuleSetSnapshotSchema,
  StoredRuleDraftSchema,
  RuleValidationReportSchema,
} from "../api/ruleSetWire";
import type {
  RuleBindingRegistrationTarget,
  RuleSourceOption,
} from "../model/ruleBindingRegistration";
import type { RuleBinding, RuleRecord, RuleSetSnapshot } from "../model/ruleSet";
import type { VersionedRulePublicationTarget } from "../model/rulePublicationTarget";
import { RULE_MUTATION, RULE_REJECTION } from "../model/ruleSetOperations";
import { activationScheduleIssues, SCHEDULE_ISSUE } from "../model/ruleActivation";

export type RuleSetMockScenario = {
  readonly environment: { readonly id: string };
  readonly applications: readonly { readonly id: string }[];
  readonly instances: readonly {
    readonly id: string;
    readonly appId: string;
    readonly processEpoch: string;
  }[];
  readonly inventorySource: string;
  readonly bindings: readonly RuleBinding[];
  readonly snapshots: readonly RuleSetSnapshot[];
  readonly deployment: {
    readonly baselineVersion: { readonly id: string; readonly name: string; readonly note: string };
    readonly baselinePublication: {
      readonly id: string;
      readonly createdAt: string;
      readonly phaseState: "succeeded";
    };
    readonly eventVersion: {
      readonly id: string;
      readonly bindingId: string;
      readonly baseVersionId: string;
      readonly checksum: string;
      readonly name: string;
      readonly note: string;
      readonly createdAtOffsetMs: number;
      readonly records: readonly RuleRecord[];
    };
    readonly eventPublication: {
      readonly id: string;
      readonly createdAtOffsetMs: number;
      readonly phaseState: "succeeded";
    };
    readonly receipt: {
      readonly publicationId: string;
      readonly appliedInstanceId: string;
      readonly appliedState: "applied";
      readonly pendingState: "pending";
      readonly appliedAtOffsetMs: number;
      readonly lastReportAtOffsetMs: number;
    };
    readonly initialPlan: {
      readonly id: string;
      readonly revision: string;
      readonly versionId: string;
      readonly restoreVersionId: string;
      readonly activateAfterMs: number;
      readonly durationMs: number;
      readonly timeZone: string;
      readonly state: "pending";
    };
  };
};

const instant = (at: number) => new Date(at).toISOString();
const headers = (requestId: string | null) => {
  const result = new Headers({ "Content-Type": "application/json" });
  if (requestId) result.set(CONSOLE_HEADER.RequestId, requestId);
  result.set(CONSOLE_HEADER.Csrf, "M".repeat(48));
  return result;
};
const response = (requestId: string | null, body: unknown, status = 200) =>
  new HttpResponse(JSON.stringify(body), { status, headers: headers(requestId) });
function demoAdminAllowed(): boolean {
  return readMockPrincipal() === "admin";
}
const forbidden = (requestId: string | null) =>
  response(requestId, { error: { code: "forbidden", requestId } }, 403);

/** State is ephemeral and process-local by design: this is a demo simulator, never durable persistence. */
function createRuleMockState(
  scenario: RuleSetMockScenario,
  adminAccountId: string,
  clock: () => number,
) {
  const bindings = scenario.bindings.filter(
    (binding) =>
      binding.environmentId === scenario.environment.id &&
      scenario.applications.some((application) => application.id === binding.appId),
  );
  const bindingIds = new Set(bindings.map((binding) => binding.id));
  const snapshots = new Map(
    scenario.snapshots
      .filter((item) => bindingIds.has(item.binding.id))
      .map((item) => [item.binding.id, item]),
  );
  const initialBindings = [...bindings];
  const initialSnapshots = [...snapshots.entries()];
  const drafts = new Map<string, Record<string, unknown>>();
  const versions = new Map<string, Record<string, unknown>>();
  const publications = new Map<string, Record<string, unknown>>();
  const receipts = new Map<string, readonly Record<string, unknown>[]>();
  const plans = new Map<string, Record<string, unknown>>();
  const targets = new Map<string, VersionedRulePublicationTarget>();
  const operations = new Map<string, Record<string, unknown>>();
  const registrationOperations = new Map<
    string,
    { readonly fingerprint: string; readonly binding: RuleBinding }
  >();
  const versionKey = (bindingId: string, versionId: string) => `${bindingId}:${versionId}`;
  function pendingReceipts(bindingId: string, targetVersionId: string) {
    const binding = snapshots.get(bindingId)?.binding;
    if (!binding) return [];
    return scenario.instances
      .filter((instance) => instance.appId === binding.appId)
      .map((instance) => ({
        instanceId: instance.id,
        processEpoch: instance.processEpoch,
        loadedProcessEpoch: null,
        targetVersionId,
        loadedVersionId: null,
        loadedChecksum: null,
        appliedAt: null,
        lastReportAt: null,
        state: "pending" as const,
      }));
  }
  let sequence = 0;
  function seedDeploymentFacts() {
    versions.clear();
    publications.clear();
    receipts.clear();
    plans.clear();
    for (const snapshot of snapshots.values()) {
      const baseline = {
        id: scenario.deployment.baselineVersion.id,
        bindingId: snapshot.binding.id,
        kind: snapshot.binding.kind,
        profile: snapshot.binding.profile,
        baseVersionId: null,
        checksum: snapshot.checksum,
        name: scenario.deployment.baselineVersion.name,
        note: scenario.deployment.baselineVersion.note,
        createdAt: instant(snapshot.asOfMs),
        createdById: adminAccountId,
        records: snapshot.records,
      };
      versions.set(versionKey(snapshot.binding.id, baseline.id), baseline);
    }

    const bindingId = scenario.deployment.eventVersion.bindingId;
    const snapshot = snapshots.get(bindingId);
    const baselineVersion = versions.get(
      versionKey(bindingId, scenario.deployment.baselineVersion.id),
    );
    if (!snapshot || !baselineVersion)
      throw new Error("The rule demo scenario must seed the event binding and baseline snapshot");
    if (scenario.deployment.eventVersion.baseVersionId !== baselineVersion.id)
      throw new Error("The rule demo event version must reference its seeded baseline version");
    const createdAt = scenario.deployment.baselinePublication.createdAt;
    publications.set(scenario.deployment.baselinePublication.id, {
      id: scenario.deployment.baselinePublication.id,
      bindingId,
      targetVersionId: baselineVersion.id,
      targetChecksum: baselineVersion.checksum,
      baseVersionId: null,
      createdAt,
      validation: {
        state: scenario.deployment.baselinePublication.phaseState,
        observedAt: createdAt,
        reason: null,
      },
      configurationWrite: {
        state: scenario.deployment.baselinePublication.phaseState,
        observedAt: createdAt,
        reason: null,
      },
      readBack: {
        state: scenario.deployment.baselinePublication.phaseState,
        observedAt: createdAt,
        reason: null,
      },
    });

    const { createdAtOffsetMs: eventCreatedAtOffsetMs, ...eventVersionFacts } =
      scenario.deployment.eventVersion;
    const eventVersion = {
      ...baselineVersion,
      ...eventVersionFacts,
      createdAt: instant(snapshot.asOfMs + eventCreatedAtOffsetMs),
    };
    versions.set(versionKey(bindingId, eventVersion.id), eventVersion);

    const eventPublicationId = scenario.deployment.eventPublication.id;
    if (scenario.deployment.receipt.publicationId !== eventPublicationId)
      throw new Error("The rule demo receipt must reference its seeded event publication");
    const eventPublicationAt = instant(
      snapshot.asOfMs + scenario.deployment.eventPublication.createdAtOffsetMs,
    );
    publications.set(eventPublicationId, {
      id: eventPublicationId,
      bindingId,
      targetVersionId: eventVersion.id,
      targetChecksum: eventVersion.checksum,
      baseVersionId: baselineVersion.id,
      createdAt: eventPublicationAt,
      validation: {
        state: scenario.deployment.eventPublication.phaseState,
        observedAt: eventPublicationAt,
        reason: null,
      },
      configurationWrite: {
        state: scenario.deployment.eventPublication.phaseState,
        observedAt: eventPublicationAt,
        reason: null,
      },
      readBack: {
        state: scenario.deployment.eventPublication.phaseState,
        observedAt: eventPublicationAt,
        reason: null,
      },
    });
    const observedAt = clock();
    const deploymentInstances = scenario.instances.filter(
      (instance) => instance.appId === snapshot.binding.appId,
    );
    if (
      !deploymentInstances.some(
        (instance) => instance.id === scenario.deployment.receipt.appliedInstanceId,
      )
    )
      throw new Error("The rule demo receipt must reference an instance in its bound application");
    receipts.set(
      eventPublicationId,
      pendingReceipts(bindingId, eventVersion.id).map((receipt) => {
        if (receipt.instanceId !== scenario.deployment.receipt.appliedInstanceId) return receipt;
        return {
          ...receipt,
          loadedProcessEpoch: receipt.processEpoch,
          loadedVersionId: eventVersion.id,
          loadedChecksum: eventVersion.checksum,
          appliedAt: instant(observedAt + scenario.deployment.receipt.appliedAtOffsetMs),
          lastReportAt: instant(observedAt + scenario.deployment.receipt.lastReportAtOffsetMs),
          state: scenario.deployment.receipt.appliedState,
        };
      }),
    );

    const planStart = clock() + scenario.deployment.initialPlan.activateAfterMs;
    const plan = {
      id: scenario.deployment.initialPlan.id,
      revision: scenario.deployment.initialPlan.revision,
      bindingId,
      versionId: scenario.deployment.initialPlan.versionId,
      restoreVersionId: scenario.deployment.initialPlan.restoreVersionId,
      activateAt: instant(planStart),
      deactivateAt: instant(planStart + scenario.deployment.initialPlan.durationMs),
      timeZone: scenario.deployment.initialPlan.timeZone,
      state: scenario.deployment.initialPlan.state,
      activationPublicationId: null,
      restorePublicationId: null,
    };
    if (
      !versions.has(versionKey(bindingId, plan.versionId)) ||
      !versions.has(versionKey(bindingId, plan.restoreVersionId))
    )
      throw new Error("The rule demo plan must reference versions from its own binding");
    const valid = ActivationPlanSchema.safeParse(plan);
    if (valid.success) plans.set(plan.id, valid.data);
  }
  seedDeploymentFacts();
  return {
    snapshots,
    bindings,
    drafts,
    versions,
    publications,
    receipts,
    plans,
    targets,
    operations,
    registrationOperations,
    versionKey,
    pendingReceipts,
    next(prefix: string) {
      sequence += 1;
      return `${prefix}-${sequence}`;
    },
    reset() {
      bindings.splice(0, bindings.length, ...initialBindings);
      snapshots.clear();
      for (const [bindingId, snapshot] of initialSnapshots) snapshots.set(bindingId, snapshot);
      drafts.clear();
      receipts.clear();
      operations.clear();
      targets.clear();
      registrationOperations.clear();
      sequence = 0;
      seedDeploymentFacts();
    },
  };
}

/** Mock-only rule handlers validate requests and responses against the feature's live wire schemas. */
export function createRuleSetMockHandlers(
  scenario: RuleSetMockScenario,
  adminAccountId: string,
  clock: () => number = () => Date.now(),
  readRegisteredSources: () => readonly RuleSourceOption[] = () => [],
) {
  const state = createRuleMockState(scenario, adminAccountId, clock);
  const handlers = Object.freeze([
    http.post("*/api/v1/rulesets", async ({ request }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      if (!demoAdminAllowed()) return forbidden(requestId);
      if (!request.headers.get(CONSOLE_HEADER.Csrf))
        return response(requestId, { error: { code: "csrf_failed", requestId } }, 403);
      const parsed = RuleBindingRegistrationRequestSchema.safeParse(
        await request.json().catch(() => null),
      );
      if (
        !parsed.success ||
        request.headers.get(CONSOLE_HEADER.IdempotencyKey) !== parsed.data?.requestKey
      )
        return response(requestId, { error: { code: "invalid_request", requestId } }, 400);

      const registration = parsed.data;
      const fingerprint = JSON.stringify(registration);
      const prior = state.registrationOperations.get(registration.requestKey);
      if (prior)
        return prior.fingerprint === fingerprint
          ? response(requestId, prior.binding, 201)
          : response(requestId, { error: { code: "idempotency_conflict", requestId } }, 409);

      const source = readRegisteredSources().find((item) => item.id === registration.sourceId);
      if (
        !source ||
        source.revision !== registration.sourceRevision ||
        source.provider !== registration.target.provider
      )
        return response(requestId, { error: { code: "conflict", requestId } }, 409);
      if (
        registration.environmentId !== scenario.environment.id ||
        !scenario.applications.some((application) => application.id === registration.appId) ||
        state.bindings.some((binding) => binding.id === registration.bindingId)
      )
        return response(requestId, { error: { code: "conflict", requestId } }, 409);

      const location =
        registration.target.provider === "nacos"
          ? `nacos://${registration.target.namespace}/${registration.target.group}/${registration.target.dataId}`
          : `consul://${registration.target.datacenter ? `${registration.target.datacenter}/` : ""}${registration.target.key}`;
      const binding = {
        id: registration.bindingId,
        environmentId: registration.environmentId,
        appId: registration.appId,
        kind: registration.kind,
        profile: registration.profile,
        sourceId: source.id,
        sourceLabel: source.name,
        location,
      };
      const validBinding = RuleBindingSchema.safeParse(binding);
      if (!validBinding.success)
        return response(requestId, { error: { code: "invalid_request", requestId } }, 400);

      const target: VersionedRulePublicationTarget = {
        bindingId: binding.id,
        targetRevision: state.next("target-revision"),
        sourceRevision: source.revision,
        target:
          registration.target.provider === "nacos"
            ? {
                ...registration.target,
                sourceId: source.id,
              }
            : {
                ...registration.target,
                sourceId: source.id,
                datacenter: registration.target.datacenter || null,
              },
      };
      const snapshot: RuleSetSnapshot = {
        binding: validBinding.data,
        versionId: null,
        checksum: state.next("empty-snapshot"),
        sourceRevision: source.revision,
        asOfMs: clock(),
        records: [],
      };
      const { asOfMs, ...snapshotFacts } = snapshot;
      if (
        !RuleSetSnapshotSchema.safeParse({
          ...snapshotFacts,
          asOf: instant(asOfMs),
        }).success
      )
        return response(requestId, { error: { code: "dependency_unavailable", requestId } }, 503);

      state.bindings.push(validBinding.data);
      state.snapshots.set(binding.id, snapshot);
      state.targets.set(binding.id, target);
      state.registrationOperations.set(registration.requestKey, {
        fingerprint,
        binding: validBinding.data,
      });
      return response(requestId, validBinding.data, 201);
    }),
    http.get("*/api/v1/rulesets", ({ request }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      const url = new URL(request.url);
      const environmentId = url.searchParams.get("environmentId") ?? "";
      const appId = url.searchParams.get("appId");
      const kind = url.searchParams.get("kind");
      const search = url.searchParams.get("search") ?? "";
      const page = Number(url.searchParams.get("page"));
      const pageSize = Number(url.searchParams.get("pageSize"));
      const query = { environmentId, appId, kind, search, page, pageSize };
      const all = state.bindings.filter(
        (binding) =>
          binding.environmentId === environmentId &&
          (appId === null || binding.appId === appId) &&
          (kind === null || binding.kind === kind) &&
          (!search || `${binding.id} ${binding.location} ${binding.kind}`.includes(search)),
      );
      const input = {
        query: {
          ...query,
          appId: appId || null,
          kind: kind || null,
        },
        total: all.length,
        items: all.slice((page - 1) * pageSize, page * pageSize),
      };
      const parsed = RuleBindingPageSchema.safeParse(input);
      return parsed.success
        ? response(requestId, parsed.data)
        : response(requestId, { error: { code: "invalid_request", requestId } }, 400);
    }),
    http.get("*/api/v1/rulesets/:bindingId/snapshot", ({ request, params }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      const snapshot = state.snapshots.get(String(params.bindingId));
      if (!snapshot) return response(requestId, { error: { code: "not_found", requestId } }, 404);
      const { asOfMs, ...facts } = snapshot;
      const wire = { ...facts, asOf: instant(asOfMs) };
      const parsed = RuleSetSnapshotSchema.safeParse(wire);
      return parsed.success
        ? response(requestId, parsed.data)
        : response(requestId, { error: { code: "dependency_unavailable", requestId } }, 503);
    }),
    http.get("*/api/v1/rulesets/:bindingId/drafts", ({ request, params }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      if (!demoAdminAllowed()) return forbidden(requestId);
      const bindingId = String(params.bindingId);
      const items = [...state.drafts.values()].filter((item) => item.bindingId === bindingId);
      const value = { bindingId, asOf: instant(clock()), items };
      const parsed = RuleSetCollectionSchema(StoredRuleDraftSchema).safeParse(value);
      return parsed.success
        ? response(requestId, value)
        : response(requestId, { error: { code: "dependency_unavailable", requestId } }, 503);
    }),
    http.get("*/api/v1/rulesets/:bindingId/drafts/:draftId", ({ request, params }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      if (!demoAdminAllowed()) return forbidden(requestId);
      const draft = state.drafts.get(String(params.draftId));
      return draft && draft.bindingId === params.bindingId
        ? response(requestId, draft)
        : response(requestId, { error: { code: "not_found", requestId } }, 404);
    }),
    http.post("*/api/v1/rulesets/:bindingId/validate", async ({ request, params }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      if (!demoAdminAllowed()) return forbidden(requestId);
      const candidate = RuleSetCandidateSchema.safeParse(await request.json().catch(() => null));
      if (!candidate.success || candidate.data.bindingId !== params.bindingId)
        return response(requestId, { error: { code: "invalid_request", requestId } }, 400);
      const report = {
        bindingId: candidate.data.bindingId,
        profile: candidate.data.profile,
        baseChecksum: candidate.data.baseChecksum,
        candidateChecksum: `candidate-${candidate.data.kind}-${candidate.data.rules.length}`,
        validationId: `validation-${candidate.data.kind}`,
        isPublishable: true,
        issues: [],
      };
      const parsed = RuleValidationReportSchema.safeParse(report);
      return parsed.success
        ? response(requestId, parsed.data)
        : response(requestId, { error: { code: "dependency_unavailable", requestId } }, 503);
    }),
    http.post("*/api/v1/rulesets/:bindingId/diff", async ({ request, params }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      if (!demoAdminAllowed()) return forbidden(requestId);
      const candidate = RuleSetCandidateSchema.safeParse(await request.json().catch(() => null));
      if (!candidate.success || candidate.data.bindingId !== params.bindingId)
        return response(requestId, { error: { code: "invalid_request", requestId } }, 400);
      return response(requestId, {
        bindingId: candidate.data.bindingId,
        baseChecksum: candidate.data.baseChecksum,
        candidateChecksum: `candidate-${candidate.data.kind}-${candidate.data.rules.length}`,
        changes: [],
      });
    }),
    http.get("*/api/v1/rulesets/:bindingId/versions", ({ request, params }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      const bindingId = String(params.bindingId);
      const items = [...state.versions.values()].filter((item) => item.bindingId === bindingId);
      return response(requestId, { bindingId, asOf: instant(clock()), items });
    }),
    http.get("*/api/v1/rulesets/:bindingId/versions/:versionId", ({ request, params }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      const value = state.versions.get(
        state.versionKey(String(params.bindingId), String(params.versionId)),
      );
      return value && value.bindingId === params.bindingId
        ? response(requestId, value)
        : response(requestId, { error: { code: "not_found", requestId } }, 404);
    }),
    http.get("*/api/v1/rulesets/:bindingId/publications", ({ request, params }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      const bindingId = String(params.bindingId);
      return response(requestId, {
        bindingId,
        asOf: instant(clock()),
        items: [...state.publications.values()].filter((item) => item.bindingId === bindingId),
      });
    }),
    http.get("*/api/v1/rulesets/:bindingId/publications/:publicationId", ({ request, params }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      const item = state.publications.get(String(params.publicationId));
      return item && item.bindingId === params.bindingId
        ? response(requestId, item)
        : response(requestId, { error: { code: "not_found", requestId } }, 404);
    }),
    http.get(
      "*/api/v1/rulesets/:bindingId/publications/:publicationId/receipts",
      ({ request, params }) => {
        const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
        const publication = state.publications.get(String(params.publicationId));
        if (!publication || publication.bindingId !== params.bindingId)
          return response(requestId, { error: { code: "not_found", requestId } }, 404);
        const url = new URL(request.url);
        const page = Number(url.searchParams.get("page"));
        const pageSize = Number(url.searchParams.get("pageSize"));
        const items = state.receipts.get(String(params.publicationId)) ?? [];
        const count = (status: string) => items.filter((item) => item.state === status).length;
        return response(requestId, {
          publicationId: publication.id,
          bindingId: publication.bindingId,
          page,
          pageSize,
          asOf: instant(clock()),
          total: items.length,
          expected: items.length,
          inventorySource: scenario.inventorySource,
          applied: count("applied"),
          pending: count("pending"),
          failed: count("failed"),
          unknown: count("unknown"),
          restartRequired: count("restart_required"),
          items: items.slice((page - 1) * pageSize, page * pageSize),
        });
      },
    ),
    http.get("*/api/v1/rulesets/:bindingId/plans", ({ request, params }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      const bindingId = String(params.bindingId);
      return response(requestId, {
        bindingId,
        asOf: instant(clock()),
        items: [...state.plans.values()].filter((item) => item.bindingId === bindingId),
      });
    }),
    http.get("*/api/v1/rulesets/:bindingId/publication-target", ({ request, params }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      const bindingId = String(params.bindingId);
      const target = state.targets.get(bindingId);
      return response(
        requestId,
        target
          ? {
              bindingId,
              targetRevision: target.targetRevision,
              sourceRevision: target.sourceRevision,
              target: target.target,
            }
          : { bindingId, target: null },
      );
    }),
    http.post("*/api/v1/rulesets/:bindingId/commands", async ({ request, params }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      if (!demoAdminAllowed()) return forbidden(requestId);
      const parsed = RuleCommandRequestSchema.safeParse(await request.json().catch(() => null));
      const bindingId = String(params.bindingId);
      if (!parsed.success || parsed.data.mutation.kind === undefined)
        return response(requestId, { error: { code: "invalid_request", requestId } }, 400);
      const operationKey = `${bindingId}:${parsed.data.requestKey}`;
      const previous = state.operations.get(operationKey);
      if (previous) return response(requestId, previous, 202);
      const reject = (reason: (typeof RULE_REJECTION)[keyof typeof RULE_REJECTION]) => {
        const operation = {
          bindingId,
          requestKey: parsed.data.requestKey,
          status: "rejected",
          reason,
        };
        const valid = RuleOperationObservationSchema.safeParse(operation);
        if (!valid.success)
          return response(requestId, { error: { code: "service_unavailable", requestId } }, 503);
        state.operations.set(operationKey, valid.data);
        return response(requestId, valid.data, 202);
      };
      const mutation = parsed.data.mutation;
      const createdAt = instant(clock());
      let result: Record<string, unknown>;
      if (mutation.kind === RULE_MUTATION.SaveDraft) {
        const draftId = mutation.draftId ?? state.next("draft");
        const draft = {
          id: draftId,
          bindingId,
          revision: state.next("draft-revision"),
          kind: mutation.candidate.kind,
          profile: mutation.candidate.profile,
          baseVersionId: mutation.candidate.baseVersionId,
          baseChecksum: mutation.candidate.baseChecksum,
          sourceRevision: mutation.candidate.sourceRevision,
          updatedAt: createdAt,
          records: mutation.candidate.rules.map((item, index) => ({
            id: item.recordId ?? `rule-${bindingId}-${index + 1}`,
            rule: item.rule,
          })),
        };
        state.drafts.set(draftId, draft);
        result = { kind: mutation.kind, draft };
      } else if (mutation.kind === RULE_MUTATION.DeleteDraft) {
        state.drafts.delete(mutation.draftId);
        result = { kind: mutation.kind, draftId: mutation.draftId };
      } else if (mutation.kind === RULE_MUTATION.FreezeVersion) {
        const draft = state.drafts.get(mutation.draftId);
        if (!draft) return reject(RULE_REJECTION.NotFound);
        const version = {
          id: state.next("version"),
          bindingId,
          kind: draft.kind,
          profile: draft.profile,
          baseVersionId: draft.baseVersionId,
          checksum: mutation.candidateChecksum,
          name: mutation.name,
          note: mutation.note,
          createdAt,
          createdById: adminAccountId,
          records: draft.records,
        };
        state.versions.set(state.versionKey(bindingId, version.id), version);
        result = {
          kind: mutation.kind,
          draftId: mutation.draftId,
          draftRevision: draft.revision,
          version,
        };
      } else if (mutation.kind === RULE_MUTATION.Publish) {
        const publication = {
          id: state.next("publication"),
          bindingId,
          targetVersionId: mutation.versionId,
          targetChecksum: mutation.versionChecksum,
          baseVersionId: mutation.expectedVersionId,
          createdAt,
          validation: { state: "succeeded", observedAt: createdAt, reason: null },
          configurationWrite: { state: "succeeded", observedAt: createdAt, reason: null },
          readBack: { state: "succeeded", observedAt: createdAt, reason: null },
        };
        state.publications.set(publication.id, publication);
        state.receipts.set(
          publication.id,
          state.pendingReceipts(bindingId, publication.targetVersionId),
        );
        result = { kind: mutation.kind, publication };
      } else if (mutation.kind === RULE_MUTATION.ConfigureTarget) {
        const binding = state.bindings.find((item) => item.id === bindingId);
        const source = state.snapshots.get(bindingId);
        const current = state.targets.get(bindingId);
        if (!binding) return reject(RULE_REJECTION.NotFound);
        if (
          !source?.sourceRevision ||
          source.sourceRevision !== mutation.expectedSourceRevision ||
          mutation.target.sourceId !== binding.sourceId ||
          (current?.targetRevision ?? null) !== mutation.expectedTargetRevision
        )
          return reject(RULE_REJECTION.Conflict);
        const target: VersionedRulePublicationTarget = {
          bindingId,
          targetRevision: state.next("target-revision"),
          sourceRevision: source.sourceRevision,
          target:
            mutation.target.provider === "consul"
              ? { ...mutation.target, datacenter: null }
              : mutation.target,
        };
        state.targets.set(bindingId, target);
        result = {
          kind: mutation.kind,
          bindingId,
          targetRevision: target.targetRevision,
          sourceRevision: target.sourceRevision,
          target: target.target,
        };
      } else if (mutation.kind === RULE_MUTATION.CreatePlan) {
        const schedule = mutation.schedule;
        if (
          !state.versions.has(state.versionKey(bindingId, schedule.versionId)) ||
          !state.versions.has(state.versionKey(bindingId, schedule.restoreVersionId))
        )
          return reject(RULE_REJECTION.Validation);
        const existingPlans = [];
        for (const candidate of state.plans.values()) {
          const parsedPlan = ActivationPlanSchema.safeParse(candidate);
          if (!parsedPlan.success)
            return response(
              requestId,
              { error: { code: "dependency_unavailable", requestId } },
              503,
            );
          const item = parsedPlan.data;
          if (item.bindingId !== bindingId) continue;
          existingPlans.push({
            id: item.id,
            revision: item.revision,
            bindingId: item.bindingId,
            versionId: item.versionId,
            restoreVersionId: item.restoreVersionId,
            activateAtMs: Date.parse(item.activateAt),
            deactivateAtMs: Date.parse(item.deactivateAt),
            timeZone: item.timeZone,
            state: item.state,
            activationPublicationId: item.activationPublicationId,
            restorePublicationId: item.restorePublicationId,
          });
        }
        const issues = activationScheduleIssues(
          {
            bindingId,
            versionId: schedule.versionId,
            restoreVersionId: schedule.restoreVersionId,
            activateAtMs: Date.parse(schedule.activateAt),
            deactivateAtMs: Date.parse(schedule.deactivateAt),
            timeZone: schedule.timeZone,
          },
          clock(),
          existingPlans,
        );
        if (issues.includes(SCHEDULE_ISSUE.Overlap)) return reject(RULE_REJECTION.Conflict);
        if (issues.length) return reject(RULE_REJECTION.Validation);
        const plan = {
          id: state.next("plan"),
          revision: state.next("plan-revision"),
          bindingId,
          versionId: mutation.schedule.versionId,
          restoreVersionId: mutation.schedule.restoreVersionId,
          activateAt: mutation.schedule.activateAt,
          deactivateAt: mutation.schedule.deactivateAt,
          timeZone: mutation.schedule.timeZone,
          state: "pending",
          activationPublicationId: null,
          restorePublicationId: null,
        };
        const valid = ActivationPlanSchema.safeParse(plan);
        if (!valid.success)
          return response(requestId, { error: { code: "validation_failed", requestId } }, 422);
        state.plans.set(plan.id, plan);
        result = { kind: mutation.kind, plan };
      } else {
        const plan = state.plans.get(mutation.planId);
        if (!plan) return reject(RULE_REJECTION.NotFound);
        if (plan.revision !== mutation.expectedRevision) return reject(RULE_REJECTION.Conflict);
        const cancelled = { ...plan, revision: state.next("plan-revision"), state: "cancelled" };
        state.plans.set(mutation.planId, cancelled);
        result = { kind: mutation.kind, plan: cancelled };
      }
      const operation = {
        bindingId,
        requestKey: parsed.data.requestKey,
        status: "completed",
        result,
      };
      const valid = RuleOperationObservationSchema.safeParse(operation);
      if (!valid.success)
        return response(requestId, { error: { code: "dependency_unavailable", requestId } }, 503);
      state.operations.set(operationKey, valid.data);
      return response(requestId, valid.data, 202);
    }),
    http.get("*/api/v1/rulesets/:bindingId/operations/:requestKey", ({ request, params }) => {
      const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
      if (!demoAdminAllowed()) return forbidden(requestId);
      const bindingId = String(params.bindingId);
      const key = `${bindingId}:${String(params.requestKey)}`;
      return response(
        requestId,
        state.operations.get(key) ?? {
          bindingId,
          requestKey: String(params.requestKey),
          status: "not-found",
        },
      );
    }),
  ]);

  return { handlers, reset: () => state.reset() };
}
