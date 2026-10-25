import panelStyles from "./Panel.module.scss";
import { scopedClasses } from "./styles/scopedClasses";
import { Card } from "@astryxdesign/core/Card";
import type { ReactNode } from "react";

const styleModules = [panelStyles] as const;

export type PanelProps = {
  title: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
};

/** Shared surface anatomy; the feature owns the panel's business content. */
export function Panel({ title, subtitle, action = null, children, className = "" }: PanelProps) {
  return (
    <Card padding={0} className={scopedClasses(styleModules, `panel ${className}`)}>
      <div className={scopedClasses(styleModules, "panel-head")}>
        <div>
          <h2>{title}</h2>
          {subtitle && <p>{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </Card>
  );
}
