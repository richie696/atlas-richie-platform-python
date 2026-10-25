import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { QuerySnapshot } from "../../../shared/state/queryResource";
import { QueryView } from "../../../shared/ui/QueryView";
/** System feedback has no metric-zero or rule-publication semantics. Reuses the sole read lifecycle shell. */
export function SystemQueryView<Value>({
  snapshot,
  onRetry,
  title: titleOverride,
  emptyDescription,
  filteredEmptyDescription,
  children,
}: {
  readonly snapshot: QuerySnapshot<Value>;
  readonly onRetry: () => void;
  readonly title?: string;
  readonly emptyDescription?: string;
  readonly filteredEmptyDescription?: string;
  readonly children: (value: Value) => ReactNode;
}) {
  const { t } = useTranslation();
  const title = titleOverride ?? t("system.observed.readTitle");
  return (
    <QueryView
      snapshot={snapshot}
      onRetry={onRetry}
      copy={{
        idle: { title, description: t("system.observed.readIdle") },
        loading: { title, description: t("system.observed.readLoading") },
        refreshing: { title, description: t("system.observed.readRefreshing") },
        empty: {
          title,
          description: emptyDescription ?? t("system.observed.readEmpty"),
        },
        "filtered-empty": {
          title,
          description: filteredEmptyDescription ?? t("system.observed.readFilteredEmpty"),
        },
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
