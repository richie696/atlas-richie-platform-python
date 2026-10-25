import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import styles from "./DocumentationPage.module.scss";

let mermaidModule: Promise<typeof import("mermaid")> | undefined;

function loadMermaid() {
  mermaidModule ??= import("mermaid").then((module) => {
    module.default.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      theme: "base",
      themeVariables: {
        darkMode: true,
        background: "#13232d",
        primaryColor: "#203b49",
        primaryTextColor: "#e8f1f7",
        primaryBorderColor: "#5e9fc4",
        lineColor: "#7b9aaa",
        secondaryColor: "#173b43",
        tertiaryColor: "#1c493a",
        clusterBkg: "#172b35",
        clusterBorder: "#345364",
        edgeLabelBackground: "#13232d",
        // Let the browser choose its installed CJK font. Mermaid's SVG text
        // measurement does not account for fallback glyph widths consistently.
        fontFamily:
          'Inter, -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC", sans-serif',
        fontSize: "15px",
      },
      flowchart: {
        // XHTML labels are measured by the browser with the actual fallback
        // font, avoiding clipped or partially rendered CJK glyphs in SVG text.
        htmlLabels: true,
        curve: "linear",
        nodeSpacing: 36,
        rankSpacing: 44,
      },
    });
    return module;
  });
  return mermaidModule;
}

/** Lazily render a trusted documentation Mermaid fence with Mermaid's strict security mode. */
export function MermaidDiagram({ source }: { readonly source: string }) {
  const { t } = useTranslation();
  const host = useRef<HTMLDivElement>(null);
  const id = `sentinel-doc-${useId().replaceAll(":", "")}`;
  const [failedSource, setFailedSource] = useState<string | null>(null);
  const failed = failedSource === source;

  useEffect(() => {
    let active = true;
    const hostElement = host.current;
    void loadMermaid()
      .then(({ default: mermaid }) => mermaid.render(id, source))
      .then(({ svg }) => {
        if (!active || !hostElement) return;
        const documentFragment = new DOMParser().parseFromString(svg, "image/svg+xml");
        const diagram = documentFragment.documentElement;
        if (diagram.localName !== "svg" || documentFragment.querySelector("parsererror")) {
          throw new Error("Mermaid returned invalid SVG");
        }
        hostElement.replaceChildren(document.importNode(diagram, true));
      })
      .catch(() => {
        if (active) setFailedSource(source);
      });

    return () => {
      active = false;
      hostElement?.replaceChildren();
    };
  }, [id, source]);

  return (
    <div className={styles.diagram}>
      {failed ? (
        <p role="status">{t("documentation.diagramFailed")}</p>
      ) : (
        <div ref={host} role="img" aria-label={t("documentation.diagramLabel")} />
      )}
    </div>
  );
}
