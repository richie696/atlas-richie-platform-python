import { RULE_KIND } from "../model/ruleKinds";
import { ACTIVATION_STATE } from "../model/ruleActivation";
import { PUBLICATION_STAGE, RECEIPT_STATE } from "../model/ruleDeployment";
import { RULE_MUTATION, RULE_REJECTION } from "../model/ruleSetOperations";

export const RULE_EXAMPLE_TIME = Object.freeze({
  asOf: "2026-10-10T08:00:00.000Z",
  createdAt: "2026-10-09T08:00:00.000Z",
  activateAt: "2026-10-11T00:00:00.000Z",
  deactivateAt: "2026-10-11T06:00:00.000Z",
});

export const RULE_EXAMPLE_BINDING = Object.freeze({
  id: "binding-checkout-flow",
  environmentId: "prod",
  appId: "checkout",
  kind: RULE_KIND.Flow,
  profile: "sentinel-json-v1",
  sourceId: "source-nacos-prod",
  sourceLabel: "Production Nacos",
  location: "namespace-prod / sentinel / flow-rules",
});

export const RULE_EXAMPLE_RECORD = Object.freeze({
  id: "flow-rule-orders",
  rule: Object.freeze({
    kind: RULE_KIND.Flow,
    value: Object.freeze({
      resource: "POST /api/orders",
      limitApp: "default",
      grade: 1,
      count: 200,
      strategy: 0,
      controlBehavior: 0,
      clusterMode: false,
    }),
  }),
});

export const RULE_EXAMPLE_VERSION = Object.freeze({
  id: "version-2026-10-09",
  bindingId: RULE_EXAMPLE_BINDING.id,
  kind: RULE_KIND.Flow,
  profile: RULE_EXAMPLE_BINDING.profile,
  baseVersionId: null,
  checksum: "checksum-base-1",
  name: "Daily baseline",
  note: "Routine production limits",
  createdAt: RULE_EXAMPLE_TIME.createdAt,
  createdById: "account-admin-1",
  records: [RULE_EXAMPLE_RECORD],
});

export const RULE_EXAMPLE_RESTORE_VERSION = Object.freeze({
  ...RULE_EXAMPLE_VERSION,
  id: "version-2026-10-09-restore",
  name: "Previous stable baseline",
  note: "Version selected as the scheduled restore target",
});

export const RULE_EXAMPLE_CANDIDATE = Object.freeze({
  bindingId: RULE_EXAMPLE_BINDING.id,
  profile: RULE_EXAMPLE_BINDING.profile,
  kind: RULE_KIND.Flow,
  baseVersionId: RULE_EXAMPLE_VERSION.id,
  baseChecksum: RULE_EXAMPLE_VERSION.checksum,
  sourceRevision: "source-revision-7",
  rules: [Object.freeze({ recordId: RULE_EXAMPLE_RECORD.id, rule: RULE_EXAMPLE_RECORD.rule })],
});

export const RULE_EXAMPLE_DRAFT = Object.freeze({
  id: "draft-checkout-flow",
  bindingId: RULE_EXAMPLE_BINDING.id,
  revision: "draft-revision-3",
  kind: RULE_KIND.Flow,
  profile: RULE_EXAMPLE_BINDING.profile,
  baseVersionId: RULE_EXAMPLE_VERSION.id,
  baseChecksum: RULE_EXAMPLE_VERSION.checksum,
  sourceRevision: "source-revision-7",
  updatedAt: RULE_EXAMPLE_TIME.asOf,
  records: [RULE_EXAMPLE_RECORD],
});

export const RULE_EXAMPLE_PREVIOUS_DRAFT_REVISION = "draft-revision-2";

export const RULE_EXAMPLE_PUBLICATION = Object.freeze({
  id: "publication-checkout-flow-1",
  bindingId: RULE_EXAMPLE_BINDING.id,
  targetVersionId: RULE_EXAMPLE_VERSION.id,
  targetChecksum: RULE_EXAMPLE_VERSION.checksum,
  baseVersionId: null,
  createdAt: RULE_EXAMPLE_TIME.asOf,
  validation: Object.freeze({
    state: PUBLICATION_STAGE.Succeeded,
    observedAt: RULE_EXAMPLE_TIME.asOf,
    reason: null,
  }),
  configurationWrite: Object.freeze({
    state: PUBLICATION_STAGE.Awaiting,
    observedAt: null,
    reason: null,
  }),
  readBack: Object.freeze({
    state: PUBLICATION_STAGE.Awaiting,
    observedAt: null,
    reason: null,
  }),
});

export const RULE_EXAMPLE_PLAN = Object.freeze({
  id: "plan-checkout-seasonal-1",
  revision: "plan-revision-1",
  bindingId: RULE_EXAMPLE_BINDING.id,
  versionId: RULE_EXAMPLE_VERSION.id,
  restoreVersionId: RULE_EXAMPLE_RESTORE_VERSION.id,
  activateAt: RULE_EXAMPLE_TIME.activateAt,
  deactivateAt: RULE_EXAMPLE_TIME.deactivateAt,
  timeZone: "Asia/Shanghai",
  state: ACTIVATION_STATE.Pending,
  activationPublicationId: null,
  restorePublicationId: null,
});

export const RULE_EXAMPLE_TARGET = Object.freeze({
  bindingId: RULE_EXAMPLE_BINDING.id,
  targetRevision: "target-revision-2",
  sourceRevision: "source-revision-7",
  target: Object.freeze({
    provider: "nacos",
    sourceId: RULE_EXAMPLE_BINDING.sourceId,
    namespace: "namespace-prod",
    group: "sentinel",
    dataId: "checkout-flow-rules",
  }),
});

export function ruleErrorExample(
  code: "unauthenticated" | "forbidden" | "not_found" | "conflict" | "service_unavailable",
) {
  return { error: { code, requestId: `example-rule-${code}` } };
}

export const RULE_EXAMPLE_OPERATION = Object.freeze({
  requestKey: "rule-save-draft-20261010-1",
  pending: Object.freeze({
    requestKey: "rule-save-draft-20261010-1",
    bindingId: RULE_EXAMPLE_BINDING.id,
    status: "pending",
  }),
  completed: Object.freeze({
    requestKey: "rule-save-draft-20261010-1",
    bindingId: RULE_EXAMPLE_BINDING.id,
    status: "completed",
    result: Object.freeze({ kind: RULE_MUTATION.SaveDraft, draft: RULE_EXAMPLE_DRAFT }),
  }),
  rejected: Object.freeze({
    requestKey: "rule-save-draft-20261010-2",
    bindingId: RULE_EXAMPLE_BINDING.id,
    status: "rejected",
    reason: RULE_REJECTION.Validation,
  }),
});

export const RULE_EXAMPLE_RECEIPT_STATE = RECEIPT_STATE.Unknown;
