import { RULE_KINDS, type RuleKind } from "./ruleKinds";
import { validRuleBinding, type RuleBinding } from "./ruleSet";
import type { RuleRecord } from "./ruleSet";
import { validRuleValue } from "./ruleValue";
export const MAX_BINDING_PAGE_SIZE = 100;
export const MAX_BINDING_SEARCH_LENGTH = 200;
export interface BindingQuery {
  readonly environmentId: string;
  readonly appId: string | null;
  readonly kind: RuleKind | null;
  readonly search: string;
  readonly page: number;
  readonly pageSize: number;
}
export interface BindingPage {
  readonly query: BindingQuery;
  readonly total: number;
  readonly items: readonly RuleBinding[];
}

export type RuleCatalogCoverage = "complete" | "partial";
export type RuleCatalogFreshness = "current" | "stale";
export type RuleCatalogIssueReason = "source_unavailable" | "content_invalid" | "not_read";

export type RuleCatalogQuery = BindingQuery;

export interface RuleCatalogEntry {
  readonly binding: RuleBinding;
  readonly record: RuleRecord;
  readonly snapshot: {
    readonly checksum: string;
    readonly sourceRevision: string | null;
    readonly versionId: string | null;
    readonly asOf: string;
  };
  readonly read: { readonly freshness: RuleCatalogFreshness; readonly lastAttemptAt: string };
}

export interface RuleCatalogIssue {
  readonly binding: RuleBinding;
  readonly reason: RuleCatalogIssueReason;
  readonly lastAttemptAt: string | null;
  readonly stale: boolean;
}

export interface RuleCatalogPage {
  readonly query: RuleCatalogQuery;
  readonly asOf: string;
  readonly coverage: RuleCatalogCoverage;
  readonly bindings: {
    readonly total: number;
    readonly current: number;
    readonly stale: number;
    readonly notRead: number;
  };
  readonly total: number | null;
  /** More already-confirmed SQL-projected rows exist; never an estimate of unread sources. */
  readonly hasMore: boolean;
  readonly items: readonly RuleCatalogEntry[];
  readonly issues: readonly RuleCatalogIssue[];
}

export interface RuleCatalogRefreshResult {
  readonly scope: { readonly environmentId: string; readonly appId: string | null };
  readonly asOf: string;
  readonly coverage: RuleCatalogCoverage;
  readonly bindings: {
    readonly total: number;
    readonly attempted: number;
    readonly current: number;
    readonly stale: number;
    readonly notRead: number;
  };
}
/** Query key includes every ownership/filter dimension; never contains credentials or rule bodies. */
export function bindingQueryKey(query: BindingQuery): string {
  return JSON.stringify([
    query.environmentId,
    query.appId,
    query.kind,
    query.search,
    query.page,
    query.pageSize,
  ]);
}
export function validBindingQuery(query: BindingQuery): boolean {
  return (
    !!query.environmentId.trim() &&
    (query.appId === null || !!query.appId.trim()) &&
    (query.kind === null || RULE_KINDS.includes(query.kind)) &&
    query.search.length <= MAX_BINDING_SEARCH_LENGTH &&
    Number.isSafeInteger(query.page) &&
    query.page > 0 &&
    Number.isSafeInteger(query.pageSize) &&
    query.pageSize > 0 &&
    query.pageSize <= MAX_BINDING_PAGE_SIZE
  );
}
/** Internal typed read checks. Final JSON decoding and server search semantics belong to F6. */
export function validBindingPage(value: BindingPage, query: BindingQuery): boolean {
  return (
    validBindingQuery(query) &&
    bindingQueryKey(value.query) === bindingQueryKey(query) &&
    Number.isSafeInteger(value.total) &&
    value.total >= 0 &&
    value.items.length <= query.pageSize &&
    value.items.length <= Math.max(0, value.total - (query.page - 1) * query.pageSize) &&
    new Set(value.items.map((item) => item.id)).size === value.items.length &&
    value.items.every(
      (item) =>
        validRuleBinding(item) &&
        item.environmentId === query.environmentId &&
        (query.appId === null || item.appId === query.appId) &&
        (query.kind === null || item.kind === query.kind),
    )
  );
}

/** Validate exact query ownership and ensure partial projections never claim an exact total. */
export function validRuleCatalogPage(value: RuleCatalogPage, query: RuleCatalogQuery): boolean {
  const coverageCounts = value.bindings;
  return (
    validBindingQuery(query) &&
    bindingQueryKey(value.query) === bindingQueryKey(query) &&
    !!value.asOf &&
    (value.coverage === "complete" || value.coverage === "partial") &&
    [
      coverageCounts.total,
      coverageCounts.current,
      coverageCounts.stale,
      coverageCounts.notRead,
    ].every((count) => Number.isSafeInteger(count) && count >= 0) &&
    coverageCounts.current + coverageCounts.stale + coverageCounts.notRead ===
      coverageCounts.total &&
    (value.coverage === "complete"
      ? value.total !== null &&
        Number.isSafeInteger(value.total) &&
        value.total >= 0 &&
        coverageCounts.current === coverageCounts.total &&
        coverageCounts.stale === 0 &&
        coverageCounts.notRead === 0
      : value.total === null) &&
    typeof value.hasMore === "boolean" &&
    (value.total === null ||
      value.hasMore === (query.page - 1) * query.pageSize + value.items.length < value.total) &&
    value.items.length <= query.pageSize &&
    (value.total === null ||
      value.items.length <= Math.max(0, value.total - (query.page - 1) * query.pageSize)) &&
    value.issues.length <= 100 &&
    value.items.every(
      (item) =>
        validRuleBinding(item.binding) &&
        item.binding.environmentId === query.environmentId &&
        (query.appId === null || item.binding.appId === query.appId) &&
        (query.kind === null || item.binding.kind === query.kind) &&
        item.record.rule.kind === item.binding.kind &&
        validRuleValue(item.record.rule) &&
        !!item.record.id &&
        !!item.snapshot.checksum &&
        !!item.snapshot.asOf &&
        !!item.read.lastAttemptAt &&
        (item.read.freshness === "current" || item.read.freshness === "stale"),
    ) &&
    value.issues.every(
      (issue) =>
        validRuleBinding(issue.binding) &&
        issue.binding.environmentId === query.environmentId &&
        (query.appId === null || issue.binding.appId === query.appId) &&
        (query.kind === null || issue.binding.kind === query.kind) &&
        (issue.reason === "source_unavailable" ||
          issue.reason === "content_invalid" ||
          issue.reason === "not_read"),
    )
  );
}

export function validRuleCatalogRefreshResult(value: RuleCatalogRefreshResult): boolean {
  return (
    !!value.scope.environmentId &&
    (value.scope.appId === null || !!value.scope.appId) &&
    !!value.asOf &&
    (value.coverage === "complete" || value.coverage === "partial") &&
    [
      value.bindings.total,
      value.bindings.attempted,
      value.bindings.current,
      value.bindings.stale,
      value.bindings.notRead,
    ].every((count) => Number.isSafeInteger(count) && count >= 0) &&
    value.bindings.attempted <= 24 &&
    value.bindings.current + value.bindings.stale + value.bindings.notRead === value.bindings.total
  );
}
