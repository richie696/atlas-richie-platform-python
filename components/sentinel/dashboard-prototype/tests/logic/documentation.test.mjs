import assert from "node:assert/strict";
import { existsSync, readFileSync, statSync } from "node:fs";
import { test } from "node:test";
import { parse as parseYaml } from "yaml";
import { remark } from "remark";
import remarkGfm from "remark-gfm";
import { searchDocumentation } from "../../src/features/documentation/model/documentation";
import { DOCUMENTATION_TREE } from "../../src/features/documentation/content/tree";
import { accessFor, pathFor, routeFromPath, ROUTE } from "../../src/app/router/route.constants";

const locales = ["zh-CN", "en-US", "ja-JP"];
const articleIds = DOCUMENTATION_TREE.flatMap((group) => group.articleIds);

function loadLocale(locale) {
  const groups = DOCUMENTATION_TREE.map((group) => ({ ...group }));
  const articles = articleIds.map((id) => {
    const source = readFileSync(`src/features/documentation/content/${locale}/${id}.md`, "utf8");
    const frontMatter = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/.exec(source);
    assert.ok(frontMatter, `${locale}/${id}.md must have YAML front matter`);
    const metadata = parseYaml(frontMatter[1]);
    const group = DOCUMENTATION_TREE.find((candidate) => candidate.articleIds.includes(id));
    return {
      id,
      group: group.id,
      ...metadata,
      markdown: source.slice(frontMatter[0].length).trim(),
    };
  });
  return { groups, articles };
}

const catalogs = locales.map(loadLocale);
const processor = remark().use(remarkGfm);
const ast = (article) => processor.parse(article.markdown);
const textOf = (node) => {
  if (typeof node.value === "string") return node.value;
  return (node.children ?? []).map(textOf).join("");
};
const nodesOfType = (node, type) => [
  ...(node.type === type ? [node] : []),
  ...(node.children ?? []).flatMap((child) => nodesOfType(child, type)),
];

test("DOCS: Markdown manuals preserve the canonical tree and translated article identities", () => {
  const identity = (catalog) => catalog.articles.map((article) => [article.id, article.group]);
  for (const catalog of catalogs) {
    assert.deepEqual(identity(catalog), identity(catalogs[0]));
    assert.equal(new Set(catalog.articles.map((article) => article.id)).size, articleIds.length);
    assert.deepEqual(
      catalog.groups.map((group) => group.id),
      DOCUMENTATION_TREE.map((group) => group.id),
    );
    for (const article of catalog.articles) {
      assert.ok(article.title.trim() && article.summary.trim());
      assert.ok(article.prerequisite.trim() && article.outcome.trim());
      assert.ok(
        nodesOfType(ast(article), "heading").length > 0,
        `${article.id} needs Markdown headings`,
      );
    }
  }
});

test("DOCS: localized Markdown keeps actionable content and rectangular GFM tables", () => {
  for (const catalog of catalogs) {
    for (const article of catalog.articles) {
      const tree = ast(article);
      assert.ok(
        nodesOfType(tree, "list").length +
          nodesOfType(tree, "code").length +
          nodesOfType(tree, "table").length >
          0,
        `${article.id} has no steps, code block, or table`,
      );
      for (const table of nodesOfType(tree, "table")) {
        const widths = table.children.map((row) => row.children.length);
        assert.ok(widths.length > 1, `${article.id} table needs a header and rows`);
        assert.ok(
          widths.every((width) => width === widths[0]),
          `${article.id} table must be rectangular`,
        );
      }
    }
  }
});

test("DOCS: search includes Markdown code and table source, while preserving deep links", () => {
  for (const catalog of catalogs) {
    assert.ok(
      searchDocumentation(catalog, "statIntervalInMs").some((article) => article.id === "go"),
    );
    assert.ok(
      searchDocumentation(catalog, "METRICS_CLIENT_PKCS12").some(
        (article) => article.id === "java",
      ),
    );
    assert.ok(searchDocumentation(catalog, "sentinel-console setup-window").length > 0);
    assert.deepEqual(searchDocumentation(catalog, "no-such-document-928319"), []);
    assert.deepEqual(searchDocumentation(catalog, "  "), catalog.articles);
  }
  assert.equal(accessFor(ROUTE.Documentation), "public");
  const parsed = routeFromPath(pathFor(ROUTE.Documentation, { view: "capacity", search: "QPS" }));
  assert.equal(parsed.route, ROUTE.Documentation);
  assert.equal(parsed.context.view, "capacity");
  assert.equal(parsed.context.search, "QPS");
  assert.equal(
    routeFromPath(pathFor(ROUTE.Documentation, { view: "obsolete-article" })).context.view,
    "obsolete-article",
  );
});

test("DOCS: protocol Markdown keeps the managed binding fail-closed boundary and envelope directions", () => {
  for (const catalog of catalogs) {
    const protocols = catalog.articles.find((article) => article.id === "protocols");
    const versions = catalog.articles.find((article) => article.id === "versions");
    const sources = catalog.articles.find((article) => article.id === "sources");
    assert.ok(protocols && versions && sources);
    const protocolText = protocols.markdown;
    for (const token of [
      "binding_id",
      "rule_kind",
      "profile_id",
      "RuleSetSnapshotInvalid",
      "atlas-richie-contracts",
    ])
      assert.ok(protocolText.includes(token), `protocols must mention ${token}`);
    assert.ok(versions.markdown.includes("RuleSetSnapshotInvalid"));
    assert.ok(protocolText.includes("Runtime Reporter → Collector"));
    assert.ok(protocolText.includes("Console → Nacos / Consul → Runtime"));
    assert.ok(protocolText.includes("target_version_id"));
    assert.ok(sources.markdown.includes("Console API"));
    assert.ok(sources.markdown.includes("Nacos / Consul"));
  }
});

test("DOCS: language-specific prose stays localized outside executable code fences", () => {
  const cjk = /[一-鿿]/;
  const english = catalogs[1];
  for (const article of english.articles) {
    for (const field of ["title", "summary", "prerequisite", "outcome"])
      assert.ok(!cjk.test(article[field]), `en-US ${article.id}.${field} contains CJK`);
    const tree = ast(article);
    const prose = (tree.children ?? [])
      .filter((node) => node.type !== "code")
      .map(textOf)
      .join(" ");
    assert.ok(!cjk.test(prose), `en-US ${article.id} prose contains CJK`);
  }
  const japanese = catalogs[2];
  const japaneseText = JSON.stringify(japanese);
  for (const term of ["封装", "部署", "持久", "解包", "配置中心"])
    assert.ok(!japaneseText.includes(term), `ja-JP copy contains ${term}`);
});

/**
 * Mermaid 图的标签是正文，不是代码。
 *
 * 图里的方框文字按语言翻译是正确做法，所以不能逐字比对。但图的**拓扑**必须一致：
 * 节点、连线、分类声明一字不改。剥掉标签文字后比对，恰好守住这一点。
 */
function normalizeMermaid(source) {
  return source
    .replace(/\[[^\]]*\]/g, "[]")
    .replace(/\([^)]*\)/g, "()")
    .replace(/\{[^}]*\}/g, "{}")
    .replace(/"[^"]*"/g, '""');
}

function codeShape(article) {
  return nodesOfType(ast(article), "code").map((code) => [
    code.lang ?? null,
    code.lang === "mermaid" ? normalizeMermaid(code.value) : code.value,
  ]);
}

test("DOCS: every locale keeps the same article structure", () => {
  // 三语结构一致不只是文章数与章节数一致：每一节有没有操作步骤、代码块、提示和表格，
  // 以及步骤条数、表格行列数，都必须一致。少一条步骤就是少一步可照做的动作。
  const shape = (article) => {
    const tree = ast(article);
    return {
      headings: nodesOfType(tree, "heading").map((heading) => heading.depth),
      lists: nodesOfType(tree, "list").map((list) => list.children.length),
      code: codeShape(article),
      tables: nodesOfType(tree, "table").map((table) =>
        table.children.map((row) => row.children.length).join("x"),
      ),
      quotes: nodesOfType(tree, "blockquote").length,
      images: nodesOfType(tree, "image")
        .map((image) => (image.url ?? "").split("/").pop())
        .sort(),
    };
  };
  for (const article of catalogs[0].articles) {
    const base = shape(article);
    for (const [index, locale] of locales.entries()) {
      if (index === 0) continue;
      const translated = catalogs[index].articles.find((candidate) => candidate.id === article.id);
      assert.ok(translated, `${locale} is missing article ${article.id}`);
      assert.deepEqual(
        shape(translated),
        base,
        `${article.id} structure differs between zh-CN and ${locale}`,
      );
    }
  }
});

test("DOCS: screen articles reference captured figures that exist for every locale", () => {
  const manifest = JSON.parse(readFileSync("public/docs/figures/manifest.json", "utf8"));
  const captured = new Set(manifest.figures.map((figure) => figure.path));

  for (const [index, locale] of locales.entries()) {
    for (const article of catalogs[index].articles) {
      const images = nodesOfType(ast(article), "image");
      for (const image of images) {
        const url = image.url ?? "";
        // The figure path carries its own locale directory: the console UI differs per
        // locale, so a Chinese screenshot is not an English screenshot.
        assert.ok(
          url.startsWith(`docs/figures/${locale}/`),
          `${locale}/${article.id} figure must live under its own locale: ${url}`,
        );
        const filePath = `public/${url}`;
        assert.ok(existsSync(filePath), `${locale}/${article.id} figure file is missing: ${url}`);
        assert.ok(statSync(filePath).size > 0, `${locale}/${article.id} figure file is empty: ${url}`);
        assert.ok(captured.has(url), `${locale}/${article.id} figure is not in the capture manifest: ${url}`);
        // Alternative text is the accessible name; an empty one leaves the figure unreadable.
        assert.ok(String(image.alt ?? "").trim().length > 0, `${locale}/${article.id} figure needs alt text`);
      }
    }
  }

  // The same article must carry the same figures in every language.
  for (const articleId of articleIds) {
    const perLocale = locales.map((locale) => {
      const index = locales.indexOf(locale);
      const article = catalogs[index].articles.find((candidate) => candidate.id === articleId);
      return nodesOfType(ast(article), "image")
        .map((image) => (image.url ?? "").replace(`docs/figures/${locale}/`, ""))
        .sort();
    });
    const [first, ...rest] = perLocale;
    for (const other of rest) {
      assert.deepEqual(
        other,
        first,
        `${articleId} must reference the same figures in every locale`,
      );
    }
  }
});
