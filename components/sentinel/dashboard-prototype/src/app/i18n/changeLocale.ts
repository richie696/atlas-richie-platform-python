import i18next from "i18next";
import type { Locale } from "./locales";
import { i18nReady } from "./config";
import { loadAstryxLocaleCatalog } from "./astryxLocaleCatalogs";
import { createLatestLocaleSwitcher } from "./localeSwitcher";

const switchLocale = createLatestLocaleSwitcher<Locale>({
  prepare: async (locale) => {
    await i18nReady;
    await loadAstryxLocaleCatalog(locale);
  },
  apply: (locale) => i18next.changeLanguage(locale),
});

/** Load both UI libraries' catalogs before changing the active locale. */
export async function changeLocale(
  locale: Locale,
  persist?: (locale: Locale) => void,
): Promise<boolean> {
  return switchLocale(locale, persist);
}
