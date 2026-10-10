import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { QuerySnapshot } from "../../../../shared/state/queryResource";
import { QueryView } from "../../../../shared/ui/QueryView";

/** Common read-state anatomy; directory/detail retain their own resource key and data. */
export function AccountQueryView<Value>({
  snapshot,
  onRetry,
  children,
}: {
  readonly snapshot: QuerySnapshot<Value>;
  readonly onRetry: () => void;
  readonly children: (value: Value) => ReactNode;
}) {
  const { t } = useTranslation();
  const title = t("management.title");
  return (
    <QueryView
      snapshot={snapshot}
      onRetry={onRetry}
      copy={{
        idle: { title, description: t("management.read.idle") },
        loading: { title, description: t("management.read.loading") },
        refreshing: { title, description: t("management.read.refreshing") },
        empty: { title, description: t("management.read.empty") },
        "filtered-empty": { title, description: t("management.read.filteredEmpty") },
        denied: { title, description: t("management.denied") },
        error: { title, description: t("management.read.failed") },
        stale: { title, description: t("management.read.stale") },
        partial: { title, description: t("management.read.partial") },
      }}
    >
      {children}
    </QueryView>
  );
}
