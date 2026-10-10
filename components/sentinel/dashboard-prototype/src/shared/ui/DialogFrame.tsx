import dialogFrameStyles from "./DialogFrame.module.scss";
import { scopedClasses } from "./styles/scopedClasses";
import { Dialog, DialogHeader, type DialogPurpose } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { useFocusTrap } from "@astryxdesign/core/hooks";
import type { ReactNode } from "react";

const styleModules = [dialogFrameStyles] as const;

type DialogFrameProps = {
  /** Whether the modal is currently presented. */
  isOpen: boolean;
  /** Receives controlled visibility changes from the Astryx dialog lifecycle. */
  onOpenChange: (isOpen: boolean) => void;
  /** Accessible heading and visible title for the modal. */
  title: string;
  /** Optional supporting copy shown beneath the title. */
  subtitle?: string;
  /** Domain-specific content rendered in the scrollable body slot. */
  children: ReactNode;
  /** Domain-specific actions rendered in the fixed footer slot. */
  actions: ReactNode;
  /** Astryx dismissal policy for the workflow. */
  purpose?: DialogPurpose;
  /** Preferred surface width in CSS pixels or a CSS length. */
  width?: number | string;
  /** Maximum surface height; only the body scrolls when content exceeds this bound. */
  maxHeight?: number | string;
  /** Optional hook for feature-specific styling on the dialog surface. */
  className?: string;
  /** An issued command is unresolved: suppress dismissal until its owner confirms the outcome. */
  isBusy?: boolean;
};

/**
 * Shared modal frame for dashboard workflows.
 *
 * The frame owns the stable modal anatomy—header, body, and action footer—so
 * feature dialogs only provide their fields and commands. Astryx remains the
 * owner of focus, escape handling, backdrop behavior, and scroll locking.
 */
export function DialogFrame({
  isOpen,
  onOpenChange,
  title,
  subtitle,
  children,
  actions,
  purpose = "form",
  width = 620,
  maxHeight = "90dvh",
  className,
  isBusy = false,
}: DialogFrameProps) {
  // Native modality makes the background inert, but Chromium still moves Tab
  // to browser chrome at the boundary. Reuse the vendor's public Tab-cycle hook;
  // omit onEscape so Dialog remains the sole dismissal/return-focus owner.
  const { containerRef } = useFocusTrap<HTMLDialogElement>({ isActive: isOpen });
  const requestOpenChange = (nextOpen: boolean) => {
    if (!nextOpen && isBusy) return;
    onOpenChange(nextOpen);
  };
  return (
    <Dialog
      ref={containerRef}
      isOpen={isOpen}
      onOpenChange={requestOpenChange}
      purpose={isBusy ? "required" : purpose}
      aria-busy={isBusy}
      width={width}
      maxHeight={maxHeight}
      padding={0}
      className={scopedClasses(
        styleModules,
        className ? `dialog-frame ${className}` : "dialog-frame",
      )}
    >
      <Layout
        height="fill"
        header={
          <DialogHeader
            title={title}
            subtitle={subtitle}
            onOpenChange={isBusy ? undefined : requestOpenChange}
            hasDivider
          />
        }
        content={
          <LayoutContent padding={4} isScrollable>
            {children}
          </LayoutContent>
        }
        footer={
          <LayoutFooter hasDivider padding={3}>
            <div className={scopedClasses(styleModules, "dialog-frame-actions")}>{actions}</div>
          </LayoutFooter>
        }
      />
    </Dialog>
  );
}
