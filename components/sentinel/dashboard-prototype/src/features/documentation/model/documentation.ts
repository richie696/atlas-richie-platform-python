import { remark } from "remark";
import remarkGfm from "remark-gfm";
import GithubSlugger from "github-slugger";
import type { Root, Heading, PhrasingContent } from "mdast";

/** A translated documentation group in the canonical left-navigation tree. */
export type DocumentationGroupId =
  "start" | "interface" | "deploy" | "connect" | "observe" | "govern" | "reference";

export interface DocumentationGroup {
  readonly id: DocumentationGroupId;
  readonly titleKey: `documentation.group.${DocumentationGroupId}.title`;
  readonly descriptionKey: `documentation.group.${DocumentationGroupId}.description`;
  readonly articleIds: readonly string[];
}

/** One localized Markdown article with display metadata extracted from its YAML front matter. */
export interface DocumentationArticle {
  readonly id: string;
  readonly group: string;
  readonly title: string;
  readonly summary: string;
  readonly prerequisite: string;
  readonly outcome: string;
  readonly markdown: string;
}

/** Locale-specific article content paired with the shared navigation tree. */
export interface DocumentationCatalog {
  readonly groups: readonly DocumentationGroup[];
  readonly articles: readonly DocumentationArticle[];
}

/** Headings used by the article's local table of contents and matching rendered anchors. */
export interface DocumentationHeading {
  readonly depth: number;
  readonly title: string;
  readonly id: string;
}

function phrasingText(value: PhrasingContent): string {
  if (value.type === "text" || value.type === "inlineCode" || value.type === "html") {
    return value.value;
  }
  if (value.type === "image" || value.type === "imageReference") return value.alt ?? "";
  if ("children" in value) return value.children.map(phrasingText).join("");
  return "";
}

function headingText(heading: Heading): string {
  return heading.children.map(phrasingText).join("");
}

/** Parse article headings with the same GitHub-style slug rules used by the rendered Markdown. */
export function getDocumentationHeadings(markdown: string): readonly DocumentationHeading[] {
  const root = remark().use(remarkGfm).parse(markdown) as Root;
  const slugger = new GithubSlugger();
  return root.children
    .filter((node): node is Heading => node.type === "heading")
    .map((heading) => {
      const title = headingText(heading);
      return { depth: heading.depth, title, id: slugger.slug(title) };
    });
}

/** Search article metadata and Markdown source without interpreting HTML or code as executable content. */
export function searchDocumentation(
  catalog: DocumentationCatalog,
  query: string,
): readonly DocumentationArticle[] {
  const terms = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  return catalog.articles.filter((article) => {
    const text = [
      article.title,
      article.summary,
      article.prerequisite,
      article.outcome,
      article.markdown,
    ]
      .join(" ")
      .toLocaleLowerCase();
    return terms.every((term) => text.includes(term));
  });
}
