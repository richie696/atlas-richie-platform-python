import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { BookOpenIcon, ArrowLeftIcon, ArrowRightIcon } from "@phosphor-icons/react";
import { ROUTE } from "../../../shared/types/navigation";
import type { DashboardPageProps } from "../../../shared/types/dashboard";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { TextField } from "../../../shared/ui/TextField";
import { loadDocumentation } from "../content/catalogs";
import { searchDocumentation, type DocumentationCatalog } from "../model/documentation";
import { DocumentationArticleView } from "./DocumentationArticleView";
import styles from "./DocumentationPage.module.scss";

/** Public, offline-readable manual. Article/search navigation is shareable; no service API is required. */
export function DocumentationPage({
  locale,
  view,
  search = "",
  navigate,
  localeControl,
  embeddedInAppShell = false,
}: Pick<DashboardPageProps, "locale" | "view" | "navigate"> & {
  readonly search?: string;
  readonly localeControl?: ReactNode;
  readonly embeddedInAppShell?: boolean;
}) {
  const { t } = useTranslation();
  const [retry, setRetry] = useState(0);
  const [loaded, setLoaded] = useState<{
    locale: string;
    catalog?: DocumentationCatalog;
    failed?: boolean;
  }>();
  useEffect(() => {
    let current = true;
    void loadDocumentation(locale).then(
      (catalog) => {
        if (current) setLoaded({ locale, catalog });
      },
      () => {
        if (current) setLoaded({ locale, failed: true });
      },
    );
    return () => {
      current = false;
    };
  }, [locale, retry]);
  const catalog = loaded?.locale === locale ? loaded.catalog : undefined;
  const selected = view || "welcome";
  const article = catalog?.articles.find((item) => item.id === selected);
  const matches = catalog ? searchDocumentation(catalog, search) : [];
  const index = catalog?.articles.findIndex((item) => item.id === selected) ?? -1;
  const open = (id: string) => {
    navigate(ROUTE.Documentation, { view: id, search: undefined });
    window.scrollTo({ top: 0, behavior: "instant" });
  };
  return (
    <div className={styles.center} data-documentation-center>
      {embeddedInAppShell ? (
        <h1 className={styles.visuallyHidden}>{t("documentation.title")}</h1>
      ) : (
        <header className={styles.intro}>
          <div>
            <span className={styles.eyebrow}>
              <BookOpenIcon size={18} aria-hidden /> ATLAS RICHIE SENTINEL
            </span>
            <h1>{t("documentation.title")}</h1>
            <p>{t("documentation.subtitle")}</p>
          </div>
          <div className={styles.tools}>
            {localeControl}
            <ActionButton onClick={() => navigate(ROUTE.Overview)}>
              <ArrowLeftIcon aria-hidden />
              {t("documentation.console")}
            </ActionButton>
          </div>
        </header>
      )}
      <div className={styles.layout}>
        <aside className={styles.sidebar}>
          <TextField
            label={t("documentation.search")}
            placeholder={t("documentation.searchPlaceholder")}
            value={search}
            onChange={(value) =>
              navigate(
                ROUTE.Documentation,
                { view: selected, search: value.slice(0, 160) },
                { history: "replace" },
              )
            }
          />
          <nav aria-label={t("documentation.learningPath")}>
            {catalog?.groups.map((group, groupIndex) => (
              <section key={group.id} className={styles.group}>
                <h2>
                  <span>{String(groupIndex + 1).padStart(2, "0")}</span>
                  {t(group.titleKey)}
                </h2>
                <p className={styles.groupDescription}>{t(group.descriptionKey)}</p>
                {catalog.articles
                  .filter((item) => item.group === group.id)
                  .map((item) => (
                    <ActionButton
                      key={item.id}
                      variant="ghost"
                      className={styles.navItem}
                      aria-current={!search.trim() && selected === item.id ? "page" : undefined}
                      onClick={() => open(item.id)}
                    >
                      {item.title}
                    </ActionButton>
                  ))}
              </section>
            ))}
          </nav>
        </aside>
        <div className={styles.workspace} aria-busy={!catalog && !loaded?.failed}>
          {!catalog ? (
            <section className={styles.article} role="status">
              <h2>
                {loaded?.locale === locale && loaded.failed
                  ? t("documentation.loadFailed")
                  : t("documentation.loading")}
              </h2>
              {loaded?.locale === locale && loaded.failed && (
                <ActionButton
                  onClick={() => {
                    setLoaded(undefined);
                    setRetry((n) => n + 1);
                  }}
                >
                  {t("documentation.retry")}
                </ActionButton>
              )}
            </section>
          ) : search.trim() ? (
            <section className={styles.article}>
              <h2>{t("documentation.results")}</h2>
              <p role="status">{t("documentation.resultTotal", { total: matches.length })}</p>
              {matches.length === 0 && <p>{t("documentation.noResults")}</p>}
              <div className={styles.results}>
                {matches.map((item) => (
                  <div key={item.id} className={styles.result}>
                    <ActionButton variant="ghost" onClick={() => open(item.id)}>
                      {item.title}
                      <ArrowRightIcon aria-hidden />
                    </ActionButton>
                    <p>{item.summary}</p>
                  </div>
                ))}
              </div>
              <ActionButton onClick={() => navigate(ROUTE.Documentation, { view: selected })}>
                {t("documentation.clearSearch")}
              </ActionButton>
            </section>
          ) : article ? (
            <DocumentationArticleView
              key={article.id}
              article={article}
              groupTitle={t(
                catalog.groups.find((group) => group.id === article.group)?.titleKey ??
                  "documentation.group.start.title",
              )}
              previous={catalog.articles[index - 1]}
              next={catalog.articles[index + 1]}
              onOpen={open}
            />
          ) : (
            <section className={styles.article}>
              <h2>{t("documentation.notFound")}</h2>
              <ActionButton onClick={() => open("welcome")}>
                {t("documentation.start")}
              </ActionButton>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
