import statusStyles from "./Status.module.scss";
import { scopedClasses } from "./styles/scopedClasses";
import { Badge, type BadgeVariant } from "@astryxdesign/core/Badge";
import type { ReactNode } from "react";

const styleModules = [statusStyles] as const;

export type StatusProps = { tone?: string; children: ReactNode };

const STATUS_VARIANTS: Readonly<Record<string, BadgeVariant>> = Object.freeze({
  healthy: "success",
  critical: "error",
  warning: "warning",
  blue: "info",
  purple: "purple",
  info: "neutral",
});

/** Renders a semantic status chip using the Dashboard skin tokens. */
export function Status({ tone = "healthy", children }: StatusProps) {
  const variant = STATUS_VARIANTS[tone] ?? "neutral";
  return (
    <Badge
      className={scopedClasses(styleModules, `status status-${tone}`)}
      variant={variant}
      label={children}
    />
  );
}
