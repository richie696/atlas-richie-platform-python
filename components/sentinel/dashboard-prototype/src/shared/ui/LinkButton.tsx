import { ArrowRightIcon as ArrowRight } from "@phosphor-icons/react";
import { Button } from "@astryxdesign/core/Button";
import type { ReactNode } from "react";

export type LinkButtonProps = { children: ReactNode; onClick: () => void };

/** A compact navigational action for cards and table rows. */
export function LinkButton({ children, onClick }: LinkButtonProps) {
  const label = typeof children === "string" ? children : "Open";
  return (
    <Button
      type="button"
      className="link-button"
      label={label}
      variant="ghost"
      size="sm"
      onClick={onClick}
      endContent={<ArrowRight size={15} />}
    >
      {children}
    </Button>
  );
}
