import { z } from "zod";
import { OpaqueIdentifierSchema, utf16BoundedString } from "../../../core/api/protocol/common";
import { SESSION_CAPABILITY } from "../../../core/session/capabilities";
import { WriteOnlySecretSchema } from "../../../shared/api/writeOnlySecretWire";
import { IDENTITY_ROLE } from "../model/account";

export const UsernameSchema = utf16BoundedString(200).min(1).regex(/\S/);
export const RoleIdSchema = z.enum([IDENTITY_ROLE.Admin, IDENTITY_ROLE.View]);
export const SessionIdentitySchema = z.strictObject({
  accountId: OpaqueIdentifierSchema,
  username: UsernameSchema,
  roleId: RoleIdSchema,
  capabilities: z
    .array(z.enum([SESSION_CAPABILITY.MetricsView, SESSION_CAPABILITY.RulesWrite]))
    .max(2),
  sessionEpoch: OpaqueIdentifierSchema,
});
export type SessionIdentityWire = z.infer<typeof SessionIdentitySchema>;

/** A view account can never carry write authority; duplicates indicate malformed server facts. */
export function validSessionWire(value: SessionIdentityWire): boolean {
  return (
    new Set(value.capabilities).size === value.capabilities.length &&
    (value.roleId !== IDENTITY_ROLE.View ||
      !value.capabilities.includes(SESSION_CAPABILITY.RulesWrite))
  );
}

export const SessionReadSchema = SessionIdentitySchema.nullable();
export const BootstrapSnapshotSchema = z.discriminatedUnion("initialized", [
  z.strictObject({ initialized: z.literal(true) }),
  z.strictObject({
    initialized: z.literal(false),
    setupAvailable: z.boolean(),
    operatorAuthorized: z.boolean(),
  }),
]);
export const LoginInputSchema = z.strictObject({
  username: UsernameSchema,
  password: WriteOnlySecretSchema,
});
