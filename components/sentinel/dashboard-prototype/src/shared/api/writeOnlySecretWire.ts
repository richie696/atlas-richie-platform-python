import { z } from "zod";
import { utf16BoundedString } from "../../core/api/protocol/common";
import { WRITE_ONLY_SECRET_MAX_LENGTH } from "../model/secretLimits";

/** Common write-only credential shape; readers never include persisted secret values. */
export const WriteOnlySecretSchema = utf16BoundedString(WRITE_ONLY_SECRET_MAX_LENGTH)
  .min(1)
  .meta({ writeOnly: true });
