import {
  Children,
  isValidElement,
  useEffect,
  useMemo,
  useState,
  type ComponentProps,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import { MarkdownHooks } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import rehypeSlug from "rehype-slug";
import rehypeShikiFromHighlighter from "@shikijs/rehype/core";
import { createHighlighterCore } from "shiki/core";
import { createJavaScriptRegexEngine } from "shiki/engine/javascript";
import { VFile } from "vfile";
import type { Element, Root } from "hast";
import type { PluggableList } from "unified";
import { ArrowLeftIcon, ArrowRightIcon } from "@phosphor-icons/react";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { getDocumentationHeadings, type DocumentationArticle } from "../model/documentation";
import { MermaidDiagram } from "./MermaidDiagram";
import styles from "./DocumentationPage.module.scss";

const markdownPlugins = [remarkGfm, remarkMath];
const highlighter = createHighlighterCore({
  themes: [import("@shikijs/themes/github-dark")],
  langs: [
    import("@shikijs/langs/bash"),
    import("@shikijs/langs/json"),
    import("@shikijs/langs/yaml"),
  ],
  engine: createJavaScriptRegexEngine(),
});

const shikiTransformer = highlighter.then((instance) =>
  rehypeShikiFromHighlighter(instance, {
    theme: "github-dark",
    fallbackLanguage: "bash",
    addLanguageClass: true,
  }),
);

function rehypeDocumentationShiki() {
  return async (tree: Root, file: VFile) => {
    const transform = await shikiTransformer;
    const mermaidBlocks: Element[] = [];
    const preserveMermaid = (node: Root | Element) => {
      for (const child of node.children) {
        if (child.type !== "element") continue;
        const classes = child.properties.className;
        if (
          child.tagName === "code" &&
          Array.isArray(classes) &&
          classes.includes("language-mermaid")
        ) {
          mermaidBlocks.push(child);
          child.properties.className = ["mermaid-source"];
          continue;
        }
        preserveMermaid(child);
      }
    };
    preserveMermaid(tree);

    const transformed = await transform(tree, file, () => undefined);
    for (const block of mermaidBlocks) block.properties.className = ["language-mermaid"];
    return transformed;
  };
}

const rehypePlugins: PluggableList = [rehypeSlug, rehypeDocumentationShiki, rehypeKatex];

function plainText(value: ReactNode): string {
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (Array.isArray(value)) return value.map(plainText).join("");
  if (isValidElement<{ children?: ReactNode }>(value)) return plainText(value.props.children);
  return "";
}

function MarkdownCode({ className, children }: ComponentProps<"code">) {
  if (className?.split(/\s+/).includes("language-mermaid")) {
    return <MermaidDiagram source={plainText(children).replace(/\n$/, "")} />;
  }
  return <code className={className}>{children}</code>;
}

function MarkdownPre({ children, style }: ComponentProps<"pre">) {
  const child = Children.count(children) === 1 ? Children.only(children) : undefined;
  if (isValidElement(child) && child.type === MermaidDiagram) return child;
  return (
    <pre className={styles.codeBlock} style={style}>
      {children}
    </pre>
  );
}

const markdownComponents = {
  code: MarkdownCode,
  pre: MarkdownPre,
  table: ({ children }: ComponentProps<"table">) => (
    <div className={styles.tableWrap}>
      <table className={styles.table}>{children}</table>
    </div>
  ),
  // Markdown 的 `![alt](src "caption")` 渲染成 figure：alt 是无障碍名称，
  // 引号里的标题是可见图注。两者不共用一个字符串，图注才能写「这张图回答什么问题」
  // 而不是重复一遍替代文本。
  img: ({ src, alt, title }: ComponentProps<"img">) => (
    <figure className={styles.figure}>
      <img src={src} alt={alt ?? ""} loading="lazy" decoding="async" />
      {title ? <figcaption className={styles.figureCaption}>{title}</figcaption> : null}
    </figure>
  ),
  a: ({ href, children, ...props }: ComponentProps<"a">) => {
    const external = href?.startsWith("https://") || href?.startsWith("http://");
    return (
      <a
        href={href}
        {...props}
        target={external ? "_blank" : undefined}
        rel={external ? "noreferrer" : undefined}
      >
        {children}
      </a>
    );
  },
};

/** Render localized Markdown through the shared safe parser and its math/code/diagram plugins. */
export function DocumentationArticleView({
  article,
  groupTitle,
  previous,
  next,
  onOpen,
}: {
  readonly article: DocumentationArticle;
  readonly groupTitle: string;
  readonly previous?: DocumentationArticle;
  readonly next?: DocumentationArticle;
  readonly onOpen: (id: string) => void;
}) {
  const { t } = useTranslation();
  const headings = useMemo(() => getDocumentationHeadings(article.markdown), [article.markdown]);
  const [activeHeading, setActiveHeading] = useState(headings[0]?.id ?? "");
  const [renderedMarkdown, setRenderedMarkdown] = useState(article.markdown);

  // Switching the interface language keeps the same article id, so the component is not
  // remounted and the remembered heading id no longer exists in the new document. Reset
  // it during render — React's documented "adjust state when an input changes" pattern —
  // instead of inside the effect, where a direct setState only buys an extra render pass.
  if (renderedMarkdown !== article.markdown) {
    setRenderedMarkdown(article.markdown);
    setActiveHeading(headings[0]?.id ?? "");
  }

  useEffect(() => {
    const targets = headings
      .map((heading) => document.getElementById(heading.id))
      .filter((target): target is HTMLElement => target !== null);
    if (targets.length === 0 || typeof IntersectionObserver === "undefined") return;

    const observer = new IntersectionObserver(
      (entries) => {
        const visibleHeadings = entries
          .filter((entry) => entry.isIntersecting)
          .sort((left, right) => left.boundingClientRect.top - right.boundingClientRect.top);
        if (visibleHeadings[0]) setActiveHeading(visibleHeadings[0].target.id);
      },
      { rootMargin: "-18% 0px -68% 0px", threshold: 0 },
    );
    targets.forEach((target) => observer.observe(target));
    return () => observer.disconnect();
  }, [article.markdown, headings]);
  return (
    <div className={styles.articleLayout}>
      <aside className={styles.tocRail}>
        <nav className={styles.toc} aria-label={t("documentation.onThisPage")}>
          <strong>{t("documentation.onThisPage")}</strong>
          <div className={styles.tocLinks}>
            {headings.map((heading) => (
              <ActionButton
                key={heading.id}
                variant="ghost"
                aria-current={activeHeading === heading.id ? "location" : undefined}
                onClick={() => {
                  setActiveHeading(heading.id);
                  const target = document.getElementById(heading.id);
                  target?.focus({ preventScroll: true });
                  target?.scrollIntoView({ block: "start" });
                }}
              >
                {heading.title}
              </ActionButton>
            ))}
          </div>
        </nav>
      </aside>
      <article className={styles.article}>
        <header className={styles.articleHeader}>
          <span className={styles.eyebrow}>{groupTitle}</span>
          <h2>{article.title}</h2>
          <p>{article.summary}</p>
        </header>
        <dl className={styles.outcomes}>
          <div>
            <dt>{t("documentation.before")}</dt>
            <dd>{article.prerequisite}</dd>
          </div>
          <div>
            <dt>{t("documentation.after")}</dt>
            <dd>{article.outcome}</dd>
          </div>
        </dl>
        <div className={styles.markdownBody}>
          <MarkdownHooks
            remarkPlugins={markdownPlugins}
            rehypePlugins={rehypePlugins}
            components={markdownComponents}
            fallback={<p>{t("documentation.rendering")}</p>}
          >
            {article.markdown}
          </MarkdownHooks>
        </div>
        <p className={styles.scope}>{t("documentation.scope")}</p>
        <footer className={styles.pager}>
          <div>
            {previous && (
              <ActionButton variant="ghost" onClick={() => onOpen(previous.id)}>
                <ArrowLeftIcon aria-hidden />
                <span>
                  {t("documentation.previous")}
                  <br />
                  {previous.title}
                </span>
              </ActionButton>
            )}
          </div>
          <div>
            {next && (
              <ActionButton variant="ghost" onClick={() => onOpen(next.id)}>
                <span>
                  {t("documentation.next")}
                  <br />
                  {next.title}
                </span>
                <ArrowRightIcon aria-hidden />
              </ActionButton>
            )}
          </div>
        </footer>
      </article>
    </div>
  );
}
