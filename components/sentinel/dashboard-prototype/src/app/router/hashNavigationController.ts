import { StateStore } from "@richie696/react-framework";
import type { NavigationProtectionRegistry } from "../../shared/state/navigationProtection";
import type { NavigateOptions } from "../../shared/types/navigation";
export interface HashLocation {
  readonly hash: string;
  readonly index: number | null;
}
/** Managed-history adapter. A foreign hash has no guessed index; it is restored by replacement, not an invented history delta. */
export interface HashNavigationPort {
  read(): HashLocation;
  commit(target: string, options: NavigateOptions): HashLocation;
  replaceUnmanaged(target: string): HashLocation;
  moveTo(target: HashLocation, signal: AbortSignal): Promise<HashLocation>;
  subscribe(listener: () => void): () => void;
}
export interface NavigationPrompt {
  readonly kind: "dirty" | "locked" | "history-failed" | "discard-failed";
  readonly target: HashLocation;
  readonly options: NavigateOptions;
  readonly historical: boolean;
}
export interface HashNavigationSnapshot {
  readonly location: HashLocation;
  readonly prompt: NavigationPrompt | null;
  readonly restoring: boolean;
}
/** Only accepted hashes reach route readers. Browser back/forward is restored before a dirty confirmation can discard the old view. */
export function createHashNavigationController(
  port: HashNavigationPort,
  protection: NavigationProtectionRegistry,
) {
  const state = new StateStore<HashNavigationSnapshot>({
    location: port.read(),
    prompt: null,
    restoring: false,
  });
  let stop: (() => void) | null = null,
    ticket = 0;
  let observation = new AbortController();
  const blocked = () => protection.getSnapshot().locked;
  const prompted = () => blocked() || protection.getSnapshot().dirty;
  const publishPrompt = (prompt: NavigationPrompt) =>
    state.set({ ...state.getSnapshot(), prompt, restoring: false });
  function request(target: string, options: NavigateOptions = {}) {
    if (!target.startsWith("#")) throw new Error("Same-document hash target required");
    const current = state.getSnapshot();
    if (target === current.location.hash || current.restoring || current.prompt) return;
    if (prompted())
      publishPrompt({
        kind: blocked() ? "locked" : "dirty",
        target: { hash: target, index: null },
        options,
        historical: false,
      });
    else state.set({ location: port.commit(target, options), prompt: null, restoring: false });
  }
  async function nativeChange() {
    const current = state.getSnapshot(),
      candidate = port.read();
    if (current.restoring) return;
    if (candidate.hash === current.location.hash) {
      if (candidate.index !== current.location.index)
        state.set({ ...current, location: candidate });
      return;
    }
    if (!prompted() && !current.prompt) {
      state.set({ location: candidate, prompt: null, restoring: false });
      return;
    }
    const generation = ++ticket;
    state.set({ ...current, restoring: true });
    const intent: NavigationPrompt = {
      kind: blocked() ? "locked" : "dirty",
      target: candidate,
      historical: candidate.index !== null && current.location.index !== null,
      options: {},
    };
    try {
      const restored = intent.historical
        ? await port.moveTo(current.location, observation.signal)
        : port.replaceUnmanaged(current.location.hash);
      if (generation !== ticket) return;
      state.set({
        location: restored,
        prompt: current.prompt ?? { ...intent, kind: blocked() ? "locked" : "dirty" },
        restoring: false,
      });
    } catch {
      if (generation !== ticket) return;
      const location = port.replaceUnmanaged(current.location.hash);
      state.set({
        location,
        prompt: { ...intent, kind: "history-failed", historical: false },
        restoring: false,
      });
    }
  }
  return Object.freeze({
    getSnapshot: state.getSnapshot,
    subscribe: state.subscribe,
    request,
    start() {
      if (stop) return;
      const stopHistory = port.subscribe(() => {
        void nativeChange();
      });
      // The browser adapter stamps the initial entry on connection, not construction.
      observation = new AbortController();
      if (port.read().hash === state.getSnapshot().location.hash)
        state.set({ ...state.getSnapshot(), location: port.read() });
      else void nativeChange();
      const stopProtection = protection.subscribe(() => {
        const current = state.getSnapshot();
        if (current.prompt && ["dirty", "locked"].includes(current.prompt.kind)) {
          const kind = blocked() ? "locked" : "dirty";
          if (kind !== current.prompt.kind)
            state.set({ ...current, prompt: { ...current.prompt, kind } });
        }
      });
      stop = () => {
        stopHistory();
        stopProtection();
      };
    },
    stop() {
      ticket++;
      observation.abort();
      stop?.();
      stop = null;
      state.set({ ...state.getSnapshot(), restoring: false });
    },
    cancel() {
      const current = state.getSnapshot();
      if (!current.restoring) state.set({ ...current, prompt: null });
    },
    async confirm() {
      const current = state.getSnapshot(),
        intent = current.prompt;
      if (!intent || current.restoring || !["dirty", "locked"].includes(intent.kind)) return;
      if (blocked()) {
        publishPrompt({ ...intent, kind: "locked" });
        return;
      }
      if (!intent.historical) {
        const abandoned = protection.discard();
        if (abandoned !== "done") {
          publishPrompt({ ...intent, kind: abandoned === "blocked" ? "locked" : "discard-failed" });
          return;
        }
        state.set({
          location: port.commit(intent.target.hash, intent.options),
          prompt: null,
          restoring: false,
        });
        return;
      }
      const generation = ++ticket;
      state.set({ ...current, restoring: true });
      try {
        const location = await port.moveTo(intent.target, observation.signal);
        if (generation !== ticket) return;
        const abandoned = blocked() ? "blocked" : protection.discard();
        if (abandoned !== "done") {
          const restored = await port.moveTo(current.location, observation.signal);
          if (generation === ticket)
            state.set({
              location: restored,
              prompt: { ...intent, kind: abandoned === "blocked" ? "locked" : "discard-failed" },
              restoring: false,
            });
        } else state.set({ location, prompt: null, restoring: false });
      } catch {
        if (generation === ticket)
          state.set({
            location: port.replaceUnmanaged(current.location.hash),
            prompt: { ...intent, kind: "history-failed", historical: false },
            restoring: false,
          });
      }
    },
  });
}
export type HashNavigationController = ReturnType<typeof createHashNavigationController>;
