import { Dialog, DialogHeader, type DialogPurpose } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import type { ReactNode } from "react";

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
  /** Maximum body height before the content slot scrolls. */
  maxHeight?: number | string;
  /** Optional hook for feature-specific styling on the dialog surface. */
  className?: string;
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
}: DialogFrameProps) {
  return (
    <Dialog
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      purpose={purpose}
      width={width}
      maxHeight={maxHeight}
      padding={0}
      className={className ? `dialog-frame ${className}` : "dialog-frame"}
    >
      <Layout
        height="auto"
        header={
          <DialogHeader
            title={title}
            subtitle={subtitle}
            onOpenChange={onOpenChange}
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
            <div className="dialog-frame-actions">{actions}</div>
          </LayoutFooter>
        }
      />
    </Dialog>
  );
}
