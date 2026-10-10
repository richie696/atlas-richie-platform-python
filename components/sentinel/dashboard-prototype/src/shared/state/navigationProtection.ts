import { StateStore } from "@richie696/react-framework";
export interface NavigationProtection {
  readonly dirty: boolean;
  readonly locked: boolean;
  /** Local abandonment only; must not cancel/replay a dispatched server transaction. */
  readonly discard?: () => void;
}
/** A view-lifetime registration contract. The app owns navigation effects, not this registry. */
export function createNavigationProtectionRegistry() {
  const entries = new Map<symbol, NavigationProtection>();
  const state = new StateStore({ dirty: false, locked: false });
  const publish = () => {
    const values = [...entries.values()],
      next = {
        dirty: values.some((entry) => entry.dirty),
        locked: values.some((entry) => entry.locked),
      };
    const previous = state.getSnapshot();
    if (previous.dirty !== next.dirty || previous.locked !== next.locked) state.set(next);
  };
  return Object.freeze({
    getSnapshot: state.getSnapshot,
    subscribe: state.subscribe,
    register(entry: NavigationProtection) {
      const owner = Symbol("navigation-protection");
      entries.set(owner, entry);
      publish();
      return () => {
        if (entries.delete(owner)) publish();
      };
    },
    discard() {
      if (state.getSnapshot().locked) return "blocked" as const;
      try {
        for (const entry of [...entries.values()]) if (entry.dirty) entry.discard?.();
      } catch {
        return "failed" as const;
      }
      return state.getSnapshot().locked ? ("blocked" as const) : ("done" as const);
    },
  });
}
export type NavigationProtectionRegistry = ReturnType<typeof createNavigationProtectionRegistry>;
