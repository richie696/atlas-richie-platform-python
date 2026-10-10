import type { ReactNode } from "react";
import { setupClass } from "./setupStyle";

/** Shared step anatomy only; the owning step supplies translated content and icon. */
export function SetupStepHeading({
  icon,
  title,
  description,
}: {
  readonly icon: ReactNode;
  readonly title: string;
  readonly description: string;
}) {
  return (
    <div className={setupClass("setup-title")}>
      {icon}
      <div>
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
    </div>
  );
}
