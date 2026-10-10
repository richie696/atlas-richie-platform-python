import { useEffect, useLayoutEffect, useRef } from "react";
import { useNavigationProtectionRegistry } from "./NavigationProtectionProvider";
/** Register local dirty/locked state with the app. Isolated consumers fall back to native-close protection. Never retains form values. */
export function useBeforeUnloadGuard(
  protectedState: boolean,
  locked = false,
  onDiscard?: () => void,
): void {
  const registry = useNavigationProtectionRegistry(),
    discard = useRef(onDiscard);
  // External navigation can fire before the next paint. Update the callback/registration at commit, never during render.
  useLayoutEffect(() => {
    discard.current = onDiscard;
  }, [onDiscard]);
  useLayoutEffect(() => {
    if (!registry || (!protectedState && !locked)) return;
    return registry.register({
      dirty: protectedState && !locked,
      locked,
      discard: () => discard.current?.(),
    });
  }, [registry, protectedState, locked]);
  useEffect(() => {
    if (registry || (!protectedState && !locked)) return;
    const prevent = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", prevent);
    return () => window.removeEventListener("beforeunload", prevent);
  }, [registry, protectedState, locked]);
}
