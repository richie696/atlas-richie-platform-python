import { AppError, AppErrorKind } from "@richie696/react-framework";
import {
  createOwnedQueryResource,
  type QueryAccessObserver,
} from "../../../shared/state/ownedQueryResource";
import type { RuleBinding, RuleSetCollection } from "../model/ruleSet";
import type { RuleSetPort } from "../api/ruleSetPort";
import type { RuleSetVersion, RulePublication } from "../model/ruleDeployment";
import type { RuleActivationPlan } from "../model/ruleActivation";
import {
  validRulePublicationTargetSnapshot,
  type RulePublicationTargetSnapshot,
} from "../model/rulePublicationTarget";
import {
  validRulePublication,
  validPublicationReceipts,
  RECEIPT_PAGE_SIZE_LIMIT,
} from "../model/ruleDeployment";
import {
  validRuleSetVersion,
  validRuleCollection,
  validRuleActivationPlan,
} from "../model/ruleDeploymentState";

const invalid = () =>
  new AppError(AppErrorKind.PROTOCOL, "Invalid rule deployment facts", { status: 502 });
export type RuleDeploymentReadPort = Pick<
  RuleSetPort,
  | "readVersions"
  | "readVersion"
  | "readPublications"
  | "readPublication"
  | "readReceipts"
  | "readPlans"
  | "readPublicationTarget"
>;
/** Independent version/publication/receipt/plan reads. Source freshness remains with the existing source owner. */
export function createRuleDeploymentResources(
  binding: RuleBinding,
  port: RuleDeploymentReadPort,
  access: QueryAccessObserver,
) {
  function collection<Value extends { readonly id: string }>(
    read: (bindingId: string, signal: AbortSignal) => Promise<RuleSetCollection<Value>>,
    validItem: (value: Value) => boolean,
  ) {
    return createOwnedQueryResource<string, RuleSetCollection<Value>>(access, {
      keyOf: (id) => id,
      async read(id, signal) {
        if (id !== binding.id) throw invalid();
        const value = await read(id, signal);
        if (!validRuleCollection(value, binding.id, validItem)) throw invalid();
        return value;
      },
      classify: (value) => (value.items.length ? "ready" : "empty"),
    });
  }
  const versions = collection<RuleSetVersion>(port.readVersions, (value) =>
    validRuleSetVersion(value, binding),
  );
  const publications = collection<RulePublication>(port.readPublications, (value) =>
    validRulePublication(value, binding.id),
  );
  const plans = collection<RuleActivationPlan>(port.readPlans, (value) =>
    validRuleActivationPlan(value, binding.id),
  );
  const publicationTarget = createOwnedQueryResource<string, RulePublicationTargetSnapshot>(
    access,
    {
      keyOf: (id) => id,
      async read(id, signal) {
        if (id !== binding.id) throw invalid();
        const value = await port.readPublicationTarget(id, signal);
        if (!validRulePublicationTargetSnapshot(value, binding.id)) throw invalid();
        return value;
      },
      classify: (value) => (value.target === null ? "empty" : "ready"),
    },
  );
  const version = createOwnedQueryResource<string, RuleSetVersion>(access, {
    keyOf: (id) => id,
    async read(id, signal) {
      if (!id.trim()) throw invalid();
      const value = await port.readVersion(binding.id, id, signal);
      if (!validRuleSetVersion(value, binding, id)) throw invalid();
      return value;
    },
    classify: () => "ready",
  });
  const publication = createOwnedQueryResource<string, RulePublication>(access, {
    keyOf: (id) => id,
    async read(id, signal) {
      if (!id.trim()) throw invalid();
      const value = await port.readPublication(binding.id, id, signal);
      if (!validRulePublication(value, binding.id, id)) throw invalid();
      return value;
    },
    classify: () => "ready",
  });
  // Capture the publication expectation with each request, so refresh/select cannot reinterpret late receipts.
  const receipts = createOwnedQueryResource<
    {
      readonly publication: RulePublication;
      readonly page: number;
      readonly pageSize: number;
    },
    Awaited<ReturnType<RuleSetPort["readReceipts"]>>
  >(access, {
    keyOf: (query) =>
      JSON.stringify([
        binding.id,
        query.publication.id,
        query.publication.targetVersionId,
        query.publication.targetChecksum,
        query.page,
        query.pageSize,
      ]),
    async read(query, signal) {
      if (
        !validRulePublication(query.publication, binding.id) ||
        !Number.isSafeInteger(query.page) ||
        query.page < 1 ||
        !Number.isSafeInteger(query.pageSize) ||
        query.pageSize < 1 ||
        query.pageSize > RECEIPT_PAGE_SIZE_LIMIT
      )
        throw invalid();
      const value = await port.readReceipts(
        {
          bindingId: binding.id,
          publicationId: query.publication.id,
          page: query.page,
          pageSize: query.pageSize,
        },
        signal,
      );
      if (!validPublicationReceipts(value, query.publication, query.page, query.pageSize))
        throw invalid();
      return value;
    },
    classify: (value) =>
      !value.total
        ? "empty"
        : value.expected === null ||
            value.pending ||
            value.failed ||
            value.unknown ||
            value.restartRequired
          ? "partial"
          : "ready",
  });
  const owned = [versions, version, publications, publication, receipts, plans, publicationTarget];
  return Object.freeze({
    versions,
    version,
    publications,
    publication,
    receipts,
    plans,
    publicationTarget,
    cancel: () => owned.forEach((resource) => resource.cancel()),
    reset: () => owned.forEach((resource) => resource.reset()),
    dispose: () => owned.forEach((resource) => resource.dispose()),
  });
}
