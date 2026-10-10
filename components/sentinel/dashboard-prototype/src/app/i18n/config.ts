/** Application-wide i18next configuration and on-demand locale registration. */
import i18next from "i18next";
import { initReactI18next } from "react-i18next";
import { loadMessageCatalog } from "./messageCatalogs";
import { FALLBACK_LOCALE, LOCALES, isSupportedLocale, readStoredLocale } from "./locales";

const localeBackend = {
  type: "backend" as const,
  init() {},
  read(
    language: string,
    namespace: string,
    callback: (error: Error | null, data: unknown) => void,
  ) {
    if (namespace !== "translation" || !isSupportedLocale(language)) {
      callback(new Error("Unsupported Sentinel locale resource"), false);
      return;
    }
    void loadMessageCatalog(language).then(
      (catalog) => callback(null, catalog),
      (error: unknown) =>
        callback(
          error instanceof Error ? error : new Error("Locale resource loading failed"),
          false,
        ),
    );
  },
};

/** Initial locale resources are loaded before the app is allowed to render. */
export const i18nReady = i18next
  .use(localeBackend)
  .use(initReactI18next)
  .init({
    lng: readStoredLocale(),
    fallbackLng: FALLBACK_LOCALE,
    supportedLngs: LOCALES,
    ns: ["translation"],
    defaultNS: "translation",
    nsSeparator: false,
    interpolation: { escapeValue: false },
    react: { useSuspense: false },
  });

/** The configured i18next instance used by React and integration tests. */
export default i18next;
