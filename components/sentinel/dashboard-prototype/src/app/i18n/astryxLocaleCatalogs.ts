import type { MessagesByLocale } from "@astryxdesign/core/i18n";
import type { Locale } from "./locales";

type AstryxCatalog = MessagesByLocale[string];

const loaders: Partial<Record<Locale, () => Promise<AstryxCatalog>>> = Object.freeze({
  "zh-CN": async () => (await import("@astryxdesign/core/locales/zh-CN.json")).default,
  "ja-JP": async () => (await import("@astryxdesign/core/locales/ja-JP.json")).default,
});

const EMPTY_CATALOGS: MessagesByLocale = Object.freeze({});

type NonEnglishLocale = Exclude<Locale, "en-US">;
type NonEnglishLoaders = Readonly<Partial<Record<NonEnglishLocale, () => Promise<AstryxCatalog>>>>;
type AstryxCatalogOwner = Readonly<{
  load(locale: Locale): Promise<MessagesByLocale>;
  getLoaded(locale: Locale): MessagesByLocale;
}>;

/** Creates the locale catalog cache so loading and retry behavior can be tested without network access. */
export function createAstryxLocaleCatalogOwner(loaders: NonEnglishLoaders): AstryxCatalogOwner {
  const pendingCatalogs = new Map<NonEnglishLocale, Promise<MessagesByLocale>>();
  const loadedCatalogs = new Map<NonEnglishLocale, MessagesByLocale>();

  const load = (locale: Locale): Promise<MessagesByLocale> => {
    if (locale === "en-US") return Promise.resolve(EMPTY_CATALOGS);

    const loaded = loadedCatalogs.get(locale);
    if (loaded) return Promise.resolve(loaded);

    const pending = pendingCatalogs.get(locale);
    if (pending) return pending;

    const loadCatalog = loaders[locale];
    if (!loadCatalog) return Promise.reject(new Error("Unsupported Astryx locale"));

    const request = loadCatalog()
      .then((catalog) => {
        const messages = Object.freeze({ [locale]: catalog }) as MessagesByLocale;
        loadedCatalogs.set(locale, messages);
        return messages;
      })
      .catch((error: unknown) => {
        pendingCatalogs.delete(locale);
        throw error;
      });

    pendingCatalogs.set(locale, request);
    return request;
  };

  const getLoaded = (locale: Locale): MessagesByLocale => {
    if (locale === "en-US") return EMPTY_CATALOGS;
    const messages = loadedCatalogs.get(locale);
    if (!messages) throw new Error("Astryx locale catalog must load before the locale is rendered");
    return messages;
  };

  return Object.freeze({ load, getLoaded });
}

const astryxCatalogOwner = createAstryxLocaleCatalogOwner(loaders);

/**
 * Loads Astryx's public ICU catalog before rendering or switching to a locale.
 * Astryx ships English internally, so en-US needs no additional catalog.
 */
export function loadAstryxLocaleCatalog(locale: Locale): Promise<MessagesByLocale> {
  return astryxCatalogOwner.load(locale);
}

/** Returns only a previously loaded catalog; English falls back to Astryx's built-in source. */
export function getLoadedAstryxLocaleCatalog(locale: Locale): MessagesByLocale {
  return astryxCatalogOwner.getLoaded(locale);
}
