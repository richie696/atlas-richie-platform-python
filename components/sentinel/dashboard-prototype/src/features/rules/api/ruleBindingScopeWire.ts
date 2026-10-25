import { z } from "zod";
import {
  OpaqueIdentifierSchema,
  UtcInstantSchema,
  utf16BoundedString,
} from "../../../core/api/protocol/common";

export const RuleBindingScopeCatalogSchema = z.strictObject({
  asOf: UtcInstantSchema,
  environments: z
    .array(z.strictObject({ id: OpaqueIdentifierSchema, name: utf16BoundedString(200).min(1) }))
    .max(1000),
  applications: z
    .array(
      z.strictObject({
        id: OpaqueIdentifierSchema,
        environmentId: OpaqueIdentifierSchema,
        name: utf16BoundedString(200).min(1),
      }),
    )
    .max(1000),
});
