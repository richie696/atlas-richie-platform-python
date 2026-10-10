import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { QuerySnapshot } from "../../../shared/state/queryResource";
import { QueryView } from "../../../shared/ui/QueryView";
/** System feedback has no metric-zero or rule-publication semantics. Reuses the sole read lifecycle shell. */
export function SystemQueryView<Value>({
  snapshot,
  onRetry,
  children,
}: {
  readonly snapshot: QuerySnapshot<Value>;
  readonly onRetry: () => void;
  readonly children: (value: Value) => ReactNode;
}) {
  const { t } = useTranslation();
  const title = t("system.observed.readTitle");
  return (
    <QueryView
      snapshot={snapshot}
      onRetry={onRetry}
      copy={{
        idle: { title, description: t("system.observed.readIdle") },
        loading: { title, description: t("system.observed.readLoading") },
        refreshing: { title, description: t("system.observed.readRefreshing") },
        empty: { title, description: t("system.observed.readEmpty") },
        "filtered-empty": { title, description: t("system.observed.readFilteredEmpty") },
        denied: { title, description: t("system.observed.readDenied") },
        error: { title, description: t("system.observed.readFailed") },
        stale: { title, description: t("system.observed.readStale") },
        partial: { title, description: t("system.observed.readPartial") },
      }}
    >
      {children}
    </QueryView>
  );
}
