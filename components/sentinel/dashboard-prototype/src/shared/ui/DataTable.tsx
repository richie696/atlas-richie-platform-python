import dataTableStyles from "./DataTable.module.scss";
import { scopedClasses } from "./styles/scopedClasses";
import { useMemo, type ReactNode } from "react";
import { Table } from "@astryxdesign/core/Table";

const styleModules = [dataTableStyles] as const;

/** Semantic table wrapper used by feature pages for consistent overflow behavior. */
export function DataTable({
  heads,
  rows,
  className = "",
}: {
  heads: readonly string[];
  rows: ReactNode;
  className?: string;
}) {
  const scrollLabel = heads.join(" / ");
  // Table already owns the focusable native scroll region. Use its public
  // plugin slot, rather than adding a second focus stop on a non-scrolling div.
  const plugins = useMemo(
    () => ({
      accessibility: {
        transformScrollWrapper: (
          props: import("@astryxdesign/core/Table").ScrollWrapperRenderProps,
        ) => ({
          ...props,
          htmlProps: {
            ...props.htmlProps,
            "aria-label": scrollLabel,
            "data-console-table-scroll": true,
          },
        }),
      },
    }),
    [scrollLabel],
  );
  return (
    <div className={scopedClasses(styleModules, "table-scroll")}>
      <Table<Record<string, unknown>>
        className={scopedClasses(styleModules, `data-table ${className}`)}
        density="balanced"
        dividers="rows"
        textOverflow="wrap"
        plugins={plugins}
      >
        <thead>
          <tr>
            {heads.map((head) => (
              <th key={head} scope="col">
                {head}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </Table>
    </div>
  );
}
