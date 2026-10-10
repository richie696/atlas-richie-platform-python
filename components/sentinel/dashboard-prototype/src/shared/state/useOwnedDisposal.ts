import { useEffect, useRef } from "react";

/** A long-lived owner that releases subscriptions and pending work. */
export interface DisposableOwner {
  readonly dispose: () => void;
}

interface OwnerLease {
  readonly owner: DisposableOwner;
  readonly token: symbol;
}

/**
 * Dispose a component-owned workflow when it is truly replaced or unmounted.
 * React StrictMode replays Effect cleanup/setup in development; deferring final
 * disposal by one microtask lets the replayed setup retain the same owner while
 * still releasing it after a real unmount. A different owner is released as
 * soon as its replacement Effect is committed.
 */
export function useOwnedDisposal(owner: DisposableOwner | null): void {
  const current = useRef<OwnerLease | null>(null);

  useEffect(() => {
    if (!owner) return;

    const previous = current.current;
    if (previous && previous.owner !== owner) previous.owner.dispose();

    const lease = Object.freeze({ owner, token: Symbol("owner-lease") });
    current.current = lease;

    return () => {
      queueMicrotask(() => {
        if (current.current?.token !== lease.token) return;
        current.current = null;
        owner.dispose();
      });
    };
  }, [owner]);
}
