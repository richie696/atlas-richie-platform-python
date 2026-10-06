import type { ReactNode } from "react";
import { Table } from "@astryxdesign/core/Table";

/** Semantic table wrapper used by feature pages for consistent overflow behavior. */
export function DataTable({ heads, rows, className = "" }: { heads: string[]; rows: ReactNode; className?: string }) {
  return <div className="table-scroll"><Table<Record<string, unknown>> className={`data-table ${className}`} density="balanced" dividers="rows" textOverflow="wrap"><thead><tr>{heads.map((head) => <th key={head}>{head}</th>)}</tr></thead><tbody>{rows}</tbody></Table></div>;
}
