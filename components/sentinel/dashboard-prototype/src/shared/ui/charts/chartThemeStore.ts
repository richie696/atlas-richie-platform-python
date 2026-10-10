import { FALLBACK_CHART_TOKENS, readChartTokens, type ChartTokens } from "./chartTheme";

/** A per-provider skin snapshot; refresh belongs to the skin lifecycle, not each chart/frame. */
export function createChartThemeStore(read: () => ChartTokens = readChartTokens) {
  let snapshot = FALLBACK_CHART_TOKENS;
  const listeners = new Set<() => void>();
  return Object.freeze({
    getSnapshot: () => snapshot,
    getServerSnapshot: () => FALLBACK_CHART_TOKENS,
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    refresh() {
      const candidate = read();
      const same = (Object.keys(candidate) as (keyof ChartTokens)[]).every((key) =>
        key === "series"
          ? (Object.keys(candidate.series) as (keyof ChartTokens["series"])[]).every(
              (color) => candidate.series[color] === snapshot.series[color],
            )
          : candidate[key] === snapshot[key],
      );
      if (same) return;
      snapshot = candidate;
      for (const listener of listeners) listener();
    },
  });
}
