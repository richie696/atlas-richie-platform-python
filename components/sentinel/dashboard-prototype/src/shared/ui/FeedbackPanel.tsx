import { Banner, type BannerStatus } from "@astryxdesign/core/Banner";
import type { ReactNode } from "react";
import { scopedClasses } from "./styles/scopedClasses";
import styles from "./FeedbackPanel.module.scss";

const styleModules = [styles] as const;
export interface FeedbackCopy {
  readonly title: string;
  /** Meaning and recovery instructions supplied by the owning capability; never raw exception text. */
  readonly description: string;
}

/** Shared status anatomy. Astryx owns announcement semantics; feature workflows own wording and actions. */
export function FeedbackPanel({
  copy,
  tone = "info",
  actions,
  isBusy = false,
}: {
  readonly copy: FeedbackCopy;
  readonly tone?: BannerStatus;
  readonly actions?: ReactNode;
  readonly isBusy?: boolean;
}) {
  return (
    <div className={scopedClasses(styleModules, "feedback")} aria-busy={isBusy}>
      <Banner
        status={tone}
        title={<h2 className={scopedClasses(styleModules, "title")}>{copy.title}</h2>}
        description={copy.description}
        endContent={
          actions ? (
            <div className={scopedClasses(styleModules, "actions")}>{actions}</div>
          ) : undefined
        }
      />
    </div>
  );
}
