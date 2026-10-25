import { AppError, AppErrorKind, StateStore } from "@richie696/react-framework";
import {
  createQueryResource,
  type QueryResource,
  type QueryResourceOptions,
  type QuerySnapshot,
} from "./queryResource";

/** App projects its sole session owner into this capability. No token, role policy or second session store. */
export interface QueryAccess {
  readonly ownerKey: string;
  readonly allowed: boolean;
}
export interface QueryAccessObserver {
  readonly read: () => QueryAccess;
  readonly subscribe: (listener: () => void) => () => void;
}

/**
 * Compose a single feature query with session ownership. The first notification
 * after revocation hides data; reset aborts old work and late results cannot repopulate.
 * Privilege decisions belong to the app's session projection and the backend.
 */
export function createOwnedQueryResource<Query, Value>(
  access: QueryAccessObserver,
  options: QueryResourceOptions<Query, Value>,
): QueryResource<Query, Value> {
  let ownerKey = access.read().ownerKey,
    disposed = false;
  const permitted = () => !disposed && access.read().allowed && access.read().ownerKey === ownerKey;
  const denied: QuerySnapshot<Value> = Object.freeze({
    status: "denied",
    key: "",
    error: new AppError(AppErrorKind.FORBIDDEN, "Observation access unavailable", { status: 403 }),
  });
  const resource = createQueryResource<Query, Value>({
    ...options,
    keyOf: (query) => JSON.stringify([ownerKey, options.keyOf(query)]),
    read: async (query, signal) => {
      if (!permitted()) throw denied.error;
      const data = await options.read(query, signal);
      if (!permitted() || signal.aborted)
        throw new AppError(AppErrorKind.CANCELLED, "Observation owner changed");
      return data;
    },
  });
  const state = new StateStore<QuerySnapshot<Value>>(permitted() ? resource.getSnapshot() : denied);
  const publish = () => state.set(permitted() ? resource.getSnapshot() : denied);
  const unsubscribeQuery = resource.subscribe(publish);
  const unsubscribeAccess = access.subscribe(() => {
    const next = access.read();
    if (next.ownerKey !== ownerKey || !next.allowed) {
      // Clear before adopting a new owner, including already-completed data.
      resource.reset();
      ownerKey = next.ownerKey;
    }
    publish();
  });
  return Object.freeze({
    keyOf: resource.keyOf,
    getSnapshot: state.getSnapshot,
    subscribe: state.subscribe,
    async load(query: Query) {
      if (disposed) throw new AppError(AppErrorKind.CANCELLED, "Observation owner disposed");
      if (!permitted()) throw denied.error;
      return resource.load(query);
    },
    cancel: resource.cancel,
    reset: resource.reset,
    dispose() {
      if (disposed) return;
      disposed = true;
      unsubscribeAccess();
      unsubscribeQuery();
      resource.dispose();
      state.set({ status: "idle" });
      state.complete();
    },
  });
}
