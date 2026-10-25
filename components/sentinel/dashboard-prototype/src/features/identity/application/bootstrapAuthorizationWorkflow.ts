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
  readonly authorizeLocal: () => Promise<void>;
  readonly inspect: () => Promise<BootstrapOperatorGate>;
  readonly cancel: () => void;
  readonly dispose: () => void;
}

/** Compose a safe gate read and single-flight local/remote bootstrap commands. */
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
  const command = createCommandResource<
    { readonly kind: "local" } | { readonly kind: "code"; readonly code: string },
    void
  >((input, signal) =>
    input.kind === "local" ? port.authorizeLocal(signal) : port.authorize(input.code, signal),
  );
  const confirmationError = new AppError(
    AppErrorKind.PROTOCOL,
    "Bootstrap authorization result requires authoritative inspection",
    { status: 502, code: "bootstrap_grant_unconfirmed" },
  );
  let confirmationRequired = false;
  const commandSnapshot = (): CommandSnapshot<void> => {
    const current = command.getSnapshot();
    return confirmationRequired && current.status === "success"
      ? { status: "result-unknown", error: confirmationError }
      : current;
  };
  const state = new StateStore<BootstrapAuthorizationSnapshot>({
    gate: gate.getSnapshot(),
    command: commandSnapshot(),
  });
  let revision = 0;
  const publish = () => {
    const next = { gate: gate.getSnapshot(), command: commandSnapshot() };
    const previous = state.getSnapshot();
    if (previous.gate !== next.gate || previous.command !== next.command)
      state.set(Object.freeze(next));
  };
  const subscriptions = [gate.subscribe(publish), command.subscribe(publish)];
  const restore = (forceRefresh = false) => gate.load({ revision: ++revision, forceRefresh });
  let authorizationInProgress = false;
  const assertNotAuthorizing = () => {
    if (authorizationInProgress)
      throw new AppError(AppErrorKind.DUPLICATE, "Bootstrap authorization requires confirmation");
  };

  const exchangeAndConfirm = async (
    input: { readonly kind: "local" } | { readonly kind: "code"; readonly code: string },
  ) => {
    assertNotAuthorizing();
    if (confirmationRequired)
      throw new AppError(AppErrorKind.DUPLICATE, "Inspect the original bootstrap authorization");
    const current = gate.getSnapshot();
    if (
      current.status !== "ready" ||
      current.data.kind !== "open" ||
      current.data.authorized ||
      (input.kind === "code" && !input.code.trim())
    )
      throw new AppError(AppErrorKind.FORBIDDEN, "Bootstrap authorization is not available", {
        status: 403,
        code: "bootstrap_unauthorized",
      });
    authorizationInProgress = true;
    try {
      await command.run(input);
      const confirmed = await restore(true);
      if (confirmed.kind !== "open" || !confirmed.authorized) throw confirmationError;
    } catch (error) {
      if (command.getSnapshot().status === "success") {
        confirmationRequired = true;
        publish();
      }
      throw error;
    } finally {
      authorizationInProgress = false;
    }
  };

  return Object.freeze({
    getSnapshot: state.getSnapshot,
    subscribe: state.subscribe,
    restore(forceRefresh = false) {
      assertNotAuthorizing();
      return restore(forceRefresh);
    },
    async authorize(code: string) {
      return exchangeAndConfirm({ kind: "code", code });
    },
    async authorizeLocal() {
      return exchangeAndConfirm({ kind: "local" });
    },
    async inspect() {
      assertNotAuthorizing();
      const confirmed = await restore(true);
      if (confirmed.kind === "open" && confirmed.authorized) {
        confirmationRequired = false;
        command.reset();
        publish();
      }
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
