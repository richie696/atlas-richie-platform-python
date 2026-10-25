import { useQueryResource } from "../../../src/shared/state/useQueryResource";
import { useLayoutEffect } from "react";
import type { QueryResource, QuerySnapshot } from "../../../src/shared/state/queryResource";
export { createQueryResource } from "../../../src/shared/state/queryResource";

export interface ProbeQuery {
  readonly session: string;
  readonly application: string;
}

/** Exercises the actual lifecycle Hook, not a copied React state implementation. */
export function QueryLifecycleProbe({
  resource,
  query,
  onCommit,
}: {
  readonly resource: QueryResource<ProbeQuery, readonly string[]>;
  readonly query: ProbeQuery;
  readonly onCommit?: (query: ProbeQuery, snapshot: QuerySnapshot<readonly string[]>) => void;
}) {
  const snapshot = useQueryResource(resource, query);
  // Observe committed UI before passive effects invalidate an old query.
  useLayoutEffect(() => {
    onCommit?.(query, snapshot);
  }, [onCommit, query, snapshot]);
  return (
    <output>
      {JSON.stringify({ status: snapshot.status, data: "data" in snapshot ? snapshot.data : null })}
    </output>
  );
}
