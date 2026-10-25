import { useTranslation } from "react-i18next";
import type { BannerStatus } from "@astryxdesign/core/Banner";
import { COMMAND_STATUS, type CommandSnapshot } from "../state/commandResource";
import { ActionButton } from "./ActionButton";
import { FeedbackPanel, type FeedbackCopy } from "./FeedbackPanel";

type FeedbackCommandStatus = Exclude<CommandSnapshot<never>["status"], "idle">;
const TONE: Readonly<Record<FeedbackCommandStatus, BannerStatus>> = Object.freeze({
  pending: "info",
  success: "success",
  error: "error",
  conflict: "warning",
  "result-unknown": "warning",
});

/** Command outcomes are not query errors. Unknown/conflict expose investigation/read actions, never replay. */
export function CommandFeedback<Result>({
  snapshot,
  copy,
  onInspectOutcome,
  inspectDisabled = false,
  onReadLatest,
}: {
  readonly snapshot: CommandSnapshot<Result>;
  readonly copy: Readonly<Record<FeedbackCommandStatus, FeedbackCopy>>;
  readonly onInspectOutcome?: () => void;
  readonly inspectDisabled?: boolean;
  readonly onReadLatest?: () => void;
}) {
  const { t } = useTranslation();
  if (snapshot.status === COMMAND_STATUS.Idle) return null;
  return (
    <section data-command-state={snapshot.status}>
      <FeedbackPanel
        copy={copy[snapshot.status]}
        tone={TONE[snapshot.status]}
        isBusy={snapshot.status === COMMAND_STATUS.Pending}
        actions={
          snapshot.status === COMMAND_STATUS.Unknown && onInspectOutcome ? (
            <ActionButton disabled={inspectDisabled} onClick={onInspectOutcome}>
              {t("shell.feedback.inspectOutcome")}
            </ActionButton>
          ) : snapshot.status === COMMAND_STATUS.Conflict && onReadLatest ? (
            <ActionButton onClick={onReadLatest}>{t("shell.feedback.readLatest")}</ActionButton>
          ) : undefined
        }
      />
    </section>
  );
}
