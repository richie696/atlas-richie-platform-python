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
  sourceDeletionExpectation,
  validSourceRegistry,
  validSourceCheck,
  validSourceObservation,
  validRegisteredSource,
  type RegisteredSource,
  type SourceRegistrationDraft,
  type SourceCheckInput,
  type SourceCheckResult,
  type SourceOutcomeExpectation,
  type SourceOperationObservation,
  type SourceCommandResult,
  type SourceMutation,
  type SourceMutationInput,
} from "../model/sourceRegistration";

function isDeletedSource(
  value: SourceCommandResult,
  sourceId: string,
): value is { readonly deletedSourceId: string } {
  return "deletedSourceId" in value && value.deletedSourceId === sourceId;
}
/** Published state excludes all credential branches, including reference identifiers and original error text. */
export function createSourceRegistrationWorkflow(
  port: SourceRegistrationPort,
  access: QueryAccessObserver,
  newRequestKey: () => string,
  options: { readonly timeoutMs?: number; readonly clock?: () => number } = {},
) {
  const clock = options.clock ?? (() => globalThis.performance.now());
  const ownerKey = access.read().ownerKey;
  let disposed = false,
    active = false,
    inspecting = false,
    checkGeneration = 0,
    checkRetryUntilMs = 0,
    commandRetryUntilMs = 0,
    inspectionRetryUntilMs = 0,
    expected: SourceOutcomeExpectation | null = null,
    confirmed: CommandSnapshot<SourceCommandResult> | null = null;
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
  const cooldownError = (deadline: number, message: string) => {
    const retryAfterMs = Math.ceil(deadline - clock());
    return Number.isSafeInteger(retryAfterMs) && retryAfterMs > 0
      ? new AppError(AppErrorKind.RATE_LIMITED, message, {
          status: 429,
          retryAfterMs,
        })
      : undefined;
  };
  const extendRetryDeadline = (deadline: number, cause: unknown) => {
    const error = AppError.fromUnknown(cause),
      now = clock();
    return error.kind === AppErrorKind.RATE_LIMITED &&
      error.retryAfterMs !== undefined &&
      Number.isSafeInteger(error.retryAfterMs) &&
      error.retryAfterMs > 0 &&
      Number.isFinite(now)
      ? Math.max(deadline, now + error.retryAfterMs)
      : deadline;
  };
  const redact = (cause: unknown) => {
    const error = AppError.fromUnknown(cause);
    const safeCode =
      error.code === "source_in_use" ||
      error.code === "conflict" ||
      error.code === "not-found" ||
      error.code === "unavailable"
        ? error.code
        : undefined;
    return new AppError(error.kind, "Source operation failed", {
      status: error.status,
      retryAfterMs: error.retryAfterMs,
      code: safeCode,
    });
  };
  function rejected(value: SourceOperationObservation): AppError {
    if (value.status !== "rejected") return invalidReceipt();
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
    return new AppError(AppErrorKind.PROTOCOL, "Source operation rejected", {
      status,
      code: value.reason,
    });
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
  const command = createCommandResource<SourceMutation, SourceCommandResult>(
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
      if (expectation.kind === "delete") {
        if (!("deletedSourceId" in value)) throw invalidReceipt();
        return { deletedSourceId: value.deletedSourceId };
      }
      if (!("record" in value)) throw invalidReceipt();
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
    const inspectionState = inspection.getSnapshot();
    const safe: CommandSnapshot<SourceCommandResult> =
      "error" in raw ? { ...raw, error: redact(raw.error) } : raw;
    return {
      authorized,
      registry: authorized ? registry.getSnapshot() : denied,
      check: authorized ? check.getSnapshot() : denied,
      checkRetryUntilMs: authorized ? checkRetryUntilMs : 0,
      command: authorized ? safe : idle,
      operation:
        authorized && expected
          ? { requestKey: expected.requestKey, kind: expected.kind, sourceId: expected.sourceId }
          : null,
      inspecting: authorized && inspecting,
      inspectionError:
        authorized && (inspectionState.status === "error" || inspectionState.status === "stale")
          ? redact(inspectionState.error)
          : undefined,
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
    inspection.subscribe(publish),
    access.subscribe(() => {
      if (!allowed()) {
        checkGeneration++;
        check.reset();
        checkRetryUntilMs = 0;
        commandRetryUntilMs = 0;
        inspectionRetryUntilMs = 0;
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
  function prepare(
    draft: SourceRegistrationDraft,
    record: RegisteredSource | null,
  ): Extract<SourceMutationInput, { readonly kind: "register" | "update" }> {
    const value = prepareSourceMutation(draft, record);
    if (!value || value.kind === "delete")
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
      const blocked = cooldownError(checkRetryUntilMs, "Source check cooldown is active");
      if (blocked) throw blocked;
      if (checkRetryUntilMs !== 0) {
        checkRetryUntilMs = 0;
        publish();
      }
      try {
        const result = await check.load({ generation: ++checkGeneration, input });
        checkRetryUntilMs = 0;
        publish();
        return result;
      } catch (cause) {
        checkRetryUntilMs = extendRetryDeadline(checkRetryUntilMs, cause);
        if (checkRetryUntilMs > 0) publish();
        throw cause;
      }
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
      const blocked = cooldownError(commandRetryUntilMs, "Source save cooldown is active");
      if (blocked) throw blocked;
      commandRetryUntilMs = 0;
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
        if (!("id" in result) || result.id !== (record?.id ?? result.id)) throw invalidReceipt();
        return result;
      } catch (cause) {
        commandRetryUntilMs = extendRetryDeadline(commandRetryUntilMs, cause);
        throw redact(cause);
      } finally {
        active = false;
        publish();
      }
    },
    async deleteSource(record: RegisteredSource): Promise<void> {
      assertMutable();
      const current = registry.getSnapshot();
      if (
        !validRegisteredSource(record) ||
        (current.status !== "ready" && current.status !== "empty") ||
        !current.data.items.some(
          (item) => item.id === record.id && item.revision === record.revision,
        )
      )
        throw new AppError(AppErrorKind.PROTOCOL, "Source revision changed", {
          status: 409,
        });
      const requestKey = newRequestKey();
      if (!requestKey.trim() || requestKey === expected?.requestKey)
        throw new AppError(AppErrorKind.PROTOCOL, "Invalid new source operation identity", {
          status: 422,
        });
      const mutation: SourceMutation = {
        kind: "delete",
        requestKey,
        sourceId: record.id,
        expectedRevision: record.revision,
      };
      expected = sourceDeletionExpectation(requestKey, record);
      confirmed = null;
      active = true;
      check.reset();
      try {
        const result = await command.run(mutation);
        assertOwner();
        if (!isDeletedSource(result, record.id)) throw invalidReceipt();
        refresh();
      } catch (cause) {
        commandRetryUntilMs = extendRetryDeadline(commandRetryUntilMs, cause);
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
      const blocked = cooldownError(
        inspectionRetryUntilMs,
        "Source operation inspection cooldown is active",
      );
      if (blocked) throw blocked;
      inspectionRetryUntilMs = 0;
      const expectation = expected;
      inspecting = true;
      publish();
      try {
        const value = await inspection.load(expectation);
        assertOwner();
        if (expected !== expectation) throw invalidReceipt();
        if (value.status === "completed") {
          let result: SourceCommandResult;
          if (expectation.kind === "delete") {
            if (!("deletedSourceId" in value)) throw invalidReceipt();
            result = { deletedSourceId: value.deletedSourceId };
          } else {
            if (!("record" in value)) throw invalidReceipt();
            result = value.record;
          }
          confirmed = { status: "success", result };
          command.reset();
          refresh();
        } else if (value.status === "rejected") {
          const error = rejected(value);
          confirmed = { status: error.status === 409 ? "conflict" : "error", error };
          command.reset();
        }
        return value;
      } catch (cause) {
        inspectionRetryUntilMs = extendRetryDeadline(inspectionRetryUntilMs, cause);
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
