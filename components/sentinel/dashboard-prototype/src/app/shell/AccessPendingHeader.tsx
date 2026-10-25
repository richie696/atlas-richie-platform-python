import styles from "./AppShell.module.scss";

/** Neutral header geometry shown while route access is being revalidated. */
export function AccessPendingHeader() {
  return (
    <header className={`topbar ${styles["topbar"]} ${styles["pending-header"]}`} aria-hidden="true">
      <span className={styles["pending-brand"]} />
      <span className={styles["pending-info"]}>
        <i />
        <i />
        <i />
      </span>
      <span className={styles["pending-navigation"]}>
        <i />
        <i />
        <i />
        <i />
        <i />
        <i />
      </span>
    </header>
  );
}
