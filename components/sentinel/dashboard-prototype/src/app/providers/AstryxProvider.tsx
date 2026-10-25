import { InternationalizationProvider } from "@astryxdesign/core/i18n";
import type { ReactNode } from "react";
import { useLocale } from "../i18n/locales";
import { getLoadedAstryxLocaleCatalog } from "../i18n/astryxLocaleCatalogs";
import { ChartThemeProvider } from "../../shared/ui/charts/ChartThemeProvider";

import "@astryxdesign/core/reset.css";
import "@astryxdesign/core/astryx.css";
import "@astryxdesign/theme-neutral/theme.css";

type AstryxProviderProps = {
  children: ReactNode;
};

/**
 * Owns the once-per-application Astryx locale boundary.
 *
 * The prebuilt neutral theme stylesheet and root data attributes are applied
 * statically. Astryx's runtime Theme provider also bundles its theme compiler,
 * which is unnecessary for this application because it does not create or
 * switch runtime themes. Sentinel's SCSS remains responsible for product
 * colors, density and operational dashboard surfaces.
 */
export function AstryxProvider({ children }: AstryxProviderProps) {
  const locale = useLocale();
  const messages = getLoadedAstryxLocaleCatalog(locale);
  return (
    <InternationalizationProvider locale={locale} messages={messages}>
      <ChartThemeProvider revision="sentinel-dark">{children}</ChartThemeProvider>
    </InternationalizationProvider>
  );
}
