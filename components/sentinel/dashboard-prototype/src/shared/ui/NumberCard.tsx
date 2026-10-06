import { Card } from "@astryxdesign/core/Card";
import type { ReactNode } from "react";

export type NumberCardProps = { label: ReactNode; value: ReactNode; unit?: ReactNode; note: ReactNode; tone?: string };

/** Displays one operational KPI with an optional semantic note tone. */
export function NumberCard({ label, value, unit = "", note, tone = "" }: NumberCardProps) {
  return (
    <Card padding={0} className="number-card">
      <span>{label}</span><strong>{value}<small>{unit}</small></strong><p className={tone}>{note}</p>
    </Card>
  );
}
