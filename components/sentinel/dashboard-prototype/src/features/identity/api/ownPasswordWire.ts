import { z } from "zod";
import { WriteOnlySecretSchema } from "../../../shared/api/configurationSourceWire";
import { NewAccountPasswordSchema } from "./accountPasswordWire";

/** The current server session selects the account. Confirmation is local UI validation, not a wire field. */
export const OwnPasswordInputSchema = z.strictObject({
  currentPassword: WriteOnlySecretSchema,
  newPassword: NewAccountPasswordSchema,
});
export const OwnPasswordReceiptSchema = z.strictObject({
  sessionDisposition: z.literal("reauthenticate"),
});
