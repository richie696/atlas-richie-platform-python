import { AppError, AppErrorKind, StateStore } from "@richie696/react-framework";
import {
  createOwnedQueryResource,
  type QueryAccessObserver,
} from "../../../shared/state/ownedQueryResource";
import { createCommandResource, type CommandSnapshot } from "../../../shared/state/commandResource";
import type { SourceRegistrationPort } from "../api/sourceRegistrationPort";
import {
  prepareSourceMutation,
  sourceRecordKey,
  sourceCheckInput,
  sourceOutcomeExpectation,
  validSourceRegistry,
  validSourceCheck,
  validSourceObservation,
  type RegisteredSource,
  type SourceRegistrationDraft,
  type SourceCheckInput,
  type SourceCheckResult,
  type SourceOutcomeExpectation,
  type SourceOperationObservation,
  type SourceMutation,
} from "../model/sourceRegistration";
/** Published state excludes all credential branches, including reference identifiers and original error text. */
export function createSourceRegistrationWorkflow(
  port: SourceRegistrationPort,
  access: QueryAccessObserver,
  newRequestKey: () => string,
  options: { readonly timeoutMs?: number } = {},
) {
  const ownerKey = access.read().ownerKey;
  let disposed = false,
    active = false,
    inspecting = false,
    checkGeneration = 0,
    expected: SourceOutcomeExpectation | null = null,
    confirmed: CommandSnapshot<RegisteredSource> | null = null;
  const allowed = () => !disposed && access.read().allowed && access.read().ownerKey === ownerKey;
  const assertOwner = () => {
    if (!allowed())
      throw new AppError(AppErrorKind.FORBIDDEN, "Source management access unavailable", {
        status: 403,
      });
  };
  const invalidReceipt = () =>
    new AppError(AppErrorKind.SERVER, "Unconfirmed source operation", {
      status: 502,
      code: "source_receipt_invalid",
    });
  const redact = (cause: unknown) => {
    const error = AppError.fromUnknown(cause);
    return new AppError(error.kind, "Source operation failed", { status: error.status });
  };
  function rejected(value: SourceOperationObservation): AppError {
    const status =
      value.status !== "rejected"
        ? 502
        : value.reason === "conflict"
          ? 409
          : value.reason === "not-found"
            ? 404
            : value.reason === "unavailable"
              ? 503
              : 422;
    return new AppError(AppErrorKind.PROTOCOL, "Source operation rejected", { status });
  }
  const registry = createOwnedQueryResource<
    null,
    Awaited<ReturnType<SourceRegistrationPort["readSources"]>>
  >(access, {
    keyOf: () => "sources",
    timeoutMs: options.timeoutMs,
    async read(_query, signal) {
      assertOwner();
      try {
        const value = await port.readSources(signal);
        if (!validSourceRegistry(value)) throw invalidReceipt();
        assertOwner();
        return value;
      } catch (cause) {
        throw redact(cause);
      }
    },
    classify: (value) => (value.items.length ? "ready" : "empty"),
  });
  const check = createOwnedQueryResource<
    { readonly generation: number; readonly input: SourceCheckInput },
    SourceCheckResult
  >(access, {
    keyOf: (query) => String(query.generation),
    timeoutMs: options.timeoutMs,
    async read(query, signal) {
      assertOwner();
      try {
        const value = await port.checkSource(query.input, signal);
        if (!validSourceCheck(value)) throw invalidReceipt();
        assertOwner();
        return value;
      } catch (cause) {
        throw redact(cause);
      }
    },
    classify: (value) => (value.status === "reachable" ? "ready" : "partial"),
  });
  const command = createCommandResource<SourceMutation, RegisteredSource>(
    async (mutation, signal) => {
      assertOwner();
      const expectation = expected;
      if (!expectation) throw invalidReceipt();
      const value = await port.mutateSource(mutation, signal);
      assertOwner();
      if (signal.aborted || expected !== expectation) throw invalidReceipt();
      if (!validSourceObservation(value, expectation)) throw invalidReceipt();
      if (value.status === "rejected") throw rejected(value);
      if (value.status !== "completed") throw invalidReceipt();
      return value.record;
    },
    options,
  );
  const inspection = createOwnedQueryResource<SourceOutcomeExpectation, SourceOperationObservation>(
    access,
    {
      keyOf: (value) => value.requestKey,
      timeoutMs: options.timeoutMs,
      async read(expectation, signal) {
        assertOwner();
        try {
          const value = await port.readSourceOperation(expectation.requestKey, signal);
          assertOwner();
          if (!validSourceObservation(value, expectation)) throw invalidReceipt();
          return value;
        } catch (cause) {
          throw redact(cause);
        }
      },
      classify: () => "ready",
    },
  );
  const idle = Object.freeze({ status: "idle" } as const);
  const denied = Object.freeze({
    status: "denied" as const,
    key: "",
    error: new AppError(AppErrorKind.FORBIDDEN, "Source management access unavailable", {
      status: 403,
    }),
  });
  function snapshot() {
    const authorized = allowed(),
      raw = confirmed ?? command.getSnapshot();
    const safe: CommandSnapshot<RegisteredSource> =
      "error" in raw ? { ...raw, error: redact(raw.error) } : raw;
    return {
      authorized,
      registry: authorized ? registry.getSnapshot() : denied,
      check: authorized ? check.getSnapshot() : denied,
      command: authorized ? safe : idle,
      operation:
        authorized && expected
          ? { requestKey: expected.requestKey, kind: expected.kind, sourceId: expected.sourceId }
          : null,
      inspecting: authorized && inspecting,
    };
  }
  const state = new StateStore(snapshot()),
    publish = () => {
      if (!disposed) state.set(snapshot());
    };
  const stops = [
    registry.subscribe(publish),
    check.subscribe(publish),
    command.subscribe(publish),
    access.subscribe(() => {
      if (!allowed()) {
        checkGeneration++;
        check.reset();
        command.cancel();
        inspection.reset();
        confirmed = null;
        if (access.read().ownerKey !== ownerKey) expected = null;
        if (!["pending", "result-unknown"].includes(command.getSnapshot().status)) {
          expected = null;
          command.reset();
        }
      }
      publish();
    }),
  ];
  function assertMutable() {
    assertOwner();
    if (
      active ||
      inspecting ||
      ["pending", "result-unknown"].includes(command.getSnapshot().status)
    )
      throw new AppError(AppErrorKind.DUPLICATE, "Source operation requires investigation");
  }
  function prepare(draft: SourceRegistrationDraft, record: RegisteredSource | null) {
    const value = prepareSourceMutation(draft, record);
    if (!value)
      throw new AppError(AppErrorKind.PROTOCOL, "Invalid source configuration", { status: 422 });
    const current = registry.getSnapshot();
    if (current.status !== "ready" && current.status !== "empty")
      throw new AppError(AppErrorKind.PROTOCOL, "Source registry must be refreshed", {
        status: 409,
      });
    if (
      record &&
      !current.data.items.some(
        (item) =>
          item.id === record.id &&
          item.revision === record.revision &&
          sourceRecordKey(item) === sourceRecordKey(record),
      )
    )
      throw new AppError(AppErrorKind.PROTOCOL, "Source revision changed", { status: 409 });
    return value;
  }
  const refresh = () => void registry.load(null).catch(() => {});
  return Object.freeze({
    getSnapshot: state.getSnapshot,
    subscribe: state.subscribe,
    registry,
    async checkSource(draft: SourceRegistrationDraft, record: RegisteredSource | null) {
      assertMutable();
      const input = sourceCheckInput(prepare(draft, record));
      return check.load({ generation: ++checkGeneration, input });
    },
    invalidateCheck() {
      checkGeneration++;
      check.reset();
    },
    cancelCheck: check.cancel,
    async submit(
      draft: SourceRegistrationDraft,
      record: RegisteredSource | null,
    ): Promise<RegisteredSource> {
      assertMutable();
      const input = prepare(draft, record),
        requestKey = newRequestKey();
      if (!requestKey.trim() || requestKey === expected?.requestKey)
        throw new AppError(AppErrorKind.PROTOCOL, "Invalid new source operation identity", {
          status: 422,
        });
      const mutation: SourceMutation = { ...input, requestKey };
      expected = sourceOutcomeExpectation(mutation, record);
      confirmed = null;
      active = true;
      check.reset();
      try {
        const result = await command.run(mutation);
        assertOwner();
        refresh();
        return result;
      } catch (cause) {
        throw redact(cause);
      } finally {
        active = false;
        publish();
      }
    },
    async inspect(): Promise<SourceOperationObservation> {
      assertOwner();
      if (active || inspecting || !expected || command.getSnapshot().status !== "result-unknown")
        throw new AppError(AppErrorKind.DUPLICATE, "No unresolved source operation");
      const expectation = expected;
      inspecting = true;
      publish();
      try {
        const value = await inspection.load(expectation);
        assertOwner();
        if (expected !== expectation) throw invalidReceipt();
        if (value.status === "completed") {
          confirmed = { status: "success", result: value.record };
          command.reset();
          refresh();
        } else if (value.status === "rejected") {
          const error = rejected(value);
          confirmed = { status: error.status === 409 ? "conflict" : "error", error };
          command.reset();
        }
        return value;
      } catch (cause) {
        throw redact(cause);
      } finally {
        inspecting = false;
        publish();
      }
    },
    dispose() {
      if (disposed) return;
      stops.forEach((stop) => stop());
      disposed = true;
      expected = null;
      confirmed = null;
      command.dispose();
      inspection.dispose();
      check.dispose();
      registry.dispose();
      state.set(snapshot());
      state.complete();
    },
  });
}
