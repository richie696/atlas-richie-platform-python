import type { ReactNode } from "react";
import type { QuerySnapshot } from "../../state/queryResource";
import { Panel } from "../Panel";
import { ObservationQueryView } from "./ObservationQueryView";
import styles from "./ObservationContextFallback.module.scss";

/** Keep a route's information hierarchy visible while its observation context is unavailable. */
export function ObservationContextFallback<Value>({
  snapshot,
  onRetry,
  header,
  emptyTitle,
  emptyDescription,
  readErrorDescription,
  readTitle,
  children,
}: {
  readonly snapshot: QuerySnapshot<Value>;
  readonly onRetry: () => void;
  readonly header: ReactNode;
  readonly emptyTitle: string;
  readonly emptyDescription: string;
  readonly readErrorDescription: string;
  readonly readTitle?: string;
  readonly children: (value: Value) => ReactNode;
}) {
  return (
    <>
      {header}
      <ObservationQueryView
        snapshot={snapshot}
        onRetry={onRetry}
        descriptions={{ error: readErrorDescription }}
        title={readTitle}
      >
        {children}
      </ObservationQueryView>
      <Panel title={emptyTitle}>
        <p className={styles.empty} role="status">
          {emptyDescription}
        </p>
      </Panel>
    </>
  );
}
