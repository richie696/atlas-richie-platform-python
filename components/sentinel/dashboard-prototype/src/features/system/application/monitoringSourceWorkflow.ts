import { AppError, AppErrorKind, StateStore } from "@richie696/react-framework";
import type { QueryAccessObserver } from "../../../shared/state/ownedQueryResource";
import type { MonitoringSourcePort } from "../api/monitoringSourcePort";
import type {
  MonitoringSourceCandidate,
  MonitoringSourceCheckReceipt,
  MonitoringSourceMutation,
  MonitoringSourceOperation,
  MonitoringSourceWorkflowSnapshot,
  MonitoringCredentialMaterial,
} from "../model/monitoringSource";

type MutationWithoutRequestKey = MonitoringSourceMutation extends infer T
  ? T extends MonitoringSourceMutation
    ? Omit<T, "requestKey">
    : never
  : never;

/** Owns safe reads and bounded source commands; credential values exist only in method arguments. */
export function createMonitoringSourceWorkflow(
  port: MonitoringSourcePort,
  access: QueryAccessObserver,
  newRequestKey: () => string,
) {
  const ownerKey = access.read().ownerKey;
  let disposed = false;
  let controller: AbortController | null = null;
  const allowed = () => !disposed && access.read().allowed && access.read().ownerKey === ownerKey;
  const initial = (): MonitoringSourceWorkflowSnapshot => ({
    authorized: allowed(),
    loading: false,
    items: [],
    error: null,
    busyRequestKey: null,
    unresolvedRequestKey: null,
    lastOperation: null,
  });
  const state = new StateStore(initial());
  const publish = (patch: Partial<MonitoringSourceWorkflowSnapshot>) => {
    if (!disposed) state.set({ ...state.getSnapshot(), authorized: allowed(), ...patch });
  };
  const assertAllowed = () => {
    if (!allowed())
      throw new AppError(AppErrorKind.FORBIDDEN, "Monitoring-source access unavailable", {
        status: 403,
      });
  };
  const currentController = () => {
    controller?.abort();
    controller = new AbortController();
    return controller;
  };

  async function refresh() {
    assertAllowed();
    const active = currentController();
    publish({ loading: true, error: null });
    try {
      const value = await port.readSources(active.signal);
      assertAllowed();
      if (active.signal.aborted || !Array.isArray(value.items) || value.items.length > 500)
        throw new Error("Invalid monitoring-source directory");
      publish({ items: value.items, loading: false, error: null });
      return value;
    } catch {
      publish({ loading: false, error: "read_failed" });
      throw new AppError(AppErrorKind.SERVER, "Monitoring-source directory unavailable");
    }
  }

  async function check(
    source: MonitoringSourceCandidate,
    credentials: MonitoringCredentialMaterial,
  ): Promise<MonitoringSourceCheckReceipt> {
    assertAllowed();
    const active = currentController();
    try {
      const receipt = await port.checkCandidate(source, credentials, active.signal);
      assertAllowed();
      if (
        active.signal.aborted ||
        receipt.sourceId !== source.sourceId ||
        receipt.sourceRevision !== source.revision
      )
        throw new Error("Candidate receipt mismatch");
      return receipt;
    } catch {
      throw new AppError(AppErrorKind.SERVER, "Monitoring-source check failed");
    }
  }

  async function readSource(sourceId: string) {
    assertAllowed();
    const active = currentController();
    const source = await port.readSource(sourceId, active.signal);
    assertAllowed();
    if (active.signal.aborted || source.id !== sourceId)
      throw new AppError(AppErrorKind.PROTOCOL, "Monitoring-source detail mismatch");
    return source;
  }

  async function mutate(input: MutationWithoutRequestKey): Promise<MonitoringSourceOperation> {
    assertAllowed();
    if (state.getSnapshot().busyRequestKey || state.getSnapshot().unresolvedRequestKey) {
      throw new AppError(AppErrorKind.PROTOCOL, "Monitoring-source command already pending");
    }
    const requestKey = newRequestKey();
    const command = { ...input, requestKey } as MonitoringSourceMutation;
    const active = currentController();
    publish({ busyRequestKey: requestKey, error: null, lastOperation: null });
    let operation: MonitoringSourceOperation | null = null;
    try {
      operation = await port.mutate(command, active.signal);
      assertAllowed();
      if (operation.requestKey !== requestKey || operation.status === "not_found")
        throw new Error("Invalid command acknowledgement");
    } catch {
      if (!allowed())
        throw new AppError(AppErrorKind.FORBIDDEN, "Monitoring-source access expired");
      // A dispatched command may have committed even if its response was lost. Only read its
      // original operation key; never replay the mutation under a new key automatically.
      const readController = currentController();
      try {
        const observed = await port.readOperation(requestKey, readController.signal);
        assertAllowed();
        if (observed.requestKey === requestKey && observed.status !== "not_found")
          operation = observed;
      } catch {
        // Intentionally retain the unknown outcome for explicit operator review.
      }
      if (operation === null) {
        publish({
          busyRequestKey: null,
          unresolvedRequestKey: requestKey,
          error: "unknown_outcome",
        });
        throw new AppError(AppErrorKind.TIMEOUT, "Monitoring-source command outcome unknown", {
          code: "monitoring_source_outcome_unknown",
        });
      }
    }
    publish({ busyRequestKey: null, lastOperation: operation, error: null });
    if (operation.status === "completed") await refresh();
    else publish({ error: "write_failed" });
    return operation;
  }

  async function inspect(requestKey: string): Promise<MonitoringSourceOperation> {
    assertAllowed();
    const active = currentController();
    const operation = await port.readOperation(requestKey, active.signal);
    assertAllowed();
    if (operation.requestKey !== requestKey)
      throw new AppError(AppErrorKind.PROTOCOL, "Invalid operation receipt");
    publish({
      busyRequestKey: null,
      unresolvedRequestKey: operation.status === "not_found" ? requestKey : null,
      lastOperation: operation,
      error: operation.status === "not_found" ? "unknown_outcome" : null,
    });
    if (operation.status === "completed") await refresh();
    return operation;
  }

  const stopAccess = access.subscribe(() => {
    if (!allowed()) {
      controller?.abort();
      controller = null;
      state.set(initial());
    }
  });
  return Object.freeze({
    getSnapshot: () => state.getSnapshot(),
    subscribe: state.subscribe,
    refresh,
    check,
    readSource,
    mutate,
    inspect,
    newRequestKey,
    dispose() {
      if (disposed) return;
      disposed = true;
      controller?.abort();
      stopAccess();
    },
  });
}
