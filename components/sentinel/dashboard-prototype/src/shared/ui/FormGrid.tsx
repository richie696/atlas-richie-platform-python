import type { ReactNode } from "react";
import styles from "./FormGrid.module.scss";

/**
 * Align visible Astryx fields by label/help, control and detached-status rows.
 * Pass fields directly (fragments are allowed), not arbitrary nested layouts or hidden labels.
 * Container width governs reflow; this component owns no values or validation.
 */
export function FormGrid({
  children,
  columns = 2,
  className,
}: {
  readonly children: ReactNode;
  readonly columns?: 1 | 2 | 3;
  readonly className?: string;
}) {
  return (
    <div className={[styles.container, className].filter(Boolean).join(" ")}>
      <div className={`sentinel-form-fields ${styles.fields}`} data-columns={columns}>
        {children}
      </div>
    </div>
  );
}

/** A full-row slot for one visible field; surrounding notices belong outside FormGrid. */
export function FormGridFullRow({ children }: { readonly children: ReactNode }) {
  return <div className={`sentinel-form-slot ${styles.fullRow}`}>{children}</div>;
}
