import { z } from "zod";
import { WriteOnlySecretSchema } from "../../../shared/api/configurationSourceWire";
import { PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH } from "../model/passwordPolicy";

/** The current server session selects the account. Confirmation is local UI validation, not a wire field. */
export const OwnPasswordInputSchema = z.strictObject({
  currentPassword: WriteOnlySecretSchema,
  newPassword: WriteOnlySecretSchema.min(PASSWORD_MIN_LENGTH).max(PASSWORD_MAX_LENGTH),
});
export const OwnPasswordReceiptSchema = z.strictObject({
  sessionDisposition: z.literal("reauthenticate"),
});
