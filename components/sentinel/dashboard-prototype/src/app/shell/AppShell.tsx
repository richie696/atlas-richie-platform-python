import type { ReactNode } from "react";

export type AppShellProps = {
  header: ReactNode;
  banner?: ReactNode;
  children: ReactNode;
  contentClassName?: string;
  footer?: ReactNode;
};

/**
 * Stable shell anatomy for Dashboard pages. Feature pages own their content;
 * this component owns only the application chrome and landmark structure.
 */
export function AppShell({ header, banner, children, contentClassName = "", footer }: AppShellProps) {
  return (
    <div className="app-shell">
      {header}
      {banner}
      <main className={`content ${contentClassName}`}>{children}</main>
      {footer}
    </div>
  );
}
