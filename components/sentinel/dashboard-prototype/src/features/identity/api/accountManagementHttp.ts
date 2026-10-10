import type { ConsoleTransport } from "../../../core/api/transport/consoleEndpoint";
import { OpaqueIdentifierSchema, RequestKeySchema } from "../../../core/api/protocol/common";
import { parseConsoleInput } from "../../../core/api/protocol/parseInput";
import type { AccountManagementPort } from "./accountManagementPort";
import { ACCOUNT_ENDPOINTS } from "./accountManagementEndpoints";
import {
  AccountListQuerySchema,
  AccountMutationSchema,
  validAccountPage,
  validAccountRecord,
  validAccountAcknowledgement,
} from "./accountManagementWire";

/** Typed account consumer. No optimistic account generation, password caching or fixture fallback. */
export function createAccountManagementHttp(transport: ConsoleTransport): AccountManagementPort {
  return Object.freeze({
    async listAccounts(input, signal) {
      const query = parseConsoleInput(AccountListQuerySchema, input);
      return transport.send(
        {
          ...ACCOUNT_ENDPOINTS.List,
          accept: (value) =>
            validAccountPage(value) &&
            value.page === query.page &&
            value.pageSize === query.pageSize &&
            value.items.every((item) => query.status === undefined || item.status === query.status),
        },
        { signal, query },
      );
    },
    async readAccount(accountId, signal) {
      const id = parseConsoleInput(OpaqueIdentifierSchema, accountId);
      return transport.send(
        {
          ...ACCOUNT_ENDPOINTS.Read,
          accept: (value) => value === null || (value.id === id && validAccountRecord(value)),
        },
        { signal, pathParams: [id] },
      );
    },
    async mutateAccount(input, signal) {
      const body = parseConsoleInput(AccountMutationSchema, input);
      return transport.send(
        {
          ...ACCOUNT_ENDPOINTS.Command,
          accept: (value) => validAccountAcknowledgement(value, body),
        },
        { signal, body, requestKey: body.requestKey },
      );
    },
    async readAccountOperation(requestKey, signal) {
      const key = parseConsoleInput(RequestKeySchema, requestKey);
      return transport.send(
        {
          ...ACCOUNT_ENDPOINTS.Operation,
          accept: (value) =>
            value.requestKey === key &&
            (value.status !== "completed" || validAccountRecord(value.account)),
        },
        { signal, pathParams: [key] },
      );
    },
  } satisfies AccountManagementPort);
}
