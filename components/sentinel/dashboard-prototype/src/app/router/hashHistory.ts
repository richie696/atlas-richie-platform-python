import { NAVIGATION_HISTORY, type NavigateOptions } from "../../shared/types/navigation";

/** The single browser history effect boundary. Never receives credentials or session authority. */
export function writeHashHistory(target: string, options: NavigateOptions = {}): void {
  if (target === window.location.hash) return;
  if (options.history === NAVIGATION_HISTORY.Replace) {
    const oldURL = window.location.href;
    window.history.replaceState(window.history.state, "", target);
    // replaceState does not emit hashchange, so external-store subscribers need
    // one notification. Back/forward and normal hash writes emit their own.
    window.dispatchEvent(
      new HashChangeEvent("hashchange", { oldURL, newURL: window.location.href }),
    );
  } else {
    window.location.hash = target;
  }
  if (options.scroll ?? options.history !== NAVIGATION_HISTORY.Replace)
    window.scrollTo({ top: 0, behavior: "smooth" });
}
