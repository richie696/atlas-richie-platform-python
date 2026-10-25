import { useEffect, useMemo } from "react";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import { QUERY_STATUS, type QueryResource, type QuerySnapshot } from "./queryResource";

/**
 * React subscription only. Resource and semantic query must be memoized by the
 * owning feature. Rejections are represented by the owner's snapshot; unmount
 * cancels work but does not destroy an owner reused by StrictMode.
 */
export function useQueryResource<Query, Value>(
  resource: QueryResource<Query, Value>,
  query: Query,
): QuerySnapshot<Value> {
  const key = resource.keyOf(query);
  const pending = useMemo(() => Object.freeze({ status: QUERY_STATUS.Loading, key }), [key]);
  useEffect(() => {
    void resource.load(query).catch(() => {
      /* error is already represented in the resource snapshot */
    });
    return () => resource.cancel();
  }, [resource, query]);
  const snapshot = useExternalSnapshot(resource);
  // Effects run after commit. A new query must not render the old session/app's
  // value for even one frame while waiting for load() to invalidate ownership.
  // An owned resource uses a key-less denial when the whole identity/capability
  // is revoked. Don't mask it as loading merely because no query can be issued.
  const ownerDenied = snapshot.status === QUERY_STATUS.Denied && snapshot.key === "";
  return "key" in snapshot && snapshot.key !== key && !ownerDenied ? pending : snapshot;
}
