import { AppError, AppErrorKind, StateStore } from "@richie696/react-framework";
import type { CommandSnapshot } from "../../../shared/state/commandResource";
import { createCommandResource } from "../../../shared/state/commandResource";
import { createQueryResource, type QuerySnapshot } from "../../../shared/state/queryResource";
import type { BootstrapAuthorizationPort } from "../api/bootstrapAuthorizationPort";
import type { BootstrapOperatorGate } from "../model/bootstrapOperator";

export interface BootstrapAuthorizationSnapshot {
  readonly gate: QuerySnapshot<BootstrapOperatorGate>;
  readonly command: CommandSnapshot<void>;
}

/** One-use deployment-code exchange; snapshots never retain the submitted code. */
export interface BootstrapAuthorizationWorkflow {
  readonly getSnapshot: () => BootstrapAuthorizationSnapshot;
  readonly subscribe: (listener: () => void) => () => void;
  readonly restore: (forceRefresh?: boolean) => Promise<BootstrapOperatorGate>;
  readonly authorize: (code: string) => Promise<void>;
  readonly inspect: () => Promise<BootstrapOperatorGate>;
  readonly cancel: () => void;
  readonly dispose: () => void;
}

/** Compose a safe gate read and a single-flight one-time authorization command. */
export function createBootstrapAuthorizationWorkflow(
  port: BootstrapAuthorizationPort,
): BootstrapAuthorizationWorkflow {
  const gate = createQueryResource<
    { readonly revision: number; readonly forceRefresh: boolean },
    BootstrapOperatorGate
  >({
    keyOf: ({ revision, forceRefresh }) =>
      JSON.stringify(["bootstrap-operator-gate", revision, forceRefresh]),
    read: ({ forceRefresh }, signal) => port.readGate(signal, { forceRefresh }),
    classify: () => "ready",
  });
  const command = createCommandResource<string, void>((code, signal) =>
    port.authorize(code, signal),
  );
  const state = new StateStore<BootstrapAuthorizationSnapshot>({
    gate: gate.getSnapshot(),
    command: command.getSnapshot(),
  });
  let revision = 0;
  const publish = () => {
    const next = { gate: gate.getSnapshot(), command: command.getSnapshot() };
    const previous = state.getSnapshot();
    if (previous.gate !== next.gate || previous.command !== next.command)
      state.set(Object.freeze(next));
  };
  const subscriptions = [gate.subscribe(publish), command.subscribe(publish)];
  const restore = (forceRefresh = false) => gate.load({ revision: ++revision, forceRefresh });
  let authorizationInProgress = false;
  const assertAuthorizationIdle = () => {
    if (authorizationInProgress)
      throw new AppError(AppErrorKind.DUPLICATE, "Bootstrap authorization requires confirmation");
  };

  return Object.freeze({
    getSnapshot: state.getSnapshot,
    subscribe: state.subscribe,
    restore(forceRefresh = false) {
      assertAuthorizationIdle();
      return restore(forceRefresh);
    },
    async authorize(code: string) {
      assertAuthorizationIdle();
      const current = gate.getSnapshot();
      if (
        current.status !== "ready" ||
        current.data.kind !== "open" ||
        current.data.authorized ||
        !code.trim()
      )
        throw new AppError(AppErrorKind.FORBIDDEN, "Bootstrap authorization is not available", {
          status: 403,
          code: "bootstrap_unauthorized",
        });
      authorizationInProgress = true;
      try {
        await command.run(code);
        // Keep the use case single-flight through authoritative read-back. The command resource
        // becomes successful as soon as POST completes, but the one-time grant is not yet known.
        const confirmed = await restore(true);
        if (confirmed.kind !== "open" || !confirmed.authorized)
          throw new AppError(AppErrorKind.PROTOCOL, "Bootstrap grant was not confirmed", {
            status: 502,
            code: "bootstrap_grant_unconfirmed",
          });
      } finally {
        authorizationInProgress = false;
      }
    },
    async inspect() {
      assertAuthorizationIdle();
      const confirmed = await restore(true);
      if (confirmed.kind === "open" && confirmed.authorized) command.reset();
      return confirmed;
    },
    cancel() {
      gate.cancel();
      command.cancel();
    },
    dispose() {
      subscriptions.forEach((unsubscribe) => unsubscribe());
      gate.dispose();
      command.dispose();
      state.complete();
    },
  });
}
