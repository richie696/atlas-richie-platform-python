import { useLayoutEffect, useMemo, useState } from "react";
import { AppError, AppErrorKind } from "@richie696/react-framework";
import {
  AuthenticationProvider,
  createAuthenticationWorkflow,
  decideControlPlaneAccess,
  useAuthentication,
} from "../../../src/features/identity/authentication";
import type { SessionIdentity } from "../../../src/features/identity/model/controlPlaneAccess";

const identity: SessionIdentity = {
  accountId: "auth-probe",
  username: "probe",
  roleId: "admin",
  capabilities: ["metrics:view", "rules:write"],
  sessionEpoch: "auth-probe-epoch",
};
interface Control {
  principal: SessionIdentity | null;
  holdLogin: boolean;
  holdSession: boolean;
  failLogin: boolean;
  loginReleases: (() => void)[];
  sessionReleases: (() => void)[];
  calls: string[];
  commits: string[];
}

function Consumer({
  control,
}: {
  readonly control: ReturnType<typeof createAuthenticationTopology>;
}) {
  const { workflow, snapshot } = useAuthentication();
  const [password, setPassword] = useState("");
  const decision = decideControlPlaneAccess("admin", snapshot.access);
  const view = {
    phase: snapshot.access.phase,
    decision: decision.kind,
    login: snapshot.login.status,
    logout: snapshot.logout.status,
  };
  useLayoutEffect(() => {
    control.recordCommit(JSON.stringify(view));
  });
  return (
    <section>
      <input
        aria-label="Probe password"
        type="password"
        value={password}
        onChange={(event) => setPassword(event.currentTarget.value)}
      />
      <button
        data-login
        onClick={() => void workflow.login({ username: "probe", password }).catch(() => {})}
      >
        Login
      </button>
      <button data-logout onClick={() => void workflow.logout().catch(() => {})}>
        Logout
      </button>
      <button data-inspect onClick={() => void workflow.inspectSession().catch(() => {})}>
        Inspect session
      </button>
      <button data-expire onClick={workflow.expire}>
        Expire
      </button>
      <button
        data-fail-login
        onClick={() => {
          control.failLogin();
        }}
      >
        Fail login
      </button>
      <button
        data-hold-login
        onClick={() => {
          control.holdLogin();
        }}
      >
        Hold login
      </button>
      <button
        data-hold-session
        onClick={() => {
          control.holdSession();
        }}
      >
        Hold session
      </button>
      <button
        data-release-login
        onClick={() => {
          control.releaseLogin();
        }}
      >
        Release login
      </button>
      <button
        data-release-session
        onClick={() => {
          control.releaseSession();
        }}
      >
        Release session
      </button>
      <output>{JSON.stringify(view)}</output>
      <pre data-auth-history>{JSON.stringify(control.readHistory())}</pre>
    </section>
  );
}

/** Test effect owner; callers receive commands and detached diagnostics, not mutable props. */
function createAuthenticationTopology() {
  const control: Control = {
    principal: null,
    holdLogin: false,
    holdSession: false,
    failLogin: false,
    loginReleases: [],
    sessionReleases: [],
    calls: [],
    commits: [],
  };
  const workflow = createAuthenticationWorkflow({
    readBootstrap: async (signal) => {
      control.calls.push("bootstrap");
      signal.throwIfAborted();
      return { initialized: true };
    },
    readSession: async (signal) => {
      control.calls.push("session");
      if (control.holdSession)
        await new Promise<void>((resolve) => control.sessionReleases.push(resolve));
      signal.throwIfAborted();
      return control.principal;
    },
    login: async (_credentials, signal) => {
      control.calls.push("login");
      if (control.holdLogin)
        await new Promise<void>((resolve) => control.loginReleases.push(resolve));
      signal.throwIfAborted();
      if (control.failLogin) throw new AppError(AppErrorKind.TIMEOUT, "PRIVATE-TRANSPORT-ERROR");
      control.principal = identity;
      return identity;
    },
    logout: async (signal) => {
      control.calls.push("logout");
      signal.throwIfAborted();
      control.principal = null;
    },
  });
  return Object.freeze({
    workflow,
    recordCommit: (commit: string) => {
      control.commits.push(commit);
    },
    readHistory: () => ({ calls: [...control.calls], commits: [...control.commits] }),
    failLogin: () => {
      control.failLogin = true;
    },
    holdLogin: () => {
      control.holdLogin = true;
    },
    holdSession: () => {
      control.holdSession = true;
    },
    releaseLogin: () => {
      control.holdLogin = false;
      control.loginReleases.splice(0).forEach((release) => release());
    },
    releaseSession: () => {
      control.holdSession = false;
      control.sessionReleases.splice(0).forEach((release) => release());
    },
  });
}
/** Test-only Port double; actual Provider/workflow/subscriptions run under StrictMode. */
export function AuthenticationProbe() {
  const control = useMemo(() => createAuthenticationTopology(), []);
  const { workflow } = control;
  return (
    <AuthenticationProvider workflow={workflow}>
      <Consumer control={control} />
    </AuthenticationProvider>
  );
}
