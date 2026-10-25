import { AppError, AppErrorKind } from "@richie696/react-framework";
import {
  createOwnedQueryResource,
  type QueryAccessObserver,
} from "../../../shared/state/ownedQueryResource";
import type { RuleObservationPort } from "../api/ruleObservationPort";
import type {
  RuleBindingStatesPage,
  RuleBindingStatesQuery,
  RuleCatalogUsagePage,
  RuleCatalogUsageQuery,
  RuleLoadObservationPage,
  RuleLoadObservationQuery,
  RuleLoadObservationHistoryPage,
  RuleLoadObservationHistoryQuery,
} from "../model/ruleObservations";

const invalid = () =>
  new AppError(AppErrorKind.PROTOCOL, "Inconsistent rule observation page", {
    status: 502,
    code: "console_response_invalid",
  });
const bindingKey = (query: RuleBindingStatesQuery) =>
  JSON.stringify([query.environmentId, query.appId, query.kind, query.page, query.pageSize]);
const loadKey = (query: RuleLoadObservationQuery) =>
  JSON.stringify([
    query.environmentId,
    query.appId,
    query.bindingId,
    query.instanceId,
    query.page,
    query.pageSize,
  ]);
const historyKey = (query: RuleLoadObservationHistoryQuery) =>
  JSON.stringify([
    query.environmentId,
    query.appId,
    query.bindingId,
    query.instanceId,
    query.page,
    query.pageSize,
  ]);

function validBindingPage(value: RuleBindingStatesPage, query: RuleBindingStatesQuery): boolean {
  return (
    bindingKey(value.query) === bindingKey(query) &&
    !!value.asOf &&
    (value.coverage === "complete" || value.coverage === "partial") &&
    (value.total === null
      ? value.coverage === "partial"
      : Number.isSafeInteger(value.total) && value.total >= 0 && value.coverage === "complete") &&
    typeof value.hasMore === "boolean" &&
    value.items.length <= query.pageSize &&
    (value.total === null ||
      value.hasMore === (query.page - 1) * query.pageSize + value.items.length < value.total) &&
    new Set(value.items.map((item) => item.binding.id)).size === value.items.length &&
    value.items.every(
      (item) =>
        item.binding.environmentId === query.environmentId &&
        (query.appId === null || item.binding.appId === query.appId) &&
        (query.kind === null || item.binding.kind === query.kind) &&
        (item.state === "configured_empty"
          ? item.ruleCount === 0
          : item.state === "current_with_rules"
            ? item.ruleCount !== null && item.ruleCount > 0
            : item.ruleCount === null) &&
        !(item.state === "not_read" && item.hasLastKnownGood),
    )
  );
}
export function validLoadPage(
  value: RuleLoadObservationPage,
  query: RuleLoadObservationQuery,
): boolean {
  const targets = value.targets;
  const counts = [targets.expected, targets.observed, targets.stale, targets.notObserved];
  return (
    loadKey(value.query) === loadKey(query) &&
    !!value.asOf &&
    (value.coverage === "complete" || value.coverage === "partial") &&
    (value.total === null
      ? value.coverage === "partial"
      : Number.isSafeInteger(value.total) && value.total >= 0 && value.coverage === "complete") &&
    (counts.every((count) => count === null) ||
      counts.every((count) => count !== null && Number.isSafeInteger(count) && count >= 0)) &&
    (targets.expected === null ||
      (targets.observed !== null &&
        targets.notObserved !== null &&
        targets.observed + targets.notObserved === targets.expected)) &&
    (targets.observed === null || targets.stale === null || targets.stale <= targets.observed) &&
    (value.total === null ||
      value.hasMore === (query.page - 1) * query.pageSize + value.items.length < value.total) &&
    value.items.length <= query.pageSize &&
    new Set(value.items.map((item) => `${item.bindingId}\u0000${item.instanceId}`)).size ===
      value.items.length &&
    value.items.every(
      (item) =>
        item.bindingId &&
        item.instanceId &&
        item.processId &&
        (item.eventKind === null
          ? item.receivedAt === null && item.observedAt === null
          : item.receivedAt !== null && item.observedAt !== null) &&
        (item.freshness === "unknown" ? item.receivedAt === null : item.receivedAt !== null),
    )
  );
}

const catalogUsageKey = (query: RuleCatalogUsageQuery) =>
  JSON.stringify([
    query.environmentId,
    [...query.bindings]
      .map(({ bindingId, appId }) => [bindingId, appId])
      .sort(([left], [right]) => String(left).localeCompare(String(right))),
  ]);

/**
 * Reads bounded app-scoped observation pages for the visible rule catalog.
 * Each response remains authoritative for its own app; missing or partial data
 * is preserved as unknown rather than converted into zero usage.
 */
export function createRuleCatalogUsageResource(
  port: RuleObservationPort,
  access: QueryAccessObserver,
) {
  return createOwnedQueryResource<RuleCatalogUsageQuery, RuleCatalogUsagePage>(access, {
    keyOf: catalogUsageKey,
    async read(query, signal) {
      const bindings = [
        ...new Map(query.bindings.map((item) => [item.bindingId, item])).values(),
      ].sort((left, right) => left.bindingId.localeCompare(right.bindingId));
      if (
        !query.environmentId.trim() ||
        bindings.length > 20 ||
        bindings.some((item) => !item.bindingId.trim() || !item.appId.trim())
      ) {
        throw invalid();
      }
      const applications = await Promise.all(
        bindings.map(async ({ appId, bindingId }) => {
          const request: RuleLoadObservationQuery = {
            environmentId: query.environmentId,
            appId,
            bindingId,
            instanceId: null,
            page: 1,
            pageSize: 100,
          };
          const page = await port.readRuleLoadObservations(request, signal);
          if (!validLoadPage(page, request)) throw invalid();
          return [bindingId, page] as const;
        }),
      );
      return {
        query: { environmentId: query.environmentId, bindings },
        bindings: Object.fromEntries(applications),
      };
    },
    classify: (page) =>
      Object.values(page.bindings).some((item) => item.coverage === "partial")
        ? "partial"
        : Object.keys(page.bindings).length
          ? "ready"
          : "empty",
  });
}

/** Owns provider binding-state reads independently from the rule-row catalog. */
export function createRuleBindingStatesResource(
  port: RuleObservationPort,
  access: QueryAccessObserver,
) {
  return createOwnedQueryResource<RuleBindingStatesQuery, RuleBindingStatesPage>(access, {
    keyOf: bindingKey,
    async read(query, signal) {
      const page = await port.readBindingStates(query, signal);
      if (!validBindingPage(page, query)) throw invalid();
      return page;
    },
    classify: (page) =>
      page.coverage === "partial" ? "partial" : page.items.length ? "ready" : "empty",
  });
}

/** Owns a binding-specific runtime query; cancellation and owner keys prevent stale cross-selection results. */
export function createRuleLoadObservationResource(
  port: RuleObservationPort,
  access: QueryAccessObserver,
) {
  return createOwnedQueryResource<RuleLoadObservationQuery, RuleLoadObservationPage>(access, {
    keyOf: loadKey,
    async read(query, signal) {
      const page = await port.readRuleLoadObservations(query, signal);
      if (!validLoadPage(page, query)) throw invalid();
      return page;
    },
    classify: (page) =>
      page.coverage === "partial" ? "partial" : page.items.length ? "ready" : "empty",
  });
}

/** Owns historical facts separately so they cannot affect current usage totals. */
export function createRuleLoadObservationHistoryResource(
  port: RuleObservationPort,
  access: QueryAccessObserver,
) {
  return createOwnedQueryResource<RuleLoadObservationHistoryQuery, RuleLoadObservationHistoryPage>(
    access,
    {
      keyOf: historyKey,
      async read(query, signal) {
        const page = await port.readRuleLoadObservationHistory(query, signal);
        if (
          historyKey(page.query) !== historyKey(query) ||
          !page.asOf ||
          (page.coverage !== "complete" && page.coverage !== "partial") ||
          (page.total === null
            ? page.coverage !== "partial"
            : !Number.isSafeInteger(page.total) ||
              page.total < 0 ||
              page.coverage !== "complete") ||
          page.items.length > query.pageSize ||
          (page.total !== null &&
            page.hasMore !== (query.page - 1) * query.pageSize + page.items.length < page.total) ||
          page.items.some(
            (entry) =>
              !entry.observationId ||
              entry.observation.bindingId !== query.bindingId ||
              !entry.observation.processEpoch ||
              entry.observation.eventKind === null,
          )
        ) {
          throw invalid();
        }
        return page;
      },
      classify: (page) =>
        page.coverage === "partial" ? "partial" : page.items.length ? "ready" : "empty",
    },
  );
}
