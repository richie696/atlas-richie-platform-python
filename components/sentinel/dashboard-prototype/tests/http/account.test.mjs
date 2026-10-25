import assert from "node:assert/strict";
import { test } from "node:test";
import { http, HttpResponse } from "msw/http";
import { setupServer } from "msw/node";
import { createConsoleTransport } from "../../src/core/api/transport/consoleTransport";
import { createAccountManagementHttp } from "../../src/features/identity/api/accountManagementHttp";
import { createOwnPasswordHttp } from "../../src/features/identity/api/ownPasswordHttp";
import { createIdentityHttp } from "../../src/features/identity/api/identityHttp";
import { createAccountManagementWorkflow } from "../../src/features/identity/application/accountManagementWorkflow";
import { createOwnPasswordWorkflow } from "../../src/features/identity/application/ownPasswordWorkflow";

const origin = "http://account-http.test",
  csrf = "D".repeat(48),
  signal = () => new AbortController().signal;
const record = {
  id: "account/用户",
  username: "operator",
  roleId: "view",
  status: "active",
  builtIn: false,
  lastLoginAt: null,
  revision: "1",
  lastActiveAdmin: false,
};
const identity = {
  accountId: "admin-account",
  username: "admin",
  roleId: "admin",
  capabilities: ["metrics:view", "rules:write"],
  sessionEpoch: "session-one",
};
const session = {
  read: () => ({ phase: "resolved", facts: { kind: "authenticated", identity } }),
  subscribe: () => () => {},
};
const response = (request, body, status = 200) =>
  HttpResponse.json(body, {
    status,
    headers: { "x-request-id": request.headers.get("x-request-id"), "x-sentinel-csrf": csrf },
  });
async function runHttp(handlers, run) {
  const server = setupServer(
    http.get(`${origin}/api/v1/auth/me`, ({ request }) => response(request, identity)),
    ...handlers,
  );
  server.listen({ onUnhandledRequest: "error" });
  let sequence = 0;
  const transport = createConsoleTransport({
    baseUrl: origin,
    owner: () => "account-owner",
    onUnauthorized: () => {},
    requestId: () => `accounts-${++sequence}`,
  });
  try {
    await createIdentityHttp(transport).readSession(signal());
    await run(createAccountManagementHttp(transport), createOwnPasswordHttp(transport));
  } finally {
    transport.dispose();
    server.close();
  }
}
test("ACCOUNT-HTTP: server page/encoded target are explicit; nullable absence is not a substitute row", async () => {
  let query;
  await runHttp(
    [
      http.get(`${origin}/api/v1/accounts`, ({ request }) => {
        query = new URL(request.url).searchParams;
        return response(request, { items: [record], page: 2, pageSize: 1, total: 2 });
      }),
      http.get(`${origin}/api/v1/accounts/:id`, ({ request, params }) =>
        response(request, params.id === record.id ? record : null),
      ),
    ],
    async (port) => {
      assert.deepEqual(
        await port.listAccounts(
          { page: 2, pageSize: 1, search: " 用户 ", status: "active" },
          signal(),
        ),
        { items: [record], page: 2, pageSize: 1, total: 2 },
      );
      assert.deepEqual(
        [...query],
        [
          ["page", "2"],
          ["pageSize", "1"],
          ["search", " 用户 "],
          ["status", "active"],
        ],
      );
      assert.deepEqual(await port.readAccount(record.id, signal()), record);
      assert.equal(await port.readAccount("missing", signal()), null);
    },
  );
});
test("ACCOUNT-HTTP-WORKFLOW: server-side last-admin race remains a conflict until an authoritative detail reread", async () => {
  const latest = { ...record, roleId: "admin", lastActiveAdmin: true, revision: "2" };
  let detailReads = 0,
    writes = 0;
  await runHttp(
    [
      http.get(`${origin}/api/v1/accounts/:id`, ({ request }) => {
        detailReads++;
        return response(request, detailReads === 1 ? record : latest);
      }),
      http.post(`${origin}/api/v1/accounts/commands`, async ({ request }) => {
        writes++;
        const body = await request.json();
        assert.deepEqual(body, {
          kind: "status",
          requestKey: "disable-last-admin-race",
          accountId: record.id,
          revision: record.revision,
          status: "disabled",
        });
        assert.equal(request.headers.get("idempotency-key"), body.requestKey);
        return response(request, {
          status: "rejected",
          requestKey: body.requestKey,
          reason: "last_admin",
        });
      }),
    ],
    async (port) => {
      const workflow = createAccountManagementWorkflow(
        port,
        identity,
        session,
        () => "disable-last-admin-race",
      );
      try {
        const selected = await workflow.select(record.id);
        assert.equal(selected.lastActiveAdmin, false, "the initial detail is intentionally stale");

        const receipt = await workflow.setStatus(selected, "disabled");
        assert.deepEqual(receipt, {
          status: "rejected",
          requestKey: "disable-last-admin-race",
          reason: "last_admin",
        });
        assert.equal(workflow.getSnapshot().mutation.status, "conflict");
        assert.equal(workflow.getSnapshot().detail.data.status, "active");
        assert.equal(workflow.getSnapshot().detail.data.lastActiveAdmin, false);
        assert.equal(writes, 1);

        const refreshed = await workflow.select(record.id);
        assert.deepEqual(
          [refreshed.status, refreshed.roleId, refreshed.lastActiveAdmin, refreshed.revision],
          ["active", "admin", true, "2"],
          "only the explicit authoritative reread may replace the stale selected detail",
        );
        assert.equal(workflow.getSnapshot().mutation.status, "idle");
        assert.equal(writes, 1, "reading current state must not replay the rejected command");
        assert.equal(detailReads, 2);
      } finally {
        workflow.dispose();
      }
    },
  );
});
test("ACCOUNT-SEARCH: directory request accepts the UTF-16 boundary and rejects overflow before dispatch", async () => {
  let dispatched = 0;
  await runHttp(
    [
      http.get(`${origin}/api/v1/accounts`, ({ request }) => {
        dispatched++;
        return response(request, { items: [], page: 1, pageSize: 20, total: 0 });
      }),
    ],
    async (port) => {
      for (const search of ["x".repeat(200), "😀".repeat(100)])
        assert.equal(
          (await port.listAccounts({ page: 1, pageSize: 20, search }, signal())).total,
          0,
        );
      assert.equal(dispatched, 2);
      for (const search of ["x".repeat(201), `${"x".repeat(199)}😀`])
        await assert.rejects(
          port.listAccounts({ page: 1, pageSize: 20, search }, signal()),
          (error) => error.code === "console_request_invalid",
        );
      assert.equal(dispatched, 2);
    },
  );
});
test("ACCOUNT-READ: foreign/stale page, duplicate IDs, inconsistent administrator facts and credentials fail closed", async () => {
  const page = { items: [record], page: 1, pageSize: 2, total: 1 };
  for (const body of [
    { ...page, page: 2 },
    { ...page, total: 3 },
    { ...page, items: [record, record], total: 2 },
    { ...page, items: [{ ...record, lastActiveAdmin: true }] },
    { ...page, items: [{ ...record, builtIn: true }] },
    { ...page, items: [{ ...record, password: "PRIVATE-READ" }] },
    { ...page, items: [{ ...record, lastLoginAt: "today" }] },
  ])
    await runHttp(
      [http.get(`${origin}/api/v1/accounts`, ({ request }) => response(request, body))],
      async (port) => {
        await assert.rejects(
          port.listAccounts({ page: 1, pageSize: 2, search: "" }, signal()),
          (error) =>
            error.code === "console_response_invalid" && !JSON.stringify(error).includes("PRIVATE"),
        );
      },
    );
  await runHttp(
    [
      http.get(`${origin}/api/v1/accounts/:id`, ({ request }) =>
        response(request, { ...record, id: "foreign" }),
      ),
    ],
    async (port) => {
      await assert.rejects(
        port.readAccount(record.id, signal()),
        (error) => error.code === "console_response_invalid",
      );
    },
  );
});
test("ACCOUNT-REVISION-WIRE: signed BIGINT revisions stay canonical decimal strings above JS safe integer", async () => {
  const revision = "9223372036854775807",
    maximumRecord = { ...record, revision };
  await runHttp(
    [
      http.get(`${origin}/api/v1/accounts`, ({ request }) =>
        response(request, { items: [maximumRecord], page: 1, pageSize: 1, total: 1 }),
      ),
    ],
    async (port) => {
      assert.equal(
        (await port.listAccounts({ page: 1, pageSize: 1, search: "" }, signal())).items[0].revision,
        revision,
      );
    },
  );
  await runHttp(
    [
      http.post(`${origin}/api/v1/accounts/commands`, async ({ request }) => {
        const body = await request.json();
        assert.equal(body.revision, revision);
        return response(request, {
          status: "rejected",
          requestKey: body.requestKey,
          reason: "conflict",
        });
      }),
    ],
    async (port) => {
      assert.deepEqual(
        await port.mutateAccount(
          {
            kind: "status",
            requestKey: "max-revision",
            accountId: record.id,
            revision,
            status: "disabled",
          },
          signal(),
        ),
        { status: "rejected", requestKey: "max-revision", reason: "conflict" },
      );
    },
  );
});
test("ACCOUNT-COMMAND: five closed variants preserve original key/revision, safe lookup permits not-found", async () => {
  const inputs = [
    {
      kind: "create",
      requestKey: "create-one",
      input: { username: "operator", password: "PRIVATE-NEW-PASSWORD", roleId: "view" },
    },
    {
      kind: "status",
      requestKey: "status-one",
      accountId: record.id,
      revision: record.revision,
      status: "disabled",
    },
    {
      kind: "role",
      requestKey: "role-one",
      accountId: record.id,
      revision: record.revision,
      roleId: "admin",
    },
    {
      kind: "reset_password",
      requestKey: "reset-one",
      accountId: record.id,
      revision: record.revision,
      password: "PRIVATE-RESET-PASSWORD",
    },
    { kind: "delete", requestKey: "delete-one", accountId: record.id, revision: record.revision },
  ];
  let writes = 0;
  await runHttp(
    [
      http.post(`${origin}/api/v1/accounts/commands`, async ({ request }) => {
        const body = await request.json();
        assert.deepEqual(body, inputs[writes++]);
        assert.equal(request.headers.get("idempotency-key"), body.requestKey);
        assert.equal(request.headers.get("x-sentinel-csrf"), csrf);
        return response(request, {
          status: "completed",
          requestKey: body.requestKey,
          account: {
            ...record,
            revision: "2",
            ...(body.kind === "status"
              ? { status: body.status }
              : body.kind === "delete"
                ? { status: "disabled" }
                : body.kind === "role"
                  ? { roleId: body.roleId }
                  : {}),
          },
        });
      }),
      http.get(`${origin}/api/v1/accounts/operations/:key`, ({ request, params }) =>
        response(request, { status: "not-found", requestKey: params.key }),
      ),
    ],
    async (port) => {
      for (const input of inputs)
        assert.equal((await port.mutateAccount(input, signal())).status, "completed");
      assert.deepEqual(await port.readAccountOperation("create-one", signal()), {
        status: "not-found",
        requestKey: "create-one",
      });
      assert.equal(writes, 5);
    },
  );
});
test("ACCOUNT-ACK: unverifiable command stays unknown; original-key inspection does not replay or release on not-found", async () => {
  for (const receipt of [
    { status: "not-found", requestKey: "original-key" },
    { status: "completed", requestKey: "other-key", account: record },
    {
      status: "completed",
      requestKey: "original-key",
      account: { ...record, username: "foreign" },
    },
    {
      status: "completed",
      requestKey: "original-key",
      account: { ...record, password: "PRIVATE-REPLY" },
    },
  ]) {
    let writes = 0,
      lookups = 0;
    await runHttp(
      [
        http.post(`${origin}/api/v1/accounts/commands`, ({ request }) => {
          writes++;
          return response(request, receipt);
        }),
        http.get(`${origin}/api/v1/accounts/operations/:key`, ({ request, params }) => {
          lookups++;
          return response(request, { status: "not-found", requestKey: params.key });
        }),
      ],
      async (port) => {
        const workflow = createAccountManagementWorkflow(
          port,
          identity,
          session,
          () => "original-key",
        );
        try {
          await assert.rejects(
            workflow.create({
              username: "operator",
              password: "PRIVATE-NEW-PASSWORD",
              roleId: "view",
            }),
          );
          assert.equal(workflow.getSnapshot().mutation.status, "result-unknown");
          await assert.rejects(
            workflow.create({
              username: "operator",
              password: "PRIVATE-NEW-PASSWORD",
              roleId: "view",
            }),
          );
          assert.equal((await workflow.inspect()).status, "not-found");
          assert.equal(workflow.getSnapshot().mutation.status, "result-unknown");
          assert.equal(writes, 1);
          assert.equal(lookups, 1);
          assert.equal(JSON.stringify(workflow.getSnapshot()).includes("PRIVATE"), false);
        } finally {
          workflow.dispose();
        }
      },
    );
  }
});
test("ACCOUNT-ACK-INTEGRATION: committed role change with lost HTTP receipt is inspected once and refreshes authoritative reads", async () => {
  let authoritative = { ...record },
    writes = 0,
    lookups = 0,
    detailReads = 0,
    listReads = 0;
  const requestKey = "role-committed-response-lost";
  const receipts = new Map();
  await runHttp(
    [
      http.get(`${origin}/api/v1/accounts`, ({ request }) => {
        listReads++;
        const url = new URL(request.url);
        return response(request, {
          items: [authoritative],
          page: Number(url.searchParams.get("page")),
          pageSize: Number(url.searchParams.get("pageSize")),
          total: 1,
        });
      }),
      http.get(`${origin}/api/v1/accounts/:accountId`, ({ request, params }) => {
        detailReads++;
        return response(request, params.accountId === record.id ? authoritative : null);
      }),
      http.post(`${origin}/api/v1/accounts/commands`, async ({ request }) => {
        writes++;
        const body = await request.json();
        assert.deepEqual(body, {
          kind: "role",
          requestKey,
          accountId: record.id,
          revision: record.revision,
          roleId: "admin",
        });
        assert.equal(request.headers.get("idempotency-key"), requestKey);
        authoritative = { ...authoritative, roleId: "admin", revision: "2" };
        receipts.set(requestKey, { status: "completed", requestKey, account: authoritative });
        // The authority committed the operation but the client received a retry-unsafe 503.
        return response(request, { error: { code: "dependency_unavailable" } }, 503);
      }),
      http.get(`${origin}/api/v1/accounts/operations/:key`, ({ request, params }) => {
        lookups++;
        return response(
          request,
          receipts.get(String(params.key)) ?? {
            status: "not-found",
            requestKey: String(params.key),
          },
        );
      }),
    ],
    async (port) => {
      const workflow = createAccountManagementWorkflow(port, identity, session, () => requestKey);
      try {
        await workflow.list({ page: 1, pageSize: 20, search: "" });
        const selected = await workflow.select(record.id);
        await assert.rejects(
          workflow.setRole(selected, {
            accountId: record.id,
            revision: record.revision,
            roleId: "admin",
          }),
        );
        assert.equal(workflow.getSnapshot().mutation.status, "result-unknown");
        assert.equal(workflow.getSnapshot().operation?.requestKey, requestKey);
        assert.equal(writes, 1);

        assert.deepEqual(await workflow.inspect(), receipts.get(requestKey));
        const snapshot = workflow.getSnapshot();
        assert.equal(snapshot.mutation.status, "success");
        assert.equal(snapshot.mutation.result.roleId, "admin");
        assert.equal(snapshot.directory.data.items[0].roleId, "admin");
        assert.equal(snapshot.detail.data.roleId, "admin");
        assert.equal(snapshot.operation?.requestKey, requestKey);
        assert.equal(writes, 1, "inspection and refresh must not replay the mutation");
        assert.equal(lookups, 1, "inspect must use exactly the original request key once");
        assert.equal(listReads, 2, "confirmed inspection must refresh the active directory query");
        assert.equal(detailReads, 2, "confirmed inspection must refresh the active detail query");
      } finally {
        workflow.dispose();
      }
    },
  );
});
test("ACCOUNT-REVISION: a changed target/effect or unchanged revision cannot acknowledge the requested status mutation", async () => {
  for (const account of [
    record,
    { ...record, id: "foreign", revision: "2", status: "disabled" },
    { ...record, revision: "2" },
  ])
    await runHttp(
      [
        http.post(`${origin}/api/v1/accounts/commands`, ({ request }) =>
          response(request, { status: "completed", requestKey: "status-one", account }),
        ),
      ],
      async (port) => {
        await assert.rejects(
          port.mutateAccount(
            {
              kind: "status",
              requestKey: "status-one",
              accountId: record.id,
              revision: record.revision,
              status: "disabled",
            },
            signal(),
          ),
          (error) => error.code === "console_response_invalid",
        );
      },
    );
});
test("IDENTITY-WRITE: inactive/confirmation/target secrets and invalid paging never dispatch; safe domain rejection stays distinct from HTTP denial", async () => {
  let dispatched = 0;
  await runHttp(
    [
      http.all(`${origin}/api/v1/accounts*`, ({ request }) => {
        dispatched++;
        return response(request, {
          status: "rejected",
          requestKey: "original-key",
          reason: "last_admin",
        });
      }),
      http.post(`${origin}/api/v1/auth/password`, ({ request }) => {
        dispatched++;
        return response(request, {});
      }),
    ],
    async (port, password) => {
      for (const input of [
        {
          kind: "role",
          requestKey: "original-key",
          accountId: record.id,
          revision: "1",
          roleId: "admin",
          password: "PRIVATE",
        },
        {
          kind: "create",
          requestKey: "original-key",
          input: {
            username: "operator",
            password: "PRIVATE-NEW-PASSWORD",
            roleId: "view",
            displayName: "bad",
          },
        },
      ])
        await assert.rejects(
          port.mutateAccount(input, signal()),
          (error) => error.code === "console_request_invalid",
        );
      for (const revision of ["revision-one", "0", "01", "9223372036854775808"])
        await assert.rejects(
          port.mutateAccount(
            {
              kind: "status",
              requestKey: "invalid-revision",
              accountId: record.id,
              revision,
              status: "disabled",
            },
            signal(),
          ),
          (error) => error.code === "console_request_invalid",
        );
      await assert.rejects(port.listAccounts({ page: 0, pageSize: 1, search: "" }, signal()));
      await assert.rejects(
        password.changeOwnPassword(
          {
            currentPassword: "PRIVATE-CURRENT",
            newPassword: "PRIVATE-NEW-PASSWORD",
            accountId: "foreign",
          },
          signal(),
        ),
      );
      await assert.rejects(
        password.changeOwnPassword(
          {
            currentPassword: "PRIVATE-CURRENT",
            newPassword: "PRIVATE-NEW-PASSWORD",
            confirm: "PRIVATE-NEW-PASSWORD",
          },
          signal(),
        ),
      );
      assert.equal(dispatched, 0);
      assert.deepEqual(
        await port.mutateAccount(
          {
            kind: "status",
            requestKey: "original-key",
            accountId: record.id,
            revision: record.revision,
            status: "disabled",
          },
          signal(),
        ),
        { status: "rejected", requestKey: "original-key", reason: "last_admin" },
      );
      assert.equal(dispatched, 1);
    },
  );
});
test("PASSWORD-HTTP: only the implemented reauthentication policy is accepted; malformed acknowledgement stays unknown without credential replay", async () => {
  for (const receipt of [
    { sessionDisposition: "reauthenticate" },
    { sessionDisposition: "retained" },
    { sessionDisposition: "retained", password: "PRIVATE-RESPONSE" },
    {},
  ]) {
    let writes = 0;
    await runHttp(
      [
        http.post(`${origin}/api/v1/auth/password`, async ({ request }) => {
          writes++;
          const requestUrl = new URL(request.url);
          assert.equal(requestUrl.pathname, "/api/v1/auth/password");
          assert.equal(requestUrl.search, "", "password values never enter URL/query state");
          assert.equal(request.headers.get("x-sentinel-csrf"), csrf);
          assert.equal(request.headers.has("idempotency-key"), false);
          assert.doesNotMatch(
            [...request.headers.values()].join("\n"),
            /PRIVATE-(?:CURRENT|NEW-PASSWORD)/,
          );
          assert.deepEqual(await request.json(), {
            currentPassword: "PRIVATE-CURRENT",
            newPassword: "PRIVATE-NEW-PASSWORD",
          });
          return response(request, receipt);
        }),
      ],
      async (_port, password) => {
        const workflow = createOwnPasswordWorkflow(password, identity, session);
        try {
          const submission = workflow.submit({
            current: "PRIVATE-CURRENT",
            next: "PRIVATE-NEW-PASSWORD",
            confirm: "PRIVATE-NEW-PASSWORD",
          });
          if (receipt.sessionDisposition === "reauthenticate" && Object.keys(receipt).length === 1)
            assert.deepEqual(await submission, receipt);
          else {
            await assert.rejects(submission);
            assert.equal(workflow.getSnapshot().status, "result-unknown");
            await assert.rejects(
              workflow.submit({
                current: "PRIVATE-CURRENT",
                next: "PRIVATE-NEW-PASSWORD",
                confirm: "PRIVATE-NEW-PASSWORD",
              }),
            );
          }
          assert.equal(writes, 1);
          assert.equal(JSON.stringify(workflow.getSnapshot()).includes("PRIVATE"), false);
          assert.equal(JSON.stringify(workflow.getSnapshot()).includes("SYNTHETIC"), false);
        } finally {
          workflow.dispose();
        }
      },
    );
  }
});
test("PASSWORD-HTTP: stable rejection codes remain correctable while 5xx is an unknown write outcome", async () => {
  for (const failure of [
    { status: 400, code: "current_password_invalid", commandStatus: "error" },
    { status: 422, code: "validation_failed", commandStatus: "error" },
    { status: 403, code: "csrf_failed", commandStatus: "error" },
    { status: 503, code: "service_unavailable", commandStatus: "result-unknown" },
  ]) {
    let writes = 0;
    await runHttp(
      [
        http.post(`${origin}/api/v1/auth/password`, ({ request }) => {
          writes++;
          return response(
            request,
            { error: { code: failure.code, requestId: request.headers.get("x-request-id") } },
            failure.status,
          );
        }),
      ],
      async (_port, password) => {
        const workflow = createOwnPasswordWorkflow(password, identity, session);
        try {
          await assert.rejects(
            workflow.submit({
              current: "PRIVATE-CURRENT",
              next: "PRIVATE-NEW-PASSWORD",
              confirm: "PRIVATE-NEW-PASSWORD",
            }),
            (error) => error.code === failure.code && error.status === failure.status,
          );
          const snapshot = workflow.getSnapshot();
          assert.equal(snapshot.status, failure.commandStatus, failure.code);
          assert.equal(snapshot.error.code, failure.code);
          assert.equal(snapshot.error.status, failure.status);
          assert.doesNotMatch(JSON.stringify(snapshot), /PRIVATE|SYNTHETIC/);
          await assert.rejects(
            workflow.submit({
              current: "PRIVATE-CURRENT",
              next: "PRIVATE-NEW-PASSWORD",
              confirm: "PRIVATE-NEW-PASSWORD",
            }),
            failure.commandStatus === "result-unknown"
              ? (error) => error.kind === "duplicate"
              : undefined,
          );
          assert.equal(writes, failure.commandStatus === "result-unknown" ? 1 : 2);
        } finally {
          workflow.dispose();
        }
      },
    );
  }
});
