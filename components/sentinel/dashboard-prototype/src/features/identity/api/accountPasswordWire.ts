import { utf16BoundedString } from "../../../core/api/protocol/common";
import { PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH } from "../model/passwordPolicy";

/** New account passwords share one UTF-16 limit in runtime and generated JSON Schema. */
export const NewAccountPasswordSchema = utf16BoundedString(PASSWORD_MAX_LENGTH)
  .min(PASSWORD_MIN_LENGTH)
  .meta({ writeOnly: true });
