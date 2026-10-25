import { z } from "zod";
import { NON_BLANK_WIRE_CONTENT, utf16BoundedString } from "../../core/api/protocol/common";
import { isSupportedConfigurationSourceEndpoint } from "../protocol/configurationSourceEndpoint";
import { WriteOnlySecretSchema } from "./writeOnlySecretWire";

/** Write-only fields share shape between bootstrap and source administration; no secrets appear in read schemas. */
export { WriteOnlySecretSchema };
export const MAX_CONFIGURATION_ENDPOINT_UNITS = 2048;
export const ConfigurationEndpointSchema = utf16BoundedString(MAX_CONFIGURATION_ENDPOINT_UNITS)
  .regex(/^https?:\/\/[^/?#@\s\\]+(?:\/[^?#\s\\]*)?$/i)
  .refine(isSupportedConfigurationSourceEndpoint)
  .meta({ format: "uri" });
const NoAuthenticationSchema = z.strictObject({ mode: z.literal("none") });
const CredentialReferenceSchema = z.strictObject({
  mode: z.literal("credential-reference"),
  reference: utf16BoundedString(512).min(1).regex(NON_BLANK_WIRE_CONTENT).meta({ writeOnly: true }),
});
export const ConfigurationSourceInputSchema = z.discriminatedUnion("provider", [
  z.strictObject({
    provider: z.literal("nacos"),
    endpoint: ConfigurationEndpointSchema,
    namespace: utf16BoundedString(200),
    authentication: z.discriminatedUnion("mode", [
      NoAuthenticationSchema,
      CredentialReferenceSchema,
      z.strictObject({
        mode: z.literal("direct"),
        username: utf16BoundedString(200)
          .min(1)
          .regex(NON_BLANK_WIRE_CONTENT)
          .meta({ writeOnly: true }),
        password: WriteOnlySecretSchema,
      }),
    ]),
  }),
  z.strictObject({
    provider: z.literal("consul"),
    endpoint: ConfigurationEndpointSchema,
    datacenter: utf16BoundedString(200),
    authentication: z.discriminatedUnion("mode", [
      NoAuthenticationSchema,
      CredentialReferenceSchema,
      z.strictObject({ mode: z.literal("direct"), aclToken: WriteOnlySecretSchema }),
    ]),
  }),
]);
