import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { QuerySnapshot } from "../../../shared/state/queryResource";
import type { FeedbackCopy } from "../../../shared/ui/FeedbackPanel";
import { QueryView } from "../../../shared/ui/QueryView";
/** Rule reads share lifecycle anatomy, not metric-specific empty or partial wording. */
export function RuleQueryView<Value>({
  snapshot,
  onRetry,
  children,
  partialCopy,
}: {
  readonly snapshot: QuerySnapshot<Value>;
  readonly onRetry: () => void;
  readonly children: (value: Value) => ReactNode;
  readonly partialCopy?: FeedbackCopy;
}) {
  const { t } = useTranslation();
  const title = t("rules.workspace.readTitle");
  return (
    <QueryView
      snapshot={snapshot}
      onRetry={onRetry}
      copy={{
        idle: { title, description: t("rules.workspace.readIdle") },
        loading: { title, description: t("rules.workspace.readLoading") },
        refreshing: { title, description: t("rules.workspace.readRefreshing") },
        empty: { title, description: t("rules.workspace.readEmpty") },
        "filtered-empty": { title, description: t("rules.workspace.readFilteredEmpty") },
        denied: { title, description: t("rules.workspace.denied") },
        error: { title, description: t("rules.workspace.readFailed") },
        stale: { title, description: t("rules.workspace.readStale") },
        partial: partialCopy ?? { title, description: t("rules.workspace.readPartial") },
      }}
    >
      {children}
    </QueryView>
  );
}
