import { Theme } from "@astryxdesign/core/theme";
import { neutralTheme } from "@astryxdesign/theme-neutral/built";
import type { ReactNode } from "react";

import "@astryxdesign/core/reset.css";
import "@astryxdesign/core/astryx.css";
import "@astryxdesign/theme-neutral/theme.css";

type AstryxProviderProps = {
  children: ReactNode;
};

/**
 * Owns the once-per-application Astryx theme boundary.
 *
 * Astryx supplies accessible primitive behavior and its neutral token base;
 * Sentinel's own SCSS remains responsible for product colors, density and
 * operational dashboard surfaces.
 */
export function AstryxProvider({ children }: AstryxProviderProps) {
  return <Theme theme={neutralTheme} mode="dark">{children}</Theme>;
}
