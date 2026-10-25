import { parse as parseYaml } from "yaml";
import { z } from "zod";
import { DOCUMENTATION_TREE, DOCUMENTATION_ARTICLE_IDS } from "./tree";
import type { DocumentationArticle, DocumentationCatalog } from "../model/documentation";

/** Locale Markdown files are separate lazy chunks; only documentation routes load them. */
const markdownLoaders = import.meta.glob<string>("./{zh-CN,en-US,ja-JP}/*.md", {
  query: "?raw",
  import: "default",
});

const ArticleMetadataSchema = z.object({
  title: z.string().min(1),
  summary: z.string(),
  prerequisite: z.string(),
  outcome: z.string(),
});

function readFrontMatter(
  source: string,
  articleId: string,
): {
  metadata: z.infer<typeof ArticleMetadataSchema>;
  markdown: string;
} {
  const match = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/.exec(source);
  if (!match) throw new Error(`Documentation article is missing front matter: ${articleId}`);
  const metadata = ArticleMetadataSchema.parse(parseYaml(match[1]));
  return { metadata, markdown: source.slice(match[0].length).trim() };
}

/** Load a locale's navigation tree and Markdown articles; missing tree entries fail visibly. */
export async function loadDocumentation(locale: string): Promise<DocumentationCatalog> {
  if (!new Set(["zh-CN", "en-US", "ja-JP"]).has(locale)) {
    throw new Error("Unsupported documentation locale");
  }

  const articleGroups = new Map<string, string>();
  for (const group of DOCUMENTATION_TREE) {
    for (const articleId of group.articleIds) articleGroups.set(articleId, group.id);
  }

  const loadedArticles = await Promise.all(
    DOCUMENTATION_ARTICLE_IDS.map(async (articleId): Promise<DocumentationArticle> => {
      const path = `./${locale}/${articleId}.md`;
      const load = markdownLoaders[path];
      if (!load)
        throw new Error(`Documentation article is missing from locale ${locale}: ${articleId}`);
      const source = await load();
      const { metadata, markdown } = readFrontMatter(source, articleId);
      return {
        id: articleId,
        group: articleGroups.get(articleId) ?? "",
        ...metadata,
        markdown,
      };
    }),
  );

  return {
    groups: DOCUMENTATION_TREE.map((group) => ({
      id: group.id,
      titleKey: `documentation.group.${group.id}.title` as const,
      descriptionKey: `documentation.group.${group.id}.description` as const,
      articleIds: group.articleIds,
    })),
    articles: loadedArticles,
  };
}
