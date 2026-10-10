import { AppError, AppErrorKind, defineUrl, HttpMethod } from "@richie696/react-framework";
import { z } from "zod";
import type {
  ConsoleEndpoint,
  ConsoleTransport,
} from "../../../core/api/transport/consoleEndpoint";
import type { ConsoleErrorCode } from "../../../core/api/protocol/common";
import {
  OpaqueIdentifierSchema,
  PageNumberSchema,
  PageSizeSchema,
  RequestKeySchema,
} from "../../../core/api/protocol/common";
import { parseConsoleInput } from "../../../core/api/protocol/parseInput";
import {
  RECEIPT_PAGE_SIZE_LIMIT,
  validPublicationReceipts,
  validRulePublication,
} from "../model/ruleDeployment";
import { MAX_BINDING_PAGE_SIZE, validBindingPage, validBindingQuery } from "../model/ruleDirectory";
import { validRuleSetSnapshot } from "../model/ruleSet";
import { validRuleActivationPlan, validRuleCollection } from "../model/ruleDeploymentState";
import { validRuleSetDiff, validValidationReport } from "../model/ruleDraftState";
import { validRuleOperationObservation } from "../model/ruleOperationPolicy";
import { validRuleValue } from "../model/ruleValue";
import type { RuleRecord, RuleSetCandidate } from "../model/ruleSet";
import type { RuleKind } from "../model/ruleKinds";
import type { RuleSetVersion } from "../model/ruleDeployment";
import { validRulePublicationTargetSnapshot } from "../model/rulePublicationTarget";
import type { StoredRuleDraft } from "../model/ruleSetOperations";
import type { RuleSetPort } from "./ruleSetPort";
import {
  ActivationPlanSchema,
  PublicationReceiptPageSchema,
  RuleBindingPageSchema,
  RuleBindingParametersSchema,
  RuleBindingRegistrationRequestSchema,
  RuleBindingSchema,
  RuleCommandRequestSchema,
  RuleOperationObservationSchema,
  RulePublicationSchema,
  RulePublicationTargetSnapshotSchema,
  RuleSetCandidateSchema,
  RuleSetCollectionSchema,
  RuleSetDiffSchema,
  RuleSetSnapshotSchema,
  RuleSetVersionSchema,
  RuleValidationReportSchema,
  StoredRuleDraftSchema,
} from "./ruleSetWire";
import {
  bindingPageFromWire,
  bindingRegistrationToWire,
  bindingParametersToWire,
  candidateToWire,
  diffFromWire,
  mutationToWire,
  operationFromWire,
  planFromWire,
  publicationFromWire,
  receiptsFromWire,
  ruleCollectionFromWire,
  ruleSetSnapshotFromWire,
  ruleValidationFromWire,
  storedDraftFromWire,
  versionFromWire,
} from "./ruleSetMapper";

const readErrors = [
  "invalid_request",
  "unauthenticated",
  "not_found",
  "rate_limited",
  "service_unavailable",
] as const;
const writeErrors = [
  "invalid_request",
  "unauthenticated",
  "forbidden",
  "csrf_failed",
  "idempotency_conflict",
  "validation_failed",
  "rate_limited",
  "service_unavailable",
] as const;
const registrationErrors = [
  "invalid_request",
  "unauthenticated",
  "forbidden",
  "conflict",
  "csrf_failed",
  "idempotency_conflict",
  "validation_failed",
  "service_unavailable",
] as const;
const draftReadErrors = [...readErrors, "forbidden"] as const;
const candidateErrors = [
  ...readErrors,
  "forbidden",
  "csrf_failed",
  "conflict",
  "validation_failed",
] as const;
const operationReadErrors = [...readErrors, "forbidden"] as const;
const publicationTargetErrors = [
  "invalid_request",
  "unauthenticated",
  "service_unavailable",
] as const;
function endpoint<T>(
  path: string,
  response: z.ZodType<T>,
  options: {
    readonly command?: boolean;
    readonly method?: HttpMethod;
    readonly csrf?: boolean;
    readonly successStatus?: 200 | 201 | 202 | 204;
    readonly errors?: readonly ConsoleErrorCode[];
  } = {},
): ConsoleEndpoint<T> {
  const command = options.command ?? false;
  const method = options.method ?? (command ? HttpMethod.POST : HttpMethod.GET);
  const csrf = options.csrf ?? command;
  return {
    url: defineUrl(path, method === HttpMethod.GET ? undefined : { method }),
    response,
    successStatus: options.successStatus ?? (command ? 202 : 200),
    command,
    idempotency: command ? "required" : "none",
    csrf,
    expireOnUnauthorized: true,
    errors: options.errors ?? (command ? writeErrors : readErrors),
  };
}

const BindingsEndpoint = {
  ...endpoint("/api/v1/rulesets", RuleBindingPageSchema),
};
const RegisterBindingEndpoint = endpoint("/api/v1/rulesets", RuleBindingSchema, {
  command: true,
  method: HttpMethod.POST,
  successStatus: 201,
  errors: registrationErrors,
});
const SnapshotEndpoint = endpoint("/api/v1/rulesets/{bindingId}/snapshot", RuleSetSnapshotSchema);
const DraftsEndpoint = endpoint(
  "/api/v1/rulesets/{bindingId}/drafts",
  RuleSetCollectionSchema(StoredRuleDraftSchema),
  { errors: draftReadErrors },
);
const DraftEndpoint = endpoint(
  "/api/v1/rulesets/{bindingId}/drafts/{draftId}",
  StoredRuleDraftSchema,
  { errors: draftReadErrors },
);
const ValidateEndpoint = endpoint(
  "/api/v1/rulesets/{bindingId}/validate",
  RuleValidationReportSchema,
  { method: HttpMethod.POST, csrf: true, errors: candidateErrors },
);
const DiffEndpoint = endpoint("/api/v1/rulesets/{bindingId}/diff", RuleSetDiffSchema, {
  method: HttpMethod.POST,
  csrf: true,
  errors: candidateErrors,
});
const VersionsEndpoint = endpoint(
  "/api/v1/rulesets/{bindingId}/versions",
  RuleSetCollectionSchema(RuleSetVersionSchema),
);
const VersionEndpoint = endpoint(
  "/api/v1/rulesets/{bindingId}/versions/{versionId}",
  RuleSetVersionSchema,
);
const PublicationsEndpoint = endpoint(
  "/api/v1/rulesets/{bindingId}/publications",
  RuleSetCollectionSchema(RulePublicationSchema),
);
const PublicationEndpoint = endpoint(
  "/api/v1/rulesets/{bindingId}/publications/{publicationId}",
  RulePublicationSchema,
);
const ReceiptsEndpoint = endpoint(
  "/api/v1/rulesets/{bindingId}/publications/{publicationId}/receipts",
  PublicationReceiptPageSchema,
);
const PlansEndpoint = endpoint(
  "/api/v1/rulesets/{bindingId}/plans",
  RuleSetCollectionSchema(ActivationPlanSchema),
);
const PublicationTargetEndpoint = endpoint(
  "/api/v1/rulesets/{bindingId}/publication-target",
  RulePublicationTargetSnapshotSchema,
  { errors: publicationTargetErrors },
);
const CommandEndpoint = endpoint(
  "/api/v1/rulesets/{bindingId}/commands",
  RuleOperationObservationSchema,
  { command: true },
);
const OperationEndpoint = endpoint(
  "/api/v1/rulesets/{bindingId}/operations/{requestKey}",
  RuleOperationObservationSchema,
  { errors: operationReadErrors },
);

export const RULE_SET_ENDPOINTS = Object.freeze({
  Bindings: BindingsEndpoint,
  RegisterBinding: RegisterBindingEndpoint,
  Snapshot: SnapshotEndpoint,
  Drafts: DraftsEndpoint,
  Draft: DraftEndpoint,
  Validate: ValidateEndpoint,
  Diff: DiffEndpoint,
  Versions: VersionsEndpoint,
  Version: VersionEndpoint,
  Publications: PublicationsEndpoint,
  Publication: PublicationEndpoint,
  Receipts: ReceiptsEndpoint,
  Plans: PlansEndpoint,
  PublicationTarget: PublicationTargetEndpoint,
  Command: CommandEndpoint,
  Operation: OperationEndpoint,
});

const invalidInput = () =>
  new AppError(AppErrorKind.PROTOCOL, "Invalid rule-set request", {
    status: 400,
    code: "console_request_invalid",
  });
const invalidResponse = () =>
  new AppError(AppErrorKind.PROTOCOL, "Invalid rule-set response", {
    status: 502,
    code: "console_response_invalid",
  });
const bindingPath = (bindingId: string) => parseConsoleInput(OpaqueIdentifierSchema, bindingId);
const validRecords = (kind: RuleKind, records: readonly RuleRecord[]) =>
  records.length <= 1000 &&
  new Set(records.map((record) => record.id)).size === records.length &&
  records.every(
    (record) => !!record.id.trim() && record.rule.kind === kind && validRuleValue(record.rule),
  );
const validCandidate = (candidate: RuleSetCandidate) =>
  !!candidate.bindingId.trim() &&
  !!candidate.profile.trim() &&
  !!candidate.baseChecksum.trim() &&
  (candidate.baseVersionId === null || !!candidate.baseVersionId.trim()) &&
  (candidate.sourceRevision === null || !!candidate.sourceRevision.trim()) &&
  candidate.rules.length <= 1000 &&
  new Set(candidate.rules.flatMap((item) => (item.recordId === null ? [] : [item.recordId])))
    .size === candidate.rules.filter((item) => item.recordId !== null).length &&
  candidate.rules.every(
    (item) =>
      (item.recordId === null || !!item.recordId.trim()) &&
      item.rule.kind === candidate.kind &&
      validRuleValue(item.rule),
  );
const validStoredDraftForBinding = (draft: StoredRuleDraft, bindingId: string) =>
  draft.bindingId === bindingId &&
  !!draft.id.trim() &&
  !!draft.revision.trim() &&
  !!draft.profile.trim() &&
  !!draft.baseChecksum.trim() &&
  Number.isSafeInteger(draft.updatedAtMs) &&
  draft.updatedAtMs >= 0 &&
  (draft.baseVersionId === null || !!draft.baseVersionId.trim()) &&
  (draft.sourceRevision === null || !!draft.sourceRevision.trim()) &&
  validRecords(draft.kind, draft.records);
const validVersionForBinding = (version: RuleSetVersion, bindingId: string) =>
  version.bindingId === bindingId &&
  !!version.id.trim() &&
  !!version.profile.trim() &&
  !!version.checksum.trim() &&
  !!version.name.trim() &&
  !!version.createdById.trim() &&
  Number.isSafeInteger(version.createdAtMs) &&
  version.createdAtMs >= 0 &&
  (version.baseVersionId === null || !!version.baseVersionId.trim()) &&
  validRecords(version.kind, version.records);
export function createRuleSetHttp(transport: ConsoleTransport): RuleSetPort {
  const port: RuleSetPort = {
    async readBindings(query, signal) {
      if (!validBindingQuery(query)) throw invalidInput();
      const parsed = parseConsoleInput(RuleBindingParametersSchema, bindingParametersToWire(query));
      const wire = await transport.send(
        {
          ...BindingsEndpoint,
          accept: (response) => validBindingPage(bindingPageFromWire(response), query),
        },
        { signal, query: parsed },
      );
      return bindingPageFromWire(wire);
    },
    async registerBinding(command, signal) {
      const body = parseConsoleInput(
        RuleBindingRegistrationRequestSchema,
        bindingRegistrationToWire(command),
      );
      const matchesCommand = (response: unknown) => {
        const binding = RuleBindingSchema.safeParse(response);
        return (
          binding.success &&
          binding.data.id === command.bindingId &&
          binding.data.environmentId === command.environmentId &&
          binding.data.appId === command.appId &&
          binding.data.kind === command.kind &&
          binding.data.profile === command.profile &&
          binding.data.sourceId === command.sourceId
        );
      };
      const wire = await transport.send(
        { ...RegisterBindingEndpoint, accept: matchesCommand },
        { signal, body, requestKey: command.requestKey },
      );
      if (!matchesCommand(wire)) throw invalidResponse();
      return RuleBindingSchema.parse(wire);
    },
    async readSnapshot(bindingId, signal) {
      const id = bindingPath(bindingId);
      const wire = await transport.send(
        {
          ...SnapshotEndpoint,
          accept: (response) => {
            const snapshot = ruleSetSnapshotFromWire(response);
            return (
              validRuleSetSnapshot(snapshot, bindingId) &&
              validRecords(snapshot.binding.kind, snapshot.records)
            );
          },
        },
        { signal, pathParams: [id] },
      );
      return ruleSetSnapshotFromWire(wire);
    },
    async readDrafts(bindingId, signal) {
      const id = bindingPath(bindingId);
      const schema = RuleSetCollectionSchema(StoredRuleDraftSchema);
      const wire = await transport.send(
        {
          ...DraftsEndpoint,
          accept: (response) => {
            const parsed = schema.safeParse(response);
            return (
              parsed.success &&
              parsed.data.bindingId === bindingId &&
              parsed.data.items.every((item) =>
                validStoredDraftForBinding(storedDraftFromWire(item), bindingId),
              )
            );
          },
        },
        { signal, pathParams: [id] },
      );
      const collection = ruleCollectionFromWire(wire, StoredRuleDraftSchema, storedDraftFromWire);
      if (
        !validRuleCollection(collection, bindingId, (item) =>
          validStoredDraftForBinding(item, bindingId),
        )
      )
        throw invalidResponse();
      return collection;
    },
    async readDraft(bindingId, draftId, signal) {
      const pathParams = [bindingId, draftId].map(bindingPath);
      const wire = await transport.send(DraftEndpoint, { signal, pathParams });
      const draft = storedDraftFromWire(wire);
      if (draft.id !== draftId || !validStoredDraftForBinding(draft, bindingId))
        throw invalidResponse();
      return draft;
    },
    async validateCandidate(candidate, signal) {
      const bindingId = bindingPath(candidate.bindingId);
      if (!validCandidate(candidate)) throw invalidInput();
      const body = parseConsoleInput(RuleSetCandidateSchema, candidateToWire(candidate));
      const wire = await transport.send(
        {
          ...ValidateEndpoint,
          accept: (response) => {
            const result = ruleValidationFromWire(response);
            return validValidationReport(result, candidate);
          },
        },
        { signal, pathParams: [bindingId], body },
      );
      const report = ruleValidationFromWire(wire);
      if (!validValidationReport(report, candidate)) throw invalidResponse();
      return report;
    },
    async compareCandidate(candidate, signal) {
      const bindingId = bindingPath(candidate.bindingId);
      if (!validCandidate(candidate)) throw invalidInput();
      const body = parseConsoleInput(RuleSetCandidateSchema, candidateToWire(candidate));
      const wire = await transport.send(
        {
          ...DiffEndpoint,
          accept: (response) => {
            const diff = diffFromWire(response);
            return validRuleSetDiff(diff, candidate);
          },
        },
        { signal, pathParams: [bindingId], body },
      );
      const diff = diffFromWire(wire);
      if (!validRuleSetDiff(diff, candidate)) throw invalidResponse();
      return diff;
    },
    async readVersions(bindingId, signal) {
      const id = bindingPath(bindingId),
        schema = RuleSetCollectionSchema(RuleSetVersionSchema);
      const wire = await transport.send(
        {
          ...VersionsEndpoint,
          accept: (response) => {
            const parsed = schema.safeParse(response);
            return (
              parsed.success &&
              parsed.data.bindingId === bindingId &&
              parsed.data.items.every((item) =>
                validVersionForBinding(versionFromWire(item), bindingId),
              )
            );
          },
        },
        { signal, pathParams: [id] },
      );
      const collection = ruleCollectionFromWire(wire, RuleSetVersionSchema, versionFromWire);
      if (
        !validRuleCollection(collection, bindingId, (item) =>
          validVersionForBinding(item, bindingId),
        )
      )
        throw invalidResponse();
      return collection;
    },
    async readVersion(bindingId, versionId, signal) {
      const pathParams = [bindingId, versionId].map(bindingPath);
      const wire = await transport.send(VersionEndpoint, { signal, pathParams });
      const version = versionFromWire(wire);
      if (version.bindingId !== bindingId || version.id !== versionId) throw invalidResponse();
      return version;
    },
    async readPublications(bindingId, signal) {
      const id = bindingPath(bindingId),
        schema = RuleSetCollectionSchema(RulePublicationSchema);
      const wire = await transport.send(
        {
          ...PublicationsEndpoint,
          accept: (response) => {
            const parsed = schema.safeParse(response);
            return (
              parsed.success &&
              parsed.data.bindingId === bindingId &&
              parsed.data.items.every((item) => {
                const publication = publicationFromWire(item);
                return validRulePublication(publication, bindingId);
              })
            );
          },
        },
        { signal, pathParams: [id] },
      );
      const collection = ruleCollectionFromWire(wire, RulePublicationSchema, publicationFromWire);
      if (
        !validRuleCollection(collection, bindingId, (item) => validRulePublication(item, bindingId))
      )
        throw invalidResponse();
      return collection;
    },
    async readPublication(bindingId, publicationId, signal) {
      const pathParams = [bindingId, publicationId].map(bindingPath);
      const wire = await transport.send(PublicationEndpoint, { signal, pathParams });
      const publication = publicationFromWire(wire);
      if (!validRulePublication(publication, bindingId, publicationId)) throw invalidResponse();
      return publication;
    },
    async readReceipts(query, signal) {
      if (
        !Number.isSafeInteger(query.page) ||
        query.page < 1 ||
        !Number.isSafeInteger(query.pageSize) ||
        query.pageSize < 1 ||
        query.pageSize > RECEIPT_PAGE_SIZE_LIMIT
      )
        throw invalidInput();
      const { bindingId, publicationId, page, pageSize } = query;
      const ids = [bindingId, publicationId].map(bindingPath);
      const params = parseConsoleInput(
        z.strictObject({
          page: PageNumberSchema,
          pageSize: PageSizeSchema.max(RECEIPT_PAGE_SIZE_LIMIT),
        }),
        { page, pageSize },
      );
      const publicationWire = await transport.send(PublicationEndpoint, {
        signal,
        pathParams: ids,
      });
      const publication = publicationFromWire(publicationWire);
      if (!validRulePublication(publication, bindingId, publicationId)) throw invalidResponse();
      const wire = await transport.send(ReceiptsEndpoint, {
        signal,
        pathParams: ids,
        query: params,
      });
      const pageResult = receiptsFromWire(wire);
      if (!validPublicationReceipts(pageResult, publication, page, pageSize))
        throw invalidResponse();
      return pageResult;
    },
    async readPlans(bindingId, signal) {
      const id = bindingPath(bindingId),
        schema = RuleSetCollectionSchema(ActivationPlanSchema);
      const wire = await transport.send(
        {
          ...PlansEndpoint,
          accept: (response) => {
            const parsed = schema.safeParse(response);
            return (
              parsed.success &&
              parsed.data.bindingId === bindingId &&
              parsed.data.items.every((item) => item.bindingId === bindingId)
            );
          },
        },
        { signal, pathParams: [id] },
      );
      const collection = ruleCollectionFromWire(wire, ActivationPlanSchema, planFromWire);
      if (
        !validRuleCollection(collection, bindingId, (plan) =>
          validRuleActivationPlan(plan, bindingId),
        )
      )
        throw invalidResponse();
      return collection;
    },
    async readPublicationTarget(bindingId, signal) {
      const id = bindingPath(bindingId);
      const value = await transport.send(PublicationTargetEndpoint, {
        signal,
        pathParams: [id],
      });
      if (!validRulePublicationTargetSnapshot(value, bindingId)) throw invalidResponse();
      return value;
    },
    async mutateRuleSet(mutation, signal) {
      const bindingId = bindingPath(mutation.bindingId);
      if (
        (mutation.kind === "save_draft" &&
          (mutation.candidate.bindingId !== mutation.bindingId ||
            !validCandidate(mutation.candidate))) ||
        (mutation.kind === "create_plan" && mutation.schedule.bindingId !== mutation.bindingId)
      )
        throw invalidInput();
      const body = parseConsoleInput(RuleCommandRequestSchema, {
        requestKey: mutation.requestKey,
        mutation: mutationToWire(mutation).mutation,
      });
      const value = await transport.send(
        {
          ...CommandEndpoint,
          accept: (response) =>
            validRuleOperationObservation(operationFromWire(response), mutation, false),
        },
        { signal, pathParams: [bindingId], body, requestKey: mutation.requestKey },
      );
      const observation = operationFromWire(value);
      if (!validRuleOperationObservation(observation, mutation, false)) throw invalidResponse();
      return observation;
    },
    async readRuleOperation(bindingId, requestKey, signal) {
      const pathParams = [bindingPath(bindingId), parseConsoleInput(RequestKeySchema, requestKey)];
      const value = await transport.send(OperationEndpoint, { signal, pathParams });
      const result = operationFromWire(value);
      if (result.bindingId !== bindingId || result.requestKey !== requestKey)
        throw invalidResponse();
      return result;
    },
  };
  return Object.freeze(port);
}
