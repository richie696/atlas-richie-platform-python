import { z } from "zod";
import {
  OpaqueIdentifierSchema,
  PageNumberSchema,
  PageSizeSchema,
  CONSOLE_WIRE_LIMIT,
  TotalCountSchema,
  RequestKeySchema,
  UtcInstantSchema,
  utf16BoundedString,
} from "../../../core/api/protocol/common";
import { ACCOUNT_STATUS, IDENTITY_ROLE } from "../model/account";
import { ACCOUNT_SEARCH_MAX_LENGTH } from "../model/accountManagement";
import { NewAccountPasswordSchema } from "./accountPasswordWire";
import { RoleIdSchema, UsernameSchema } from "./identityAccessWire";

const MAX_ACCOUNT_REVISION = "9223372036854775807";

function positiveDecimalPattern(maximum: string): RegExp {
  const alternatives = [`[1-9][0-9]{0,${maximum.length - 2}}`];
  for (let index = 0; index < maximum.length; index++) {
    const maximumDigit = Number(maximum[index]);
    const minimumDigit = index === 0 ? 1 : 0;
    if (maximumDigit <= minimumDigit) continue;
    const remainingDigits = maximum.length - index - 1;
    const suffix = remainingDigits === 0 ? "" : `[0-9]{${remainingDigits}}`;
    alternatives.push(`${maximum.slice(0, index)}[${minimumDigit}-${maximumDigit - 1}]${suffix}`);
  }
  alternatives.push(maximum);
  return new RegExp(`^(?:${alternatives.join("|")})$`);
}

/** Canonical positive SQL BIGINT revision transported as a decimal string without precision loss. */
export const AccountRevisionSchema = z.string().regex(positiveDecimalPattern(MAX_ACCOUNT_REVISION));

export const AccountStatusSchema = z.enum([ACCOUNT_STATUS.Active, ACCOUNT_STATUS.Disabled]);
/** Safe read facts only. Credentials, display names and UI confirmation fields are not account records. */
export const AccountRecordSchema = z.strictObject({
  id: OpaqueIdentifierSchema,
  username: UsernameSchema,
  roleId: RoleIdSchema,
  status: AccountStatusSchema,
  builtIn: z.boolean(),
  lastLoginAt: UtcInstantSchema.nullable(),
  revision: AccountRevisionSchema,
  lastActiveAdmin: z.boolean(),
});
export const AccountListQuerySchema = z.strictObject({
  page: PageNumberSchema,
  pageSize: PageSizeSchema,
  search: utf16BoundedString(ACCOUNT_SEARCH_MAX_LENGTH),
  status: AccountStatusSchema.optional(),
});
export const AccountPageSchema = z.strictObject({
  items: z.array(AccountRecordSchema).max(CONSOLE_WIRE_LIMIT.PageSize),
  page: PageNumberSchema,
  pageSize: PageSizeSchema,
  total: TotalCountSchema,
});
export const AccountCreateInputSchema = z.strictObject({
  username: UsernameSchema,
  password: NewAccountPasswordSchema,
  roleId: RoleIdSchema,
});
export const AccountMutationSchema = z.discriminatedUnion("kind", [
  z.strictObject({
    kind: z.literal("create"),
    requestKey: RequestKeySchema,
    input: AccountCreateInputSchema,
  }),
  z.strictObject({
    kind: z.literal("status"),
    requestKey: RequestKeySchema,
    accountId: OpaqueIdentifierSchema,
    revision: AccountRevisionSchema,
    status: AccountStatusSchema,
  }),
  z.strictObject({
    kind: z.literal("role"),
    requestKey: RequestKeySchema,
    accountId: OpaqueIdentifierSchema,
    revision: AccountRevisionSchema,
    roleId: RoleIdSchema,
  }),
  z.strictObject({
    kind: z.literal("reset_password"),
    requestKey: RequestKeySchema,
    accountId: OpaqueIdentifierSchema,
    revision: AccountRevisionSchema,
    password: NewAccountPasswordSchema,
  }),
  z.strictObject({
    kind: z.literal("delete"),
    requestKey: RequestKeySchema,
    accountId: OpaqueIdentifierSchema,
    revision: AccountRevisionSchema,
  }),
]);
const ACCOUNT_FINAL_RECEIPTS = [
  z.strictObject({
    status: z.literal("completed"),
    requestKey: RequestKeySchema,
    account: AccountRecordSchema,
  }),
  z.strictObject({
    status: z.literal("rejected"),
    requestKey: RequestKeySchema,
    reason: z.enum([
      "username_taken",
      "last_admin",
      "built_in",
      "self_operation",
      "validation",
      "conflict",
      "not_found",
    ]),
  }),
] as const;
export const AccountCommandObservationSchema = z.discriminatedUnion(
  "status",
  ACCOUNT_FINAL_RECEIPTS,
);
export const AccountOperationObservationSchema = z.discriminatedUnion("status", [
  z.strictObject({ status: z.literal("not-found"), requestKey: RequestKeySchema }),
  ...ACCOUNT_FINAL_RECEIPTS,
]);

/** Conservative fact validation, not a substitute for the backend's transactional last-admin protection. */
export function validAccountRecord(value: z.infer<typeof AccountRecordSchema>): boolean {
  const activeAdmin =
    value.status === ACCOUNT_STATUS.Active && value.roleId === IDENTITY_ROLE.Admin;
  return (!value.builtIn && !value.lastActiveAdmin) || activeAdmin;
}

/** Page count is a directory fact, never an observation coverage denominator. */
export function validAccountPage(value: z.infer<typeof AccountPageSchema>): boolean {
  const remaining = Math.max(0, value.total - (value.page - 1) * value.pageSize);
  return (
    value.items.length === Math.min(value.pageSize, remaining) &&
    new Set(value.items.map((item) => item.id)).size === value.items.length &&
    value.items.every(validAccountRecord)
  );
}

/** Command acknowledgement is correlated with this input, never with whichever row is currently selected. */
export function validAccountAcknowledgement(
  value: z.infer<typeof AccountCommandObservationSchema>,
  input: z.infer<typeof AccountMutationSchema>,
): boolean {
  if (value.requestKey !== input.requestKey) return false;
  if (value.status !== "completed") return true;
  const account = value.account;
  if (!validAccountRecord(account)) return false;
  if (input.kind === "create")
    return (
      account.username === input.input.username &&
      account.roleId === input.input.roleId &&
      account.status === ACCOUNT_STATUS.Active &&
      !account.builtIn
    );
  return (
    account.id === input.accountId &&
    account.revision !== input.revision &&
    (input.kind === "status"
      ? account.status === input.status
      : input.kind === "role"
        ? account.roleId === input.roleId
        : input.kind === "delete"
          ? account.status === ACCOUNT_STATUS.Disabled
          : true)
  );
}
