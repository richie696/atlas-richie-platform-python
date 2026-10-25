/** Stable documentation navigation tree shared by every locale. */
export const DOCUMENTATION_TREE = [
  { id: "start", articleIds: ["welcome", "ui-map", "concepts", "glossary"] },
  {
    id: "interface",
    articleIds: [
      "screen-overview",
      "screen-applications",
      "screen-rules",
      "screen-observation",
      "screen-system",
    ],
  },
  { id: "deploy", articleIds: ["setup", "sources", "accounts"] },
  { id: "connect", articleIds: ["java", "go", "rust", "verify"] },
  { id: "observe", articleIds: ["metrics", "hosts", "load-observation", "daily-operations"] },
  { id: "govern", articleIds: ["first-rule", "rule-types", "rule-fields", "capacity", "versions"] },
  { id: "reference", articleIds: ["protocols", "troubleshooting", "operations", "faq"] },
] as const;

/** Canonical article order used by the sidebar, search results, and previous/next links. */
export const DOCUMENTATION_ARTICLE_IDS = DOCUMENTATION_TREE.flatMap((group) => group.articleIds);
