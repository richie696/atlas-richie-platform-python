import { AppError, AppErrorKind } from "@richie696/react-framework";
import {
  createOwnedQueryResource,
  type QueryAccessObserver,
} from "../../../shared/state/ownedQueryResource";
import type { RuleSetPort } from "../api/ruleSetPort";
import {
  bindingQueryKey,
  validBindingQuery,
  validBindingPage,
  validRuleCatalogPage,
  type BindingQuery,
  type BindingPage,
  type RuleCatalogPage,
  type RuleCatalogQuery,
} from "../model/ruleDirectory";
import {
  validRuleSetSnapshot,
  type RuleBinding,
  type RuleSetCollection,
  type RuleSetSnapshot,
} from "../model/ruleSet";
import type { StoredRuleDraft } from "../model/ruleSetOperations";
import { RULE_MUTATION } from "../model/ruleSetOperations";
import { validStoredDraft } from "../model/ruleDraftState";
import { validRuleCollection } from "../model/ruleDeploymentState";
import type { RuleOperation } from "./ruleOperation";
const invalid = () =>
  new AppError(AppErrorKind.PROTOCOL, "Inconsistent rule directory", {
    status: 502,
    code: "rule_read_invalid",
  });
/** Directory reads never select the first binding or create an editing owner. */
export function createRuleBindingDirectory(
  port: Pick<RuleSetPort, "readBindings">,
  access: QueryAccessObserver,
) {
  return createOwnedQueryResource<BindingQuery, BindingPage>(access, {
    keyOf: bindingQueryKey,
    async read(query, signal) {
      if (!validBindingQuery(query))
        throw new AppError(AppErrorKind.PROTOCOL, "Invalid directory query", { status: 422 });
      const page = await port.readBindings(query, signal);
      if (!validBindingPage(page, query)) throw invalid();
      return page;
    },
    classify: (page) =>
      page.items.length
        ? "ready"
        : page.query.search || page.query.kind !== null || page.total > 0
          ? "filtered-empty"
          : "empty",
  });
}

/** Rule entries are projected from authoritative provider snapshots; partial reads never imply zero rules. */
export function createRuleCatalogDirectory(
  port: Pick<RuleSetPort, "readRuleCatalog">,
  access: QueryAccessObserver,
) {
  return createOwnedQueryResource<RuleCatalogQuery, RuleCatalogPage>(access, {
    keyOf: bindingQueryKey,
    async read(query, signal) {
      if (!validBindingQuery(query))
        throw new AppError(AppErrorKind.PROTOCOL, "Invalid rule catalog query", { status: 422 });
      const page = await port.readRuleCatalog(query, signal);
      if (!validRuleCatalogPage(page, query)) throw invalid();
      return page;
    },
    classify: (page) =>
      page.coverage === "partial"
        ? "partial"
        : page.items.length
          ? "ready"
          : page.query.search || page.query.kind !== null || (page.total ?? 0) > 0
            ? "filtered-empty"
            : "empty",
  });
}
/** A deep-linked binding is read as its own cancellable owner; late responses cannot replace a newer target. */
export function createRuleBindingSnapshot(
  port: Pick<RuleSetPort, "readSnapshot">,
  access: QueryAccessObserver,
) {
  return createOwnedQueryResource<string | null, RuleSetSnapshot | null>(access, {
    keyOf: (bindingId) => bindingId ?? "",
    async read(bindingId, signal) {
      if (bindingId === null) return null;
      const snapshot = await port.readSnapshot(bindingId, signal);
      if (!validRuleSetSnapshot(snapshot, bindingId)) throw invalid();
      return snapshot;
    },
    classify: (snapshot) => (snapshot?.records.length ? "ready" : "empty"),
  });
}
/** Draft contents are admin-scoped. Confirmed save/delete refreshes only this directory, never the local edit buffer. */
export function createStoredDraftDirectory(
  binding: RuleBinding,
  port: Pick<RuleSetPort, "readDrafts">,
  access: QueryAccessObserver,
  operation: RuleOperation,
) {
  const ownerKey = access.read().ownerKey;
  const resource = createOwnedQueryResource<string, RuleSetCollection<StoredRuleDraft>>(access, {
    keyOf: (id) => id,
    async read(id, signal) {
      if (id !== binding.id || access.read().ownerKey !== ownerKey)
        throw new AppError(AppErrorKind.FORBIDDEN, "Wrong draft owner", { status: 403 });
      const value = await port.readDrafts(id, signal);
      if (!validRuleCollection(value, id, (draft) => validStoredDraft(draft, binding, draft.id)))
        throw invalid();
      return value;
    },
    classify: (value) => (value.items.length ? "ready" : "empty"),
  });
  let confirmedKey: string | null = null;
  const stop = operation.subscribe(() => {
    const state = operation.getSnapshot();
    if (
      !access.read().allowed ||
      access.read().ownerKey !== ownerKey ||
      state.command.status !== "success" ||
      !state.operation ||
      confirmedKey === state.operation.requestKey
    )
      return;
    if (
      state.operation.kind === RULE_MUTATION.SaveDraft ||
      state.operation.kind === RULE_MUTATION.DeleteDraft
    ) {
      confirmedKey = state.operation.requestKey;
      resource.reset();
      void resource.load(binding.id).catch(() => {});
    }
  });
  return Object.freeze({
    ...resource,
    dispose() {
      stop();
      resource.dispose();
    },
  });
}
