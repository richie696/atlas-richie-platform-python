/** Stable Rules-page URL sections; labels remain in the rules locale catalog. */
export const RULE_PAGE_SECTION = Object.freeze({
  Catalog: "catalog",
  Runtime: "runtime",
  Bindings: "bindings",
  Drafts: "drafts",
  Editor: "editor",
  Publications: "publications",
  Recovery: "recovery",
} as const);

export type RulePageSection = (typeof RULE_PAGE_SECTION)[keyof typeof RULE_PAGE_SECTION];

const RULE_PAGE_SECTIONS: readonly RulePageSection[] = Object.freeze(
  Object.values(RULE_PAGE_SECTION),
);

/**
 * Resolve untrusted URL section state and preserve legacy binding deep links.
 *
 * A binding-only URL opens that binding's editor. Otherwise new visits start in the rule catalog.
 */
export function resolveRulePageSection(
  value: string | undefined,
  bindingId: string | undefined,
  publicationId: string | undefined,
  versionId: string | undefined,
): RulePageSection {
  if (value && RULE_PAGE_SECTIONS.includes(value as RulePageSection))
    return value as RulePageSection;
  if (publicationId || versionId) return RULE_PAGE_SECTION.Publications;
  return bindingId ? RULE_PAGE_SECTION.Editor : RULE_PAGE_SECTION.Catalog;
}

/** Return the top-level section selected by a detail/workflow section. */
export function primaryRulePageSection(
  section: RulePageSection,
):
  | typeof RULE_PAGE_SECTION.Catalog
  | typeof RULE_PAGE_SECTION.Runtime
  | typeof RULE_PAGE_SECTION.Bindings
  | "maintenance" {
  if (
    section === RULE_PAGE_SECTION.Drafts ||
    section === RULE_PAGE_SECTION.Editor ||
    section === RULE_PAGE_SECTION.Publications ||
    section === RULE_PAGE_SECTION.Recovery
  )
    return "maintenance";
  return section;
}
