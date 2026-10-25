import { useMemo, useState } from "react";
import { AppError, AppErrorKind } from "@richie696/react-framework";
import { AstryxProvider } from "../../../src/app/providers/AstryxProvider";
import {
  createAuthenticationWorkflow,
  AuthenticationProvider,
  useAuthentication,
} from "../../../src/features/identity/authentication";
import { LoginEntryPage } from "../../../src/features/identity/ui/LoginEntryPage";
import type { SessionIdentity } from "../../../src/features/identity/model/controlPlaneAccess";

const identity: SessionIdentity = {
  accountId: "self",
  username: "synthetic-viewer",
  roleId: "view",
  capabilities: ["metrics:view"],
  sessionEpoch: "login-probe-session",
};
interface Control {
  mode: "success" | "invalid" | "blocked" | "rate" | "timeout";
  principal: SessionIdentity | null;
  holdConfirmation: boolean;
  releases: (() => void)[];
  calls: number;
}
function Consumer({ control }: { readonly control: ReturnType<typeof createLoginTopology> }) {
  const { snapshot } = useAuthentication();
  const [navigations, setNavigations] = useState(0),
    [setupRequests, setSetupRequests] = useState(0),
    [credentialFormRemovedAtConfirmation, setCredentialFormRemovedAtConfirmation] = useState(false);
  return (
    <>
      <div data-login-controls>
        {(["success", "invalid", "blocked", "rate", "timeout"] as const).map((mode) => (
          <button
            data-mode={mode}
            key={mode}
            onClick={() => {
              control.setMode(mode);
            }}
          >
            {mode}
          </button>
        ))}
        <button
          data-hold-confirmation
          onClick={() => {
            control.holdConfirmation();
          }}
        >
          Hold confirmation
        </button>
        <button
          data-release-confirmation
          onClick={() => {
            control.releaseConfirmation();
          }}
        >
          Release confirmation
        </button>
      </div>
      <LoginEntryPage
        onAuthenticated={() => {
          setCredentialFormRemovedAtConfirmation(
            !document.querySelector('#login-entry-probe input[autocomplete="current-password"]'),
          );
          setNavigations((count) => count + 1);
        }}
        onSetupRequired={() => setSetupRequests((count) => count + 1)}
      />
      <output data-login-summary>
        {JSON.stringify({
          calls: control.readCalls(),
          login: snapshot.login.status,
          phase: snapshot.access.phase,
          navigations,
          setupRequests,
          credentialFormRemovedAtConfirmation,
        })}
      </output>
    </>
  );
}
/** Transport ownership is independent of React render; all mutation stays behind explicit test commands. */
function createLoginTopology(initialized: boolean, failBootstrap: boolean) {
  const control: Control = {
    mode: "success",
    principal: null,
    holdConfirmation: false,
    releases: [],
    calls: 0,
  };
  const workflow = createAuthenticationWorkflow({
    readBootstrap: async (signal) => {
      signal.throwIfAborted();
      if (failBootstrap) throw new AppError(AppErrorKind.NETWORK, "PRIVATE-BOOTSTRAP-ERROR");
      return initialized
        ? { initialized: true }
        : { initialized: false, setupAvailable: true, operatorAuthorized: true };
    },
    readSession: async (signal) => {
      if (control.holdConfirmation)
        await new Promise<void>((resolve) => control.releases.push(resolve));
      signal.throwIfAborted();
      return control.principal;
    },
    login: async (_credentials, signal) => {
      signal.throwIfAborted();
      control.calls++;
      if (control.mode === "invalid" || control.mode === "blocked" || control.mode === "rate")
        throw new AppError(
          control.mode === "invalid"
            ? AppErrorKind.UNAUTHORIZED
            : control.mode === "blocked"
              ? AppErrorKind.FORBIDDEN
              : AppErrorKind.PROTOCOL,
          "PRIVATE-LOGIN-ERROR",
          control.mode === "rate"
            ? { status: 429, code: "rate_limited", retryAfterMs: 2_500 }
            : { status: control.mode === "invalid" ? 401 : 403 },
        );
      control.principal = identity;
      if (control.mode === "timeout")
        throw new AppError(AppErrorKind.TIMEOUT, "PRIVATE-LOGIN-ERROR");
      return identity;
    },
    logout: async () => {
      control.principal = null;
    },
  });
  return Object.freeze({
    workflow,
    readCalls: () => control.calls,
    setMode: (mode: Control["mode"]) => {
      control.mode = mode;
    },
    holdConfirmation: () => {
      control.holdConfirmation = true;
    },
    releaseConfirmation: () => {
      control.holdConfirmation = false;
      control.releases.splice(0).forEach((release) => release());
    },
  });
}
/** Test-only transport seam; actual authentication owner and login UI under StrictMode. */
export function LoginEntryProbe({
  initialized = true,
  failBootstrap = false,
}: {
  readonly initialized?: boolean;
  readonly failBootstrap?: boolean;
}) {
  const control = useMemo(
    () => createLoginTopology(initialized, failBootstrap),
    [initialized, failBootstrap],
  );
  const { workflow } = control;
  return (
    <AstryxProvider>
      <AuthenticationProvider workflow={workflow}>
        <Consumer control={control} />
      </AuthenticationProvider>
    </AstryxProvider>
  );
}
