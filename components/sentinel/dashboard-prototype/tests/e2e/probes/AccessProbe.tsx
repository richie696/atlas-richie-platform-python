import { useLayoutEffect, useMemo, useState } from "react";
import { AppError, AppErrorKind } from "@richie696/react-framework";
import { useControlPlaneAccess } from "../../../src/features/identity/state/useControlPlaneAccess";
import { decideControlPlaneAccess } from "../../../src/features/identity/model/controlPlaneAccess";
import type { IdentityAccessPort } from "../../../src/features/identity/api/identityAccessPort";
import type { SessionIdentity } from "../../../src/features/identity/model/controlPlaneAccess";

const principal: SessionIdentity = {
  accountId: "probe-admin",
  username: "probe",
  roleId: "admin",
  capabilities: ["metrics:view", "rules:write"],
  sessionEpoch: "probe-one",
};
type Owner = "admin" | "view" | "anonymous" | "uninitialized" | "unavailable";
interface Control {
  owner: Owner;
  holdBootstrap: boolean;
  releases: (() => void)[];
  calls: string[];
  commits: { owner: Owner; decision: string; accountId: string | null }[];
}

/** Own the mutable transport state outside React; expose explicit effects and safe history copies. */
function createAccessTopology() {
  const control: Control = {
    owner: "admin",
    holdBootstrap: false,
    releases: [],
    calls: [],
    commits: [],
  };
  const port: IdentityAccessPort = {
    readBootstrap: async (signal) => {
      const captured = control.owner;
      control.calls.push(`bootstrap:${captured}`);
      if (control.holdBootstrap)
        await new Promise<void>((resolve) => control.releases.push(resolve));
      signal.throwIfAborted();
      if (captured === "unavailable")
        throw new AppError(AppErrorKind.NETWORK, "PRIVATE-ERROR-NOT-UI");
      return captured === "uninitialized"
        ? { initialized: false, setupAvailable: true, operatorAuthorized: true }
        : { initialized: true };
    },
    readSession: async (signal) => {
      signal.throwIfAborted();
      control.calls.push(`session:${control.owner}`);
      return control.owner === "anonymous"
        ? null
        : {
            ...principal,
            roleId: control.owner === "view" ? "view" : "admin",
            sessionEpoch: control.owner,
          };
    },
    login: async () => principal,
    logout: async () => {},
  };
  return Object.freeze({
    port,
    setOwner: (owner: Owner) => {
      control.owner = owner;
    },
    hold: () => {
      control.holdBootstrap = true;
    },
    release: () => {
      control.holdBootstrap = false;
      for (const release of control.releases.splice(0)) release();
    },
    recordCommit: (commit: Control["commits"][number]) => {
      control.commits.push(commit);
    },
    readHistory: () => ({
      ...control,
      releases: [],
      calls: [...control.calls],
      commits: [...control.commits],
    }),
  });
}
/** StrictMode probe uses the real access Hook/decision. Port double is test-only, never an app fixture gateway. */
export function AccessProbe() {
  const [owner, setOwner] = useState<Owner>("admin");
  const control = useMemo(() => createAccessTopology(), []);
  const { port } = control;
  const access = useControlPlaneAccess(port, owner);
  const decision = decideControlPlaneAccess("admin", access.state);
  const accountId =
    access.state.phase === "resolved" && access.state.facts.kind === "authenticated"
      ? access.state.facts.identity.sessionEpoch
      : null;
  useLayoutEffect(() => {
    control.recordCommit({ owner, decision: decision.kind, accountId });
  }, [control, owner, decision.kind, accountId]);
  return (
    <section>
      {(["admin", "view", "anonymous", "uninitialized", "unavailable"] as const).map((next) => (
        <button
          key={next}
          data-access-owner={next}
          onClick={() => {
            control.setOwner(next);
            setOwner(next);
          }}
        >
          {next}
        </button>
      ))}
      <button
        data-hold
        onClick={() => {
          control.hold();
        }}
      >
        Hold next bootstrap
      </button>
      <button
        data-release
        onClick={() => {
          control.release();
        }}
      >
        Release pending
      </button>
      <button
        data-refresh
        onClick={() => void access.resource.load({ sessionGeneration: owner }).catch(() => {})}
      >
        Refresh identity
      </button>
      <output>
        {JSON.stringify({ owner, phase: access.state.phase, decision: decision.kind, accountId })}
      </output>
      <pre data-access-history>{JSON.stringify(control.readHistory())}</pre>
    </section>
  );
}
