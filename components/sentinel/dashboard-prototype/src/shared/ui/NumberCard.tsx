import presentationStyles from "./styles/Presentation.module.scss";
import numberCardStyles from "./NumberCard.module.scss";
import { scopedClasses } from "./styles/scopedClasses";
import { Card } from "@astryxdesign/core/Card";
import type { ReactNode } from "react";

const styleModules = [presentationStyles, numberCardStyles] as const;

export type NumberCardProps = {
  label: ReactNode;
  value: ReactNode;
  unit?: ReactNode;
  note: ReactNode;
  tone?: string;
};

/** Displays one operational KPI with an optional semantic note tone. */
export function NumberCard({ label, value, unit = "", note, tone = "" }: NumberCardProps) {
  return (
    <Card padding={0} className={scopedClasses(styleModules, "number-card")}>
      <span>{label}</span>
      <strong>
        {value}
        <small>{unit}</small>
      </strong>
      <p className={scopedClasses(styleModules, tone)}>{note}</p>
    </Card>
  );
}
