import { AppError, AppErrorKind, StateStore } from "@richie696/react-framework";
import { createCommandResource, type CommandSnapshot } from "../../../shared/state/commandResource";
import type { OwnPasswordPort, OwnPasswordReceipt } from "../api/ownPasswordPort";
import type { SessionIdentity } from "../model/controlPlaneAccess";
import type { IdentitySessionObserver } from "../api/identityAccessPort";
import { prepareOwnPasswordChange, type OwnPasswordChange } from "../model/ownPasswordChange";
import type { PasswordChangeDraft } from "../model/passwordPolicy";

/** Session-bound write owner. Uncertain mutations have no reset/replay API. */
export interface OwnPasswordWorkflow {
  readonly getSnapshot: () => CommandSnapshot<OwnPasswordReceipt>;
  readonly subscribe: (listener: () => void) => () => void;
  readonly submit: (draft: PasswordChangeDraft) => Promise<OwnPasswordReceipt>;
  readonly cancel: () => void;
  readonly dispose: () => void;
}

/**
 * Bind to one account/session epoch. Owner changes abort observation, not the
 * server transaction. Credentials live only in the transient execution closure;
 * published errors/results are redacted. Dispose when this owner leaves the app.
 * Server authorization is mandatory; client checks protect UI ownership only.
 */
export function createOwnPasswordWorkflow(
  port: OwnPasswordPort,
  owner: SessionIdentity,
  session: IdentitySessionObserver,
): OwnPasswordWorkflow {
  const accountId = owner.accountId,
    sessionEpoch = owner.sessionEpoch;
  const idle = Object.freeze({ status: "idle" } as const);
  const state = new StateStore<CommandSnapshot<OwnPasswordReceipt>>(idle);
  let disposed = false;
  function ownsSession() {
    const access = session.read();
    return (
      access.phase === "resolved" &&
      access.facts.kind === "authenticated" &&
      access.facts.identity.accountId === accountId &&
      access.facts.identity.sessionEpoch === sessionEpoch
    );
  }
  const command = createCommandResource<OwnPasswordChange, OwnPasswordReceipt>(
    async (input, signal) => {
      if (!ownsSession())
        throw new AppError(AppErrorKind.FORBIDDEN, "Password session owner changed");
      const receipt = await port.changeOwnPassword(input, signal);
      if (!ownsSession() || signal.aborted)
        throw new AppError(AppErrorKind.CANCELLED, "Password observation cancelled");
      if (!receipt || receipt.sessionDisposition !== "reauthenticate")
        throw new AppError(AppErrorKind.SERVER, "Invalid password receipt", {
          status: 502,
          code: "password_receipt_invalid",
        });
      return Object.freeze({ sessionDisposition: receipt.sessionDisposition });
    },
  );
  const stopCommand = command.subscribe(() => {
    if (disposed) return;
    const snapshot = command.getSnapshot();
    state.set(
      "error" in snapshot
        ? {
            ...snapshot,
            error: new AppError(snapshot.error.kind, "Password operation failed", {
              status: snapshot.error.status,
              code: snapshot.error.code,
            }),
          }
        : snapshot,
    );
  });
  const stopSession = session.subscribe(() => {
    if (!ownsSession()) command.cancel();
  });
  return Object.freeze({
    getSnapshot: state.getSnapshot,
    subscribe: state.subscribe,
    async submit(draft: PasswordChangeDraft) {
      if (disposed) throw new AppError(AppErrorKind.CANCELLED, "Password owner disposed");
      if (!ownsSession()) {
        const error = new AppError(AppErrorKind.FORBIDDEN, "Password session required", {
          status: 403,
          code: "password_session_changed",
        });
        if (
          command.getSnapshot().status !== "result-unknown" &&
          command.getSnapshot().status !== "pending"
        )
          state.set({ status: "error", error });
        throw error;
      }
      const prepared = prepareOwnPasswordChange(draft);
      if (prepared.status === "invalid")
        throw new AppError(AppErrorKind.PROTOCOL, "Invalid password form", {
          status: 400,
          code: "password_form_invalid",
        });
      return command.run(prepared.input);
    },
    cancel: command.cancel,
    dispose() {
      if (disposed) return;
      disposed = true;
      stopSession();
      stopCommand();
      command.dispose();
      state.set(idle);
      state.complete();
    },
  });
}
