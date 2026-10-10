import { AppError, AppErrorKind, StateStore } from "@richie696/react-framework";
import { createCommandResource } from "../../../shared/state/commandResource";
import { createQueryResource, type QuerySnapshot } from "../../../shared/state/queryResource";
import type {
  ConnectionCheck,
  InitializationObservation,
  InitializationPort,
} from "../api/initializationPort";
import type { BootstrapFact } from "../model/controlPlaneAccess";
import type {
  SetupSourceInput,
  SetupStorageInput,
  SetupSubmission,
} from "../model/setupSubmission";

/** Ready means THIS request completed AND bootstrap confirmed initialization, not merely a successful POST. */
export type InitializationState =
  | { readonly status: "idle" | "closed" }
  | { readonly status: "submitting" | "checking" | "result-unknown"; readonly requestKey: string }
  | {
      readonly status: "pending" | "ready";
      readonly requestKey: string;
      readonly operationId: string;
    }
  | {
      readonly status: "rejected";
      readonly requestKey: string;
      readonly reason: "validation" | "setup-closed" | "dependency";
    }
  | {
      readonly status: "error" | "conflict";
      readonly requestKey: string;
      readonly error: AppError;
    };

export interface InitializationSnapshot {
  readonly bootstrap: QuerySnapshot<BootstrapFact>;
  readonly databaseCheck: QuerySnapshot<ConnectionCheck>;
  readonly sourceCheck: QuerySnapshot<ConnectionCheck>;
  readonly initialization: InitializationState;
}
/** Stable setup-page owner; secrets are transient call inputs, never part of a published snapshot or key. */
export interface InitializationWorkflow {
  readonly getSnapshot: () => InitializationSnapshot;
  readonly subscribe: (listener: () => void) => () => void;
  readonly restore: (forceRefresh?: boolean) => Promise<BootstrapFact>;
  readonly checkDatabase: (input: SetupStorageInput) => Promise<ConnectionCheck>;
  readonly checkSource: (input: SetupSourceInput) => Promise<ConnectionCheck>;
  /** Field/provider/auth changes invalidate old connection facts, including late responses. */
  readonly invalidateChecks: () => void;
  readonly initialize: (input: SetupSubmission) => Promise<InitializationState>;
  /** Explicit lookup of the ORIGINAL request. No automatic polling or write replay. */
  readonly inspect: () => Promise<InitializationState>;
  readonly cancel: () => void;
  readonly dispose: () => void;
}

/** Compose the existing bounded query and mutation owners; never persist a second copy of form credentials. */
export function createInitializationWorkflow(
  port: InitializationPort,
  newRequestKey: () => string,
): InitializationWorkflow {
  const bootstrap = createQueryResource<
    { readonly revision: number; readonly forceRefresh: boolean },
    BootstrapFact
  >({
    keyOf: ({ revision, forceRefresh }) => JSON.stringify(["setup-window", revision, forceRefresh]),
    read: ({ forceRefresh }, signal) => port.readBootstrap(signal, { forceRefresh }),
    classify: () => "ready",
  });
  function connectionResource<Input>(
    read: (input: Input, signal: AbortSignal) => Promise<ConnectionCheck>,
  ) {
    return createQueryResource<
      { readonly revision: number; readonly input: Input },
      ConnectionCheck
    >({
      keyOf: ({ revision }) => JSON.stringify(["setup-connectivity", revision]),
      read: ({ input }, signal) => read(input, signal),
      classify: () => "ready",
    });
  }
  const database = connectionResource(port.checkDatabase);
  const source = connectionResource(port.checkSource);
  const write = createCommandResource(
    async (request: { readonly requestKey: string; readonly input: SetupSubmission }, signal) => {
      const receipt = await port.initialize(request, signal);
      if (receipt.requestKey !== request.requestKey || receipt.status === "not-found")
        throw new AppError(AppErrorKind.SERVER, "Unconfirmed initialization receipt", {
          status: 502,
          code: "initialization_receipt_mismatch",
        });
      return receipt;
    },
  );
  const idle = Object.freeze({ status: "idle" } as const);
  let initialization: InitializationState = idle;
  let generation = 0,
    revision = 0,
    active = false,
    disposed = false;
  const state = new StateStore<InitializationSnapshot>({
    bootstrap: bootstrap.getSnapshot(),
    databaseCheck: database.getSnapshot(),
    sourceCheck: source.getSnapshot(),
    initialization,
  });
  const publish = () => {
    if (disposed) return;
    const previous = state.getSnapshot();
    const next = {
      bootstrap: bootstrap.getSnapshot(),
      databaseCheck: database.getSnapshot(),
      sourceCheck: source.getSnapshot(),
      initialization,
    };
    if (
      previous.bootstrap === next.bootstrap &&
      previous.databaseCheck === next.databaseCheck &&
      previous.sourceCheck === next.sourceCheck &&
      previous.initialization === next.initialization
    )
      return;
    state.set(Object.freeze(next));
  };
  const subscriptions = [
    bootstrap.subscribe(publish),
    database.subscribe(publish),
    source.subscribe(publish),
  ];
  const setInitialization = (next: InitializationState) => {
    initialization = Object.freeze(next);
    publish();
  };
  const assertOpen = () => {
    if (disposed) throw new AppError(AppErrorKind.CANCELLED, "Setup owner disposed");
  };
  const assertObservationAllowed = () => {
    assertOpen();
    if (
      active ||
      ["submitting", "checking", "pending", "result-unknown", "ready"].includes(
        initialization.status,
      )
    )
      throw new AppError(
        AppErrorKind.DUPLICATE,
        "Initialization requires completion or investigation",
      );
  };
  const assertMutable = () => {
    assertObservationAllowed();
    if (initialization.status === "closed")
      throw new AppError(AppErrorKind.FORBIDDEN, "Setup window was authoritatively closed");
  };
  const setupAvailable = () => {
    const current = bootstrap.getSnapshot();
    return current.status === "ready" && !current.data.initialized && current.data.setupAvailable;
  };
  const assertWindow = () => {
    if (!setupAvailable())
      throw new AppError(AppErrorKind.FORBIDDEN, "Setup window not confirmed open");
  };
  const assertConnectionIdle = (snapshot: QuerySnapshot<ConnectionCheck>) => {
    if (snapshot.status === "loading" || snapshot.status === "refreshing")
      throw new AppError(AppErrorKind.DUPLICATE, "Connection check already in progress");
  };
  const ensureCurrent = (ticket: number) => {
    if (disposed || ticket !== generation)
      throw new AppError(AppErrorKind.CANCELLED, "Setup observation superseded");
  };
  const restore = (forceRefresh = false) => bootstrap.load({ revision: ++revision, forceRefresh });
  const inspectResource = createQueryResource<string, InitializationObservation>({
    keyOf: (key) => JSON.stringify(["setup-operation", key]),
    read: port.readInitialization,
    classify: () => "ready",
  });
  const accept = async (receipt: InitializationObservation, requestKey: string, ticket: number) => {
    ensureCurrent(ticket);
    if (receipt.requestKey !== requestKey)
      throw new AppError(AppErrorKind.PROTOCOL, "Unconfirmed initialization receipt", {
        code: "initialization_receipt_mismatch",
      });
    if (receipt.status === "completed") {
      const fact = await restore(true);
      ensureCurrent(ticket);
      if (!fact.initialized)
        throw new AppError(AppErrorKind.PROTOCOL, "Initialization not yet confirmed", {
          code: "initialization_confirmation_pending",
        });
      setInitialization({ status: "ready", requestKey, operationId: receipt.operationId });
    } else if (receipt.status === "pending")
      setInitialization({ status: "pending", requestKey, operationId: receipt.operationId });
    else if (receipt.status === "rejected")
      setInitialization(
        receipt.reason === "setup-closed"
          ? { status: "closed" }
          : { status: "rejected", requestKey, reason: receipt.reason },
      );
    else setInitialization({ status: "result-unknown", requestKey });
    return initialization;
  };
  return Object.freeze({
    getSnapshot: state.getSnapshot,
    subscribe: state.subscribe,
    async restore(forceRefresh = false) {
      // A server-closed receipt is terminal for writes, but a read-only refresh
      // remains available to reconcile a bootstrap snapshot that may be stale.
      assertObservationAllowed();
      return restore(forceRefresh);
    },
    async checkDatabase(input: SetupStorageInput) {
      assertMutable();
      assertWindow();
      assertConnectionIdle(database.getSnapshot());
      return database.load({ revision: ++revision, input });
    },
    async checkSource(input: SetupSourceInput) {
      assertMutable();
      assertWindow();
      assertConnectionIdle(source.getSnapshot());
      return source.load({ revision: ++revision, input });
    },
    invalidateChecks() {
      assertOpen();
      database.reset();
      source.reset();
    },
    async initialize(input: SetupSubmission) {
      assertMutable();
      assertWindow();
      const requestKey = newRequestKey();
      if (!requestKey.trim())
        throw new AppError(AppErrorKind.PROTOCOL, "Empty initialization request identity");
      const ticket = ++generation;
      active = true;
      write.reset();
      setInitialization({ status: "submitting", requestKey });
      try {
        const fact = await restore(true);
        ensureCurrent(ticket);
        if (fact.initialized || !fact.setupAvailable) {
          setInitialization({ status: "closed" });
          throw new AppError(AppErrorKind.FORBIDDEN, "Setup window closed");
        }
        const receipt = await write.run({ requestKey, input });
        ensureCurrent(ticket);
        setInitialization({ status: "checking", requestKey });
        return await accept(receipt, requestKey, ticket);
      } catch (cause) {
        if (ticket === generation && initialization.status !== "closed") {
          const command = write.getSnapshot();
          if (
            command.status === "success" ||
            command.status === "result-unknown" ||
            command.status === "pending"
          )
            setInitialization({ status: "result-unknown", requestKey });
          else {
            const error = AppError.fromUnknown(cause);
            setInitialization({
              status: command.status === "conflict" ? "conflict" : "error",
              requestKey,
              error: new AppError(error.kind, "Initialization request failed", {
                status: error.status,
                code: error.code,
              }),
            });
          }
        }
        throw cause;
      } finally {
        active = false;
      }
    },
    async inspect() {
      assertOpen();
      if (active) throw new AppError(AppErrorKind.DUPLICATE, "Initialization observation pending");
      if (!(initialization.status === "pending" || initialization.status === "result-unknown"))
        throw new AppError(AppErrorKind.FORBIDDEN, "No unconfirmed initialization request");
      const requestKey = initialization.requestKey,
        ticket = ++generation;
      active = true;
      setInitialization({ status: "checking", requestKey });
      try {
        return await accept(await inspectResource.load(requestKey), requestKey, ticket);
      } catch (cause) {
        if (ticket === generation) setInitialization({ status: "result-unknown", requestKey });
        throw cause;
      } finally {
        active = false;
      }
    },
    cancel() {
      if (disposed) return;
      generation++;
      bootstrap.cancel();
      database.cancel();
      source.cancel();
      inspectResource.cancel();
      write.cancel();
      if (initialization.status === "submitting" || initialization.status === "checking")
        setInitialization(
          write.getSnapshot().status === "idle"
            ? idle
            : { status: "result-unknown", requestKey: initialization.requestKey },
        );
    },
    dispose() {
      if (disposed) return;
      generation++;
      disposed = true;
      subscriptions.forEach((unsubscribe) => unsubscribe());
      bootstrap.dispose();
      database.dispose();
      source.dispose();
      inspectResource.dispose();
      write.dispose();
      initialization = idle;
      state.set(
        Object.freeze<InitializationSnapshot>({
          bootstrap: { status: "idle" },
          databaseCheck: { status: "idle" },
          sourceCheck: { status: "idle" },
          initialization,
        }),
      );
      state.complete();
    },
  });
}
