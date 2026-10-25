import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { BannerStatus } from "@astryxdesign/core/Banner";
import { QUERY_STATUS, type QuerySnapshot } from "../state/queryResource";
import { useRetryCooldown } from "../state/useRetryCooldown";
import { ActionButton } from "./ActionButton";
import { FeedbackPanel, type FeedbackCopy } from "./FeedbackPanel";

type FeedbackQueryStatus = Exclude<QuerySnapshot<never>["status"], "ready">;
const TONE: Readonly<Record<FeedbackQueryStatus, BannerStatus>> = Object.freeze({
  idle: "info",
  loading: "info",
  refreshing: "info",
  empty: "info",
  "filtered-empty": "info",
  denied: "warning",
  error: "error",
  stale: "warning",
  partial: "warning",
});

/** Distinguish resource states without leaking errors or rendering denied/previous-key data. Retry is read-only. */
export function QueryView<Value>({
  snapshot,
  copy,
  children,
  unavailableContent,
  onRetry,
  showStatusFeedback = true,
  showPartialFeedback = true,
}: {
  readonly snapshot: QuerySnapshot<Value>;
  readonly copy: Readonly<Record<FeedbackQueryStatus, FeedbackCopy>>;
  readonly children: (value: Value) => ReactNode;
  /** Capability-owned layout to keep visible when no trusted query value is available. */
  readonly unavailableContent?: ReactNode;
  readonly onRetry?: () => void;
  /** Lets a page consolidate simultaneous related failures into one owned status notice. */
  readonly showStatusFeedback?: boolean;
  /** Some dashboards present partial quality beside every metric and need only one page-level notice. */
  readonly showPartialFeedback?: boolean;
}) {
  const { t } = useTranslation();
  const retryable =
    snapshot.status === QUERY_STATUS.Error || snapshot.status === QUERY_STATUS.Stale;
  const retryError = retryable ? snapshot.error : undefined;
  const retryCooldownActive = useRetryCooldown(retryError);
  const retained =
    snapshot.status === QUERY_STATUS.Ready ||
    snapshot.status === QUERY_STATUS.Refreshing ||
    snapshot.status === QUERY_STATUS.Stale ||
    snapshot.status === QUERY_STATUS.Partial;
  return (
    <section data-query-state={snapshot.status}>
      {showStatusFeedback &&
        snapshot.status !== QUERY_STATUS.Ready &&
        (snapshot.status !== QUERY_STATUS.Partial || showPartialFeedback) && (
          <FeedbackPanel
            copy={copy[snapshot.status]}
            tone={TONE[snapshot.status]}
            isBusy={
              snapshot.status === QUERY_STATUS.Loading ||
              snapshot.status === QUERY_STATUS.Refreshing
            }
            actions={
              retryable && onRetry ? (
                <ActionButton
                  disabled={retryCooldownActive}
                  onClick={() => {
                    if (!retryCooldownActive) onRetry();
                  }}
                >
                  {t("shell.feedback.retryRead")}
                </ActionButton>
              ) : undefined
            }
          />
        )}
      {/* Stable child position preserves local edit buffers during same-key refresh.
          Changing ready -> refreshing must not unmount the consumer and erase edits. */}
      <div>{retained && "data" in snapshot ? children(snapshot.data) : unavailableContent}</div>
    </section>
  );
}
