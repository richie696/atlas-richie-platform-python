import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { QuerySnapshot } from "../../state/queryResource";
import { QueryView } from "../QueryView";

/** Common read feedback only; this component does not select a source, authorize or perform effects. */
export function ObservationQueryView<Value>({
  snapshot,
  onRetry,
  children,
  descriptions,
}: {
  readonly snapshot: QuerySnapshot<Value>;
  readonly onRetry: () => void;
  readonly children: (value: Value) => ReactNode;
  /** Capability-specific empty/partial semantics; lifecycle and safe error policy remain shared. */
  readonly descriptions?: {
    readonly empty?: string;
    readonly filteredEmpty?: string;
    readonly partial?: string;
    readonly error?: string;
    readonly stale?: string;
  };
}) {
  const { t } = useTranslation();
  const title = t("observation.read.title");
  const targetAbsent =
    snapshot.status === "error" && (snapshot.error.status === 404 || snapshot.error.status === 410);
  return (
    <QueryView
      snapshot={snapshot}
      onRetry={onRetry}
      copy={{
        idle: { title, description: t("observation.read.idle") },
        loading: { title, description: t("observation.read.loading") },
        refreshing: { title, description: t("observation.read.refreshing") },
        empty: { title, description: descriptions?.empty ?? t("observation.read.empty") },
        "filtered-empty": {
          title,
          description: descriptions?.filteredEmpty ?? t("observation.read.filteredEmpty"),
        },
        denied: { title, description: t("observation.read.denied") },
        error: {
          title,
          description: targetAbsent
            ? t("observation.read.targetAbsent")
            : (descriptions?.error ?? t("observation.read.error")),
        },
        stale: { title, description: descriptions?.stale ?? t("observation.read.stale") },
        partial: { title, description: descriptions?.partial ?? t("observation.read.partial") },
      }}
    >
      {children}
    </QueryView>
  );
}
