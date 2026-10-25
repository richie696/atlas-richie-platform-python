import { NAVIGATION_HISTORY, type NavigateOptions } from "../../shared/types/navigation";
import type { HashLocation, HashNavigationPort } from "./hashNavigationController";
const STATE_KEY = "sentinelHashNavigation";
const RESTORE_TIMEOUT_MS = 2_000;
/** Owns only this SPA's same-document history metadata. Preserves pre-existing state properties and never stores application form/credentials. */
export function createBrowserHashPort(sessionKey: string): HashNavigationPort {
  let activeSessionKey = sessionKey,
    branch = 0;
  const read = (): HashLocation => {
    const entry = window.history.state?.[STATE_KEY];
    return {
      hash: window.location.hash,
      index:
        entry?.sessionKey === activeSessionKey && Number.isSafeInteger(entry.index)
          ? entry.index
          : null,
    };
  };
  const metadata = (index: number) => ({
    ...window.history.state,
    [STATE_KEY]: { sessionKey: activeSessionKey, index },
  });
  const replaceUnmanaged = (hash: string) => {
    // Unknown positions invalidate older index arithmetic; start a new managed branch instead of guessing their offset.
    if (read().index === null) activeSessionKey = `${sessionKey}:${++branch}`;
    window.history.replaceState(
      metadata(read().index ?? 0),
      "",
      hash || window.location.pathname + window.location.search,
    );
    return read();
  };
  return Object.freeze({
    read,
    replaceUnmanaged,
    commit(target: string, options: NavigateOptions) {
      const index = read().index ?? 0,
        replace = options.history === NAVIGATION_HISTORY.Replace;
      window.history[replace ? "replaceState" : "pushState"](
        metadata(replace ? index : index + 1),
        "",
        target,
      );
      if (options.scroll ?? !replace) window.scrollTo({ top: 0, behavior: "smooth" });
      return read();
    },
    moveTo(target: HashLocation, signal: AbortSignal) {
      const current = read();
      if (signal.aborted) return Promise.reject(new Error("History observation cancelled"));
      if (target.index === null || current.index === null)
        return Promise.reject(new Error("Unmanaged history position"));
      if (target.index === current.index)
        return current.hash === target.hash
          ? Promise.resolve(current)
          : Promise.reject(new Error("History location mismatch"));
      const delta = target.index - current.index;
      return new Promise<HashLocation>((resolve, reject) => {
        const finish = () => {
          const candidate = read();
          if (candidate.index !== target.index || candidate.hash !== target.hash) return;
          clearTimeout(timeout);
          cleanup();
          resolve(candidate);
        };
        const cleanup = () => {
          clearTimeout(timeout);
          window.removeEventListener("popstate", finish);
          window.removeEventListener("hashchange", finish);
          signal.removeEventListener("abort", cancel);
        };
        const cancel = () => {
          cleanup();
          reject(new Error("History observation cancelled"));
        };
        const timeout = setTimeout(() => {
          cleanup();
          reject(new Error("History recovery timed out"));
        }, RESTORE_TIMEOUT_MS);
        window.addEventListener("popstate", finish);
        window.addEventListener("hashchange", finish);
        signal.addEventListener("abort", cancel, { once: true });
        window.history.go(delta);
      });
    },
    subscribe(listener: () => void) {
      if (read().index === null) replaceUnmanaged(window.location.hash);
      window.addEventListener("popstate", listener);
      window.addEventListener("hashchange", listener);
      return () => {
        window.removeEventListener("popstate", listener);
        window.removeEventListener("hashchange", listener);
      };
    },
  });
}
