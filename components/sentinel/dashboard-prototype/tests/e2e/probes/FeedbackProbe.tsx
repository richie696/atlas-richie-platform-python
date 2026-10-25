import { useState } from "react";
import { AppError, AppErrorKind } from "@richie696/react-framework";
import { AstryxProvider } from "../../../src/app/providers/AstryxProvider";
import { QUERY_STATUS, type QuerySnapshot } from "../../../src/shared/state/queryResource";
import { COMMAND_STATUS, type CommandSnapshot } from "../../../src/shared/state/commandResource";
import { QueryView } from "../../../src/shared/ui/QueryView";
import { CommandFeedback } from "../../../src/shared/ui/CommandFeedback";
import type { FeedbackCopy } from "../../../src/shared/ui/FeedbackPanel";

const error = new AppError(AppErrorKind.SERVER, "SENSITIVE-RAW-ERROR-MUST-NOT-RENDER", {
  status: 500,
});
const rateLimitedError = new AppError(AppErrorKind.RATE_LIMITED, "SENSITIVE-RATE-LIMIT-DETAIL", {
  status: 429,
  retryAfterMs: 500,
});
const value = { key: "one-resource", data: "trusted observations", receivedAt: 1 };
const queries: Readonly<Record<QuerySnapshot<string>["status"], QuerySnapshot<string>>> = {
  idle: { status: "idle" },
  loading: { status: "loading", key: value.key },
  refreshing: { ...value, status: "refreshing" },
  ready: { ...value, status: "ready" },
  empty: { ...value, status: "empty" },
  "filtered-empty": { ...value, status: "filtered-empty" },
  partial: { ...value, status: "partial" },
  stale: { ...value, status: "stale", error },
  error: { status: "error", key: value.key, error },
  denied: { status: "denied", key: value.key, error },
};
const commands: Readonly<Record<CommandSnapshot<string>["status"], CommandSnapshot<string>>> = {
  idle: { status: "idle" },
  pending: { status: "pending" },
  success: { status: "success", result: "confirmed" },
  error: { status: "error", error },
  conflict: { status: "conflict", error },
  "result-unknown": { status: "result-unknown", error },
};
function copy(status: string): FeedbackCopy {
  return {
    title: `${status} — Rule observations`,
    description:
      "観測対象の状態と復旧方法を説明します。空の検索結果はデータの不存在ではなく、権限不足のデータも表示しません。結果が不明な操作を自動的に再実行することはありません。",
  };
}
const queryCopy = Object.fromEntries(
  Object.keys(queries).map((status) => [status, copy(status)]),
) as Readonly<Record<Exclude<QuerySnapshot<string>["status"], "ready">, FeedbackCopy>>;
const commandCopy = Object.fromEntries(
  Object.keys(commands).map((status) => [status, copy(status)]),
) as Readonly<Record<Exclude<CommandSnapshot<string>["status"], "idle">, FeedbackCopy>>;

/** Local snapshot fixture for the real feedback components, not an application mock mode or transport. */
export function FeedbackProbe() {
  const [query, setQuery] = useState<QuerySnapshot<string>["status"]>(QUERY_STATUS.Ready);
  const [rateLimited, setRateLimited] = useState(false);
  const [command, setCommand] = useState<CommandSnapshot<string>["status"]>(COMMAND_STATUS.Idle);
  const [reads, setReads] = useState(0);
  const [inspections, setInspections] = useState(0);
  return (
    <AstryxProvider>
      <section
        style={{
          position: "fixed",
          inset: 0,
          zIndex: 100,
          overflow: "auto",
          padding: 12,
          background: "var(--sentinel-color-background-base)",
        }}
      >
        <div>
          {Object.keys(queries).map((status) => (
            <button
              data-query={status}
              key={status}
              onClick={() => {
                setRateLimited(false);
                setQuery(status as typeof query);
              }}
            >
              {status}
            </button>
          ))}
          <button data-query-rate-limited onClick={() => setRateLimited(true)}>
            rate-limited
          </button>
        </div>
        <div>
          {Object.keys(commands).map((status) => (
            <button
              data-command={status}
              key={status}
              onClick={() => setCommand(status as typeof command)}
            >
              {status}
            </button>
          ))}
        </div>
        <output>{JSON.stringify({ reads, inspections })}</output>
        <div data-query-probe>
          <QueryView
            snapshot={
              rateLimited
                ? { status: QUERY_STATUS.Error, key: value.key, error: rateLimitedError }
                : queries[query]
            }
            copy={queryCopy}
            onRetry={() => setReads((count) => count + 1)}
          >
            {(data) => <p data-trusted>{data}</p>}
          </QueryView>
        </div>
        <div data-command-probe>
          <CommandFeedback
            snapshot={commands[command]}
            copy={commandCopy}
            onInspectOutcome={() => setInspections((count) => count + 1)}
            onReadLatest={() => setReads((count) => count + 1)}
          />
        </div>
      </section>
    </AstryxProvider>
  );
}
