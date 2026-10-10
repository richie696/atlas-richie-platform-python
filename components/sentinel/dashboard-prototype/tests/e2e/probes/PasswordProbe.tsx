import { useMemo, useState } from "react";
import { AppError, AppErrorKind, StateStore } from "@richie696/react-framework";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import { AstryxProvider } from "../../../src/app/providers/AstryxProvider";
import {
  createOwnPasswordWorkflow,
  OwnPasswordPage,
} from "../../../src/features/identity/password";
import type {
  SessionIdentity,
  ControlPlaneAccessState,
} from "../../../src/features/identity/model/controlPlaneAccess";

const identity: SessionIdentity = {
  accountId: "self",
  username: "synthetic-viewer",
  roleId: "view",
  capabilities: ["metrics:view"],
  sessionEpoch: "password-probe-session",
};
/** Own the transport double's mutable controls outside React render and props. */
function createPasswordTopology() {
  const session = new StateStore<ControlPlaneAccessState>({
    phase: "resolved",
    facts: { kind: "authenticated", identity },
  });
  const control = {
    mode: "success" as "success" | "current" | "policy" | "rate" | "timeout",
    hold: false,
    releases: [] as (() => void)[],
    calls: 0,
  };
  const workflow = createOwnPasswordWorkflow(
    {
      changeOwnPassword: async (_input, signal) => {
        control.calls++;
        if (control.hold) await new Promise<void>((resolve) => control.releases.push(resolve));
        signal.throwIfAborted();
        if (control.mode !== "success")
          throw control.mode === "timeout"
            ? new AppError(AppErrorKind.TIMEOUT, "PRIVATE-PASSWORD-ERROR")
            : new AppError(AppErrorKind.PROTOCOL, "PRIVATE-PASSWORD-ERROR", {
                status: control.mode === "current" ? 400 : control.mode === "policy" ? 422 : 429,
              });
        return { sessionDisposition: "reauthenticate" };
      },
    },
    identity,
    { read: session.getSnapshot, subscribe: session.subscribe },
  );
  return Object.freeze({
    session,
    workflow,
    readCalls: () => control.calls,
    setMode: (mode: typeof control.mode) => {
      control.mode = mode;
    },
    hold: () => {
      control.hold = true;
    },
    release: () => {
      control.hold = false;
      control.releases.splice(0).forEach((release) => release());
    },
  });
}
/** Test-only effects; actual page/workflow/skin execute under StrictMode. No password enters diagnostics. */
export function PasswordProbe() {
  const [confirmed, setConfirmed] = useState(0),
    [reauthentications, setReauthentications] = useState(0);
  const topology = useMemo(() => createPasswordTopology(), []);
  const { session, workflow } = topology;
  const snapshot = useExternalSnapshot(workflow);
  return (
    <AstryxProvider>
      <div data-password-controls>
        {(["success", "current", "policy", "rate", "timeout"] as const).map((mode) => (
          <button
            key={mode}
            data-mode={mode}
            onClick={() => {
              topology.setMode(mode);
            }}
          >
            {mode}
          </button>
        ))}
        <button
          data-hold
          onClick={() => {
            topology.hold();
          }}
        >
          Hold
        </button>
        <button
          data-release
          onClick={() => {
            topology.release();
          }}
        >
          Release
        </button>
        <button data-expire onClick={() => session.set({ phase: "expired" })}>
          Expire
        </button>
      </div>
      <OwnPasswordPage
        identity={identity}
        workflow={workflow}
        onConfirmed={() => setConfirmed((count) => count + 1)}
        onReauthenticate={() => setReauthentications((count) => count + 1)}
      />
      <output data-password-summary>
        {JSON.stringify({
          status: snapshot.status,
          calls: topology.readCalls(),
          confirmed,
          reauthentications,
        })}
      </output>
    </AstryxProvider>
  );
}
