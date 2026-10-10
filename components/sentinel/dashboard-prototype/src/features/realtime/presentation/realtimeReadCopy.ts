import { AppErrorKind } from "@richie696/react-framework";
import type { QuerySnapshot } from "../../../shared/state/queryResource";
import type { MetricBundle } from "../../../shared/model/observation";

/** Locale keys for realtime network failures; raw transport messages never reach the UI. */
export function realtimeReadCopy(snapshot: QuerySnapshot<MetricBundle>) {
  if (snapshot.status === "error" && snapshot.error.kind === AppErrorKind.NETWORK)
    return { error: "observation.read.errorNetwork" as const };
  if (snapshot.status === "stale" && snapshot.error.kind === AppErrorKind.NETWORK)
    return { stale: "observation.read.staleNetwork" as const };
  return undefined;
}
