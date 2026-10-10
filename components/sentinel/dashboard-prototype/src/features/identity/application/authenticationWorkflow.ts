import { AppError, AppErrorKind, StateStore } from "@richie696/react-framework";
import { createCommandResource, type CommandSnapshot } from "../../../shared/state/commandResource";
import type { IdentityAccessPort } from "../api/identityAccessPort";
import { validateLoginCredentials, type LoginCredentials } from "../model/account";
import type {
  AccessFacts,
  ControlPlaneAccessState,
  SessionIdentity,
} from "../model/controlPlaneAccess";
import { accessStateFromResource, createAccessResource } from "../state/accessResource";

export interface AuthenticationSnapshot {
  readonly access: ControlPlaneAccessState;
  readonly login: CommandSnapshot<SessionIdentity>;
  readonly logout: CommandSnapshot<void>;
}

/** One application-scoped owner, shared by bootstrap, login, menus and access guards. */
export interface AuthenticationWorkflow {
  readonly getSnapshot: () => AuthenticationSnapshot;
  readonly subscribe: (listener: () => void) => () => void;
  /** Bootstrap + session restoration only; never reads a browser-stored role as authentication. */
  readonly restore: () => Promise<AccessFacts>;
  /** Revalidate current authority after returning to a visible app; never resolves unknown writes. */
  readonly revalidateAccess: () => Promise<AccessFacts | undefined>;
  /** Server login then separate session read-back. Return does not bypass access state. */
  readonly login: (credentials: LoginCredentials) => Promise<SessionIdentity>;
  /** Clear only a known rejected login after credentials change; never dismiss an unknown write. */
  readonly clearLoginFailure: () => void;
  readonly logout: () => Promise<void>;
  /** Immediately drop privileged facts after an authentication failure or session invalidation. */
  readonly expire: () => void;
  /** Explicit investigation; failure retains unknown outcome and never automatically repeats the write. */
  readonly inspectSession: () => Promise<AccessFacts>;
  /** Abort observation on cleanup; an issued write may have an unknown outcome. */
  readonly cancel: () => void;
  readonly dispose: () => void;
}

/** Composition-owned observation invalidation. UI phases and server session facts never act as transport generations. */
export interface AuthenticationObservationOwner {
  readonly begin: () => void;
}

/** Compose existing query/command owners; no second copy of the session or credentials in a React store. */
export function createAuthenticationWorkflow(
  port: IdentityAccessPort,
  observationOwner?: AuthenticationObservationOwner,
): AuthenticationWorkflow {
  const access = createAccessResource(port);
  const login = createCommandResource((credentials: LoginCredentials, signal) =>
    port.login(credentials, signal),
  );
  const logout = createCommandResource((_input: void, signal) => port.logout(signal));
  const state = new StateStore<AuthenticationSnapshot>({
    access: { phase: "unknown" },
    login: login.getSnapshot(),
    logout: logout.getSnapshot(),
  });
  let generation = 0,
    readGeneration = 0,
    disposed = false,
    expired = false,
    confirmationFailed = false;
  let lastConfirmedFacts: AccessFacts | undefined;
  let active: "login" | "logout" | "inspection" | "foreground" | undefined;
  let foregroundRead: Promise<AccessFacts> | undefined;

  const assertOpen = () => {
    if (disposed) throw new AppError(AppErrorKind.CANCELLED, "Authentication owner disposed");
  };
  const assertNoCommand = () => {
    assertOpen();
    if (
      active ||
      login.getSnapshot().status === "result-unknown" ||
      logout.getSnapshot().status === "result-unknown"
    )
      throw new AppError(
        AppErrorKind.DUPLICATE,
        "Authentication operation requires completion or investigation",
      );
  };
  const publish = () => {
    if (disposed) return;
    const loginState = login.getSnapshot(),
      logoutState = logout.getSnapshot();
    const projectedBase: ControlPlaneAccessState = expired
      ? { phase: "expired" }
      : active === "inspection"
        ? { phase: "checking" }
        : confirmationFailed ||
            loginState.status === "result-unknown" ||
            logoutState.status === "result-unknown"
          ? { phase: "unavailable" }
          : active === "login" && loginState.status === "pending"
            ? { phase: "authenticating" }
            : active
              ? { phase: "checking" }
              : accessStateFromResource(access.getSnapshot());
    const previousSetupFacts =
      lastConfirmedFacts?.kind === "uninitialized" &&
      lastConfirmedFacts.setupAvailable &&
      lastConfirmedFacts.operatorAuthorized
        ? lastConfirmedFacts
        : undefined;
    const projected: ControlPlaneAccessState =
      projectedBase.phase === "checking" && previousSetupFacts
        ? { ...projectedBase, previousFacts: previousSetupFacts }
        : projectedBase;
    const previous = state.getSnapshot();
    const sameAccess =
      previous.access.phase === projected.phase &&
      (previous.access.phase !== "resolved" ||
        projected.phase !== "resolved" ||
        previous.access.facts === projected.facts);
    if (sameAccess && previous.login === loginState && previous.logout === logoutState) return;
    state.set(
      Object.freeze({
        access: sameAccess ? previous.access : projected,
        login: loginState,
        logout: logoutState,
      }),
    );
  };
  const subscriptions = [
    access.subscribe(publish),
    login.subscribe(publish),
    logout.subscribe(publish),
  ];
  const restore = async () => {
    const readTicket = ++readGeneration;
    try {
      const facts = await access.load({ sessionGeneration: String(readTicket) });
      if (readTicket === readGeneration) lastConfirmedFacts = facts;
      return facts;
    } catch (cause) {
      if (readTicket === readGeneration) lastConfirmedFacts = undefined;
      throw cause;
    }
  };
  const confirmedFacts = () => {
    const current = accessStateFromResource(access.getSnapshot());
    return current.phase === "resolved" ? current.facts : undefined;
  };
  const ensureCurrent = (ticket: number) => {
    if (ticket !== generation || disposed)
      throw new AppError(AppErrorKind.CANCELLED, "Authentication owner changed");
  };
  return Object.freeze({
    getSnapshot: state.getSnapshot,
    subscribe: state.subscribe,
    async restore() {
      assertOpen();
      if (active === "foreground") {
        // An explicit setup/authentication boundary read takes precedence over
        // a background focus refresh that may have started before a write.
        generation++;
        foregroundRead = undefined;
        active = undefined;
      } else assertNoCommand();
      observationOwner?.begin();
      expired = false;
      confirmationFailed = false;
      return restore();
    },
    async revalidateAccess() {
      assertOpen();
      const loginState = login.getSnapshot();
      const logoutState = logout.getSnapshot();
      if (active === "foreground" && foregroundRead) return foregroundRead;
      if (
        active ||
        expired ||
        confirmationFailed ||
        loginState.status === "result-unknown" ||
        logoutState.status === "result-unknown"
      )
        return undefined;
      if (foregroundRead) return foregroundRead;
      const current = access.getSnapshot();
      if (
        current.status === "idle" ||
        current.status === "loading" ||
        current.status === "refreshing"
      )
        return undefined;

      const ticket = ++generation;
      active = "foreground";
      const read = restore();
      foregroundRead = read;
      publish();
      try {
        const facts = await read;
        ensureCurrent(ticket);
        return facts;
      } finally {
        if (foregroundRead === read) foregroundRead = undefined;
        if (ticket === generation) {
          active = undefined;
          publish();
        }
      }
    },
    async login(credentials: LoginCredentials) {
      assertNoCommand();
      if (confirmedFacts()?.kind !== "anonymous")
        throw new AppError(
          AppErrorKind.FORBIDDEN,
          "Login requires confirmed initialized anonymous state",
        );
      if (validateLoginCredentials(credentials).length)
        throw new AppError(AppErrorKind.PROTOCOL, "Invalid login form", {
          status: 400,
          code: "credentials_required",
        });
      observationOwner?.begin();
      const ticket = ++generation;
      active = "login";
      try {
        const result = await login.run({
          username: credentials.username.trim(),
          password: credentials.password,
        });
        ensureCurrent(ticket);
        access.reset();
        const facts = await restore();
        ensureCurrent(ticket);
        if (facts.kind !== "authenticated" || facts.identity.accountId !== result.accountId) {
          access.reset();
          throw new AppError(
            AppErrorKind.PROTOCOL,
            "Session confirmation did not match login response",
            { code: "session_confirmation_mismatch" },
          );
        }
        return result;
      } catch (cause) {
        if (ticket === generation && login.getSnapshot().status === "success")
          confirmationFailed = true;
        throw cause;
      } finally {
        active = undefined;
        publish();
      }
    },
    clearLoginFailure() {
      assertOpen();
      if (active || expired || confirmationFailed) return;
      const status = login.getSnapshot().status;
      if (status === "error" || status === "conflict") login.reset();
    },
    async logout() {
      assertNoCommand();
      if (confirmedFacts()?.kind !== "authenticated")
        throw new AppError(AppErrorKind.FORBIDDEN, "Logout requires confirmed session");
      observationOwner?.begin();
      const ticket = ++generation;
      active = "logout";
      login.reset();
      lastConfirmedFacts = undefined;
      access.reset();
      try {
        await logout.run();
        ensureCurrent(ticket);
        const facts = await restore();
        ensureCurrent(ticket);
        if (facts.kind === "authenticated") {
          access.reset();
          throw new AppError(AppErrorKind.PROTOCOL, "Session remained authenticated after logout", {
            code: "logout_confirmation_mismatch",
          });
        }
      } catch (cause) {
        if (ticket === generation) confirmationFailed = true;
        throw cause;
      } finally {
        active = undefined;
        publish();
      }
    },
    expire() {
      assertOpen();
      observationOwner?.begin();
      generation++;
      expired = true;
      lastConfirmedFacts = undefined;
      access.reset();
      login.cancel();
      logout.cancel();
      if (login.getSnapshot().status !== "pending") login.reset();
      if (logout.getSnapshot().status !== "pending") logout.reset();
      publish();
    },
    async inspectSession() {
      assertOpen();
      if (active)
        throw new AppError(AppErrorKind.DUPLICATE, "Authentication command still pending");
      observationOwner?.begin();
      const ticket = ++generation;
      active = "inspection";
      try {
        // Observe CURRENT session validity, not completion of every earlier server-side operation.
        const facts = await restore();
        ensureCurrent(ticket);
        login.reset();
        logout.reset();
        expired = false;
        confirmationFailed = false;
        return facts;
      } finally {
        active = undefined;
        publish();
      }
    },
    cancel() {
      observationOwner?.begin();
      access.cancel();
      login.cancel();
      logout.cancel();
    },
    dispose() {
      if (disposed) return;
      observationOwner?.begin();
      generation++;
      disposed = true;
      lastConfirmedFacts = undefined;
      subscriptions.forEach((unsubscribe) => unsubscribe());
      access.dispose();
      login.dispose();
      logout.dispose();
      state.set(
        Object.freeze({
          access: { phase: "expired" },
          login: { status: "idle" },
          logout: { status: "idle" },
        } as const),
      );
      state.complete();
    },
  });
}
