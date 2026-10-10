import { defineUrl, HttpMethod } from "@richie696/react-framework";
import { z } from "zod";
import type {
  ConsoleTransport,
  ConsoleEndpoint,
} from "../../../core/api/transport/consoleEndpoint";
import { parseConsoleInput } from "../../../core/api/protocol/parseInput";
import type { OwnPasswordPort } from "./ownPasswordPort";
import { OwnPasswordInputSchema, OwnPasswordReceiptSchema } from "./ownPasswordWire";

export const OWN_PASSWORD_ENDPOINT: ConsoleEndpoint<z.infer<typeof OwnPasswordReceiptSchema>> =
  Object.freeze({
    url: defineUrl("/api/v1/auth/password", { method: HttpMethod.POST }),
    response: OwnPasswordReceiptSchema,
    successStatus: 200,
    command: true,
    idempotency: "none",
    csrf: true,
    expireOnUnauthorized: true,
    errors: [
      "invalid_request",
      "current_password_invalid",
      "unauthenticated",
      "csrf_failed",
      "validation_failed",
      "rate_limited",
      "service_unavailable",
    ],
  } satisfies ConsoleEndpoint<z.infer<typeof OwnPasswordReceiptSchema>>);
/** Once dispatched, an unverifiable password result cannot be replayed by the adapter. */
export function createOwnPasswordHttp(transport: ConsoleTransport): OwnPasswordPort {
  return Object.freeze({
    async changeOwnPassword(input, signal) {
      return transport.send(OWN_PASSWORD_ENDPOINT, {
        signal,
        body: parseConsoleInput(OwnPasswordInputSchema, input),
      });
    },
  } satisfies OwnPasswordPort);
}
