import { StateStore, AppError, AppErrorKind } from "@richie696/react-framework";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import { AstryxProvider } from "../../../src/app/providers/AstryxProvider";
import {
  createSourceRegistrationWorkflow,
  SourceRegistryPanel,
  type RegisteredSource,
  type SourceMutation,
  type SourceOperationObservation,
  type SourceCheckResult,
} from "../../../src/features/system/sources";
const NOW = Date.parse("2026-10-07T12:00:00Z");
const INITIAL: RegisteredSource = {
  id: "source-one",
  revision: "source-revision-one",
  name: "Internal config",
  provider: "nacos",
  endpoint: "https://config.test",
  namespace: "namespace-one",
  authenticationMode: "direct",
  credentialConfigured: true,
};
/** Isolated test Ports; secrets are not recorded in diagnostic snapshots. Persistence assertions still await real HTTP/Python acceptance. */
export function createSourceRegistrationTopology() {
  const access = new StateStore({ ownerKey: "source-probe-session", allowed: true }),
    counts = new StateStore({
      reads: 0,
      writes: 0,
      checks: 0,
      lookups: 0,
      aborts: 0,
      keep: false,
      lastMutation: null as null | {
        kind: "register" | "update";
        name: string;
        provider: "nacos" | "consul";
        endpoint: string;
        location: string;
        authenticationMode: string;
      },
    });
  let records: readonly RegisteredSource[] = [INITIAL],
    key = 0,
    revision = 1,
    fail = false,
    conflict = false,
    rateLimitNextMutation = false,
    rateLimitNextCheck = false,
    rateLimitNextLookup = false,
    held = false,
    outcomeVisible = false;
  let release: (() => void) | null = null,
    latest: SourceOperationObservation | null = null;
  const count = (field: "reads" | "writes" | "checks" | "lookups" | "aborts") =>
    counts.set({ ...counts.getSnapshot(), [field]: counts.getSnapshot()[field] + 1 });
  const checked: SourceCheckResult = {
    status: "reachable",
    checkedAtMs: NOW,
    expiresAtMs: NOW + 60_000,
    capabilities: ["read", "conditional-write"],
  };
  function apply(
    mutation: SourceMutation & { readonly kind: "register" | "update" },
  ): RegisteredSource {
    const existing =
      mutation.kind === "update" ? records.find((item) => item.id === mutation.sourceId) : null;
    const mode =
      mutation.source.authentication.mode === "keep"
        ? (existing?.authenticationMode ?? "none")
        : mutation.source.authentication.mode;
    const shared = {
      id: mutation.kind === "update" ? mutation.sourceId : `source-new-${revision}`,
      revision: `source-revision-${++revision}`,
      name: mutation.name,
      endpoint: mutation.source.endpoint,
      authenticationMode: mode,
      credentialConfigured:
        mutation.source.authentication.mode === "keep"
          ? (existing?.credentialConfigured ?? false)
          : mode !== "none",
    };
    const record: RegisteredSource =
      mutation.source.provider === "nacos"
        ? { ...shared, provider: "nacos", namespace: mutation.source.namespace }
        : { ...shared, provider: "consul", datacenter: mutation.source.datacenter };
    records = [...records.filter((item) => item.id !== record.id), record];
    return record;
  }
  const workflow = createSourceRegistrationWorkflow(
    {
      async readSources() {
        count("reads");
        return { asOfMs: NOW, items: records };
      },
      async checkSource(_input, signal) {
        count("checks");
        if (rateLimitNextCheck) {
          rateLimitNextCheck = false;
          throw new AppError(AppErrorKind.RATE_LIMITED, "PRIVATE-CHECK-RATE-LIMIT", {
            status: 429,
            retryAfterMs: 500,
          });
        }
        if (!held) return checked;
        return new Promise<SourceCheckResult>((resolve) => {
          release = () => resolve(checked);
          signal.addEventListener("abort", () => count("aborts"), { once: true });
        });
      },
      async mutateSource(mutation) {
        count("writes");
        if (rateLimitNextMutation) {
          rateLimitNextMutation = false;
          throw new AppError(AppErrorKind.RATE_LIMITED, "PRIVATE-SOURCE-RATE-LIMIT", {
            status: 429,
            retryAfterMs: 500,
          });
        }
        if (mutation.kind === "delete") {
          const current = records.find((item) => item.id === mutation.sourceId);
          latest = !current
            ? { requestKey: mutation.requestKey, status: "rejected", reason: "not-found" }
            : current.revision !== mutation.expectedRevision
              ? { requestKey: mutation.requestKey, status: "rejected", reason: "conflict" }
              : {
                  requestKey: mutation.requestKey,
                  status: "completed",
                  deletedSourceId: current.id,
                };
          if (latest.status === "completed")
            records = records.filter((item) => item.id !== mutation.sourceId);
          if (fail) throw new AppError(AppErrorKind.NETWORK, "PRIVATE-SOURCE-ERROR");
          return latest;
        }
        const source = mutation.source;
        const lastMutation = {
          kind: mutation.kind,
          name: mutation.name,
          provider: source.provider,
          endpoint: source.endpoint,
          location: source.provider === "nacos" ? source.namespace : source.datacenter,
          authenticationMode: source.authentication.mode,
        } as const;
        counts.set({
          ...counts.getSnapshot(),
          keep: mutation.source.authentication.mode === "keep",
          lastMutation,
        });
        if (conflict)
          throw new AppError(AppErrorKind.PROTOCOL, "PRIVATE-CONFLICT", { status: 409 });
        latest = { requestKey: mutation.requestKey, status: "completed", record: apply(mutation) };
        if (fail) throw new AppError(AppErrorKind.NETWORK, "PRIVATE-SOURCE-ERROR");
        return latest;
      },
      async readSourceOperation(requestKey) {
        count("lookups");
        if (rateLimitNextLookup) {
          rateLimitNextLookup = false;
          throw new AppError(AppErrorKind.RATE_LIMITED, "PRIVATE-LOOKUP-RATE-LIMIT", {
            status: 429,
            retryAfterMs: 500,
          });
        }
        return outcomeVisible && latest ? latest : { requestKey, status: "pending" };
      },
    },
    { read: access.getSnapshot, subscribe: access.subscribe },
    () => `source-probe-request-${++key}`,
  );
  return {
    workflow,
    access,
    counts,
    loseAck: () => {
      fail = true;
    },
    conflict: () => {
      conflict = true;
    },
    rateLimitMutation: () => {
      rateLimitNextMutation = true;
    },
    rateLimitCheck: () => {
      rateLimitNextCheck = true;
    },
    rateLimitLookup: () => {
      rateLimitNextLookup = true;
    },
    hold: () => {
      held = true;
    },
    release: () => release?.(),
    confirm: () => {
      outcomeVisible = true;
    },
    dispose: () => {
      workflow.dispose();
      access.complete();
      counts.complete();
    },
  };
}
export function SourceRegistrationProbe({
  topology,
}: {
  readonly topology: ReturnType<typeof createSourceRegistrationTopology>;
}) {
  const state = useExternalSnapshot(topology.workflow),
    counts = useExternalSnapshot(topology.counts);
  return (
    <AstryxProvider>
      <div data-source-controls>
        <button data-source-lost onClick={topology.loseAck}>
          Lose acknowledgement
        </button>
        <button data-source-conflict onClick={topology.conflict}>
          Conflict
        </button>
        <button data-source-rate-limit-mutation onClick={topology.rateLimitMutation}>
          Rate-limit next mutation
        </button>
        <button data-source-rate-limit onClick={topology.rateLimitCheck}>
          Rate-limit next check
        </button>
        <button data-source-rate-limit-lookup onClick={topology.rateLimitLookup}>
          Rate-limit next lookup
        </button>
        <button data-source-hold onClick={topology.hold}>
          Hold check
        </button>
        <button data-source-release onClick={topology.release}>
          Release check
        </button>
        <button data-source-confirm onClick={topology.confirm}>
          Confirm operation
        </button>
        <button
          data-source-deny
          onClick={() => topology.access.set({ ownerKey: "source-probe-session", allowed: false })}
        >
          Revoke
        </button>
        <button
          data-source-allow
          onClick={() => topology.access.set({ ownerKey: "source-probe-session", allowed: true })}
        >
          Restore access
        </button>
      </div>
      <pre data-source-summary>
        {JSON.stringify({
          authorized: state.authorized,
          registry: state.registry.status,
          check: state.check.status,
          command: state.command.status,
          operation: state.operation,
          counts,
        })}
      </pre>
      <SourceRegistryPanel workflow={topology.workflow} demoMode />
    </AstryxProvider>
  );
}
