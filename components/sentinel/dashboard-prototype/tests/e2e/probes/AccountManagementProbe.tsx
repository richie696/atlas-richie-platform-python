import { useMemo, useState } from "react";
import { AppError, AppErrorKind, StateStore } from "@richie696/react-framework";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import { AstryxProvider } from "../../../src/app/providers/AstryxProvider";
import {
  createAccountManagementWorkflow,
  AccountsPage,
  RoleManagementPage,
  type AccountRecord,
  type AccountListQuery,
  type AccountMutation,
  type AccountOperationObservation,
} from "../../../src/features/identity/management";
import type {
  SessionIdentity,
  ControlPlaneAccessState,
} from "../../../src/features/identity/model/controlPlaneAccess";

const owner: SessionIdentity = {
  accountId: "owner",
  username: "operator",
  roleId: "admin",
  capabilities: ["metrics:view", "rules:write"],
  sessionEpoch: "management-session",
};
const records: readonly AccountRecord[] = [
  {
    id: "builtin",
    username: "root",
    roleId: "admin",
    status: "active",
    builtIn: true,
    lastActiveAdmin: false,
    lastLoginAt: null,
    revision: "1",
  },
  {
    id: "one",
    username: "reader-one",
    roleId: "view",
    status: "active",
    builtIn: false,
    lastActiveAdmin: false,
    lastLoginAt: null,
    revision: "1",
  },
  {
    id: "two",
    username: "reader-two",
    roleId: "view",
    status: "active",
    builtIn: false,
    lastActiveAdmin: false,
    lastLoginAt: null,
    revision: "1",
  },
  {
    id: "last-admin",
    username: "sole-admin",
    roleId: "admin",
    status: "active",
    builtIn: false,
    lastActiveAdmin: true,
    lastLoginAt: null,
    revision: "1",
  },
];
/** The test effect owner holds transport counters and records; no mutable control object enters component props. */
function createManagementTopology() {
  const access = new StateStore<ControlPlaneAccessState>({
    phase: "resolved",
    facts: { kind: "authenticated", identity: owner },
  });
  const control = {
    records: [...records],
    mode: "success" as "success" | "conflict" | "duplicate" | "timeout",
    key: 0,
    writes: 0,
    reads: 0,
    lookups: 0,
    hold: false,
    releases: [] as (() => void)[],
    observations: new Map<string, AccountOperationObservation>(),
  };
  const workflow = createAccountManagementWorkflow(
    {
      listAccounts: async (input, signal) => {
        signal.throwIfAborted();
        control.reads++;
        const items = control.records.filter(
          (record) =>
            (!input.search || record.username.includes(input.search)) &&
            (!input.status || record.status === input.status),
        );
        return {
          items: items.slice((input.page - 1) * input.pageSize, input.page * input.pageSize),
          page: input.page,
          pageSize: input.pageSize,
          total: items.length,
        };
      },
      readAccount: async (id, signal) => {
        signal.throwIfAborted();
        return control.records.find((record) => record.id === id) ?? null;
      },
      mutateAccount: async (input: AccountMutation, signal) => {
        control.writes++;
        if (control.hold) await new Promise<void>((resolve) => control.releases.push(resolve));
        signal.throwIfAborted();
        if (control.mode === "duplicate" || control.mode === "conflict")
          return {
            status: "rejected",
            requestKey: input.requestKey,
            reason: control.mode === "duplicate" ? "username_taken" : "conflict",
          };
        const existing =
          input.kind === "create"
            ? undefined
            : control.records.find((record) => record.id === input.accountId);
        const record: AccountRecord =
          input.kind === "create"
            ? {
                id: `server-${control.writes}`,
                username: input.input.username,
                roleId: input.input.roleId,
                status: "active",
                builtIn: false,
                lastActiveAdmin: false,
                lastLoginAt: null,
                revision: "1",
              }
            : {
                ...existing!,
                revision: String(Number(existing!.revision) + 1),
                ...(input.kind === "role"
                  ? { roleId: input.roleId }
                  : input.kind === "status"
                    ? { status: input.status }
                    : input.kind === "delete"
                      ? { status: "disabled" as const }
                      : {}),
              };
        control.records =
          input.kind === "create"
            ? [...control.records, record]
            : control.records.map((previous) => (previous.id === record.id ? record : previous));
        const receipt = {
          status: "completed" as const,
          requestKey: input.requestKey,
          account: record,
        };
        control.observations.set(input.requestKey, receipt);
        if (control.mode === "timeout")
          throw new AppError(AppErrorKind.TIMEOUT, "PRIVATE-ACCOUNT-PASSWORD");
        return receipt;
      },
      readAccountOperation: async (requestKey, signal) => {
        signal.throwIfAborted();
        control.lookups++;
        return control.observations.get(requestKey) ?? { status: "not-found", requestKey };
      },
    },
    owner,
    {
      read: access.getSnapshot,
      subscribe: access.subscribe,
      revalidateAccess: async () => undefined,
    },
    () => `management-${++control.key}`,
  );
  return Object.freeze({
    access,
    workflow,
    readCounts: () => ({
      writes: control.writes,
      reads: control.reads,
      lookups: control.lookups,
      roles: control.records.map((record) => ({ id: record.id, roleId: record.roleId })),
      records: control.records.length,
    }),
    setMode: (mode: typeof control.mode) => {
      control.mode = mode;
    },
    hold: () => {
      control.hold = true;
    },
    release: () => {
      control.hold = false;
      control.releases.splice(0).forEach((resolve) => resolve());
    },
    changeRevision: (accountId: string) => {
      control.records = control.records.map((record) =>
        record.id === accountId
          ? { ...record, revision: String(Number(record.revision) + 1) }
          : record,
      );
    },
  });
}
/** Test-only port topology; actual page/workflow/dialog run under the real skin and StrictMode. */
export function AccountManagementProbe({
  initialPage = "accounts",
  initialAccount = "one",
}: {
  readonly initialPage?: "accounts" | "roles";
  readonly initialAccount?: string;
}) {
  const [page, setPage] = useState(initialPage),
    [accountId, setAccountId] = useState(initialAccount);
  const [query, setQuery] = useState<AccountListQuery>(() => ({
    page: 1,
    pageSize: 2,
    search: "",
  }));
  const topology = useMemo(() => createManagementTopology(), []);
  const { access, workflow } = topology;
  const snapshot = useExternalSnapshot(workflow);
  return (
    <AstryxProvider>
      <div data-management-controls>
        {(["success", "conflict", "duplicate", "timeout"] as const).map((mode) => (
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
        <button data-expire onClick={() => access.set({ phase: "expired" })}>
          Expire
        </button>
        <button
          data-reader
          onClick={() =>
            access.set({
              phase: "resolved",
              facts: {
                kind: "authenticated",
                identity: { ...owner, roleId: "view", capabilities: ["metrics:view"] },
              },
            })
          }
        >
          Reader
        </button>
        <button data-missing onClick={() => setAccountId("missing")}>
          Missing
        </button>
        <button
          data-external-revision
          onClick={() => {
            topology.changeRevision(accountId);
            void workflow.select(accountId).catch(() => {});
          }}
        >
          External change
        </button>
      </div>
      {page === "accounts" ? (
        <AccountsPage
          workflow={workflow}
          query={query}
          onQueryChange={setQuery}
          onBindRole={(id) => {
            setAccountId(id);
            setPage("roles");
          }}
          onOwnPasswordReset={() => {}}
        />
      ) : (
        <RoleManagementPage
          workflow={workflow}
          accountId={accountId}
          sessionEpoch={owner.sessionEpoch}
          onAccountSelection={setAccountId}
          onBack={() => setPage("accounts")}
        />
      )}
      <output data-management-summary>
        {JSON.stringify({
          ...topology.readCounts(),
          authorized: snapshot.authorized,
          mutation: snapshot.mutation.status,
          accountId,
        })}
      </output>
    </AstryxProvider>
  );
}
