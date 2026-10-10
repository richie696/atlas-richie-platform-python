import { useState } from "react";
import { ChartThemeProvider } from "../../../src/shared/ui/charts/ChartThemeProvider";
import { TrendChart } from "../../../src/shared/ui/charts/TrendChart";
import type { TrendPoint } from "../../../src/shared/ui/charts/trendPlot";

const SAMPLES: Readonly<Record<string, readonly TrendPoint[]>> = {
  gaps: [
    { time: "14:00", qps: 100, blocked: 1 },
    { time: "14:01", qps: 150, blocked: 2 },
    { time: "14:02", qps: null, blocked: null },
    { time: "14:03", qps: 200, blocked: 10 },
    { time: "14:04", qps: 250, blocked: 12 },
  ],
  empty: [],
  constant: [{ time: "14:00", qps: 0 }],
  timestamp: [
    { timestampMs: Date.UTC(2026, 9, 7, 1, 30), qps: 100 },
    { timestampMs: Date.UTC(2026, 9, 7, 7, 30), qps: 150 },
    { timestampMs: Date.UTC(2026, 9, 8, 1, 30), qps: 200 },
  ],
  invalid: [
    { time: "14:00", qps: 1 },
    { time: "14:00", qps: 2 },
  ],
};

/** Exercises the actual renderer with explicit observations; never part of the application mock path. */
export function ChartProbe() {
  const [mode, setMode] = useState("gaps");
  const [revision, setRevision] = useState(0);
  return (
    <section
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 100,
        overflow: "auto",
        background: "var(--sentinel-color-background-base)",
        padding: 12,
      }}
    >
      {Object.keys(SAMPLES).map((value) => (
        <button key={value} data-mode={value} onClick={() => setMode(value)}>
          {value}
        </button>
      ))}
      <button
        data-theme
        onClick={() => {
          document.documentElement.style.setProperty("--chart-series-primary", "#ff00ff");
          document.documentElement.style.setProperty("--chart-axis-text", "#00ffaa");
          setRevision((value) => value + 1);
        }}
      >
        Change installed skin
      </button>
      <ChartThemeProvider revision={revision}>
        <div style={{ maxWidth: 900, margin: "20px auto" }}>
          <TrendChart
            data={SAMPLES[mode]}
            metric="qps"
            second={mode === "gaps" ? "blocked" : undefined}
            secondAxis
            secondUnit="%"
            height={300}
            annotations={[
              { time: "14:02", label: "Deployment-42" },
              { time: "outside", label: "Ignored-outside" },
            ]}
            cursorTime="outside"
          />
        </div>
      </ChartThemeProvider>
    </section>
  );
}
