import { RULE_KINDS, type RuleKind } from "./ruleKinds";
import { validRuleBinding, type RuleBinding } from "./ruleSet";
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
